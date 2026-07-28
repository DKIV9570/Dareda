"""把多项分析合成一句话:牌 / 打法 / 运气 各占多少锅。

## 分解

以 2.5 位(四人中性)为原点,实际名次的偏离拆成三项:

    实际名次 - 2.5  =  (deal_ev - 2.5)      牌与座次的贡献
                     + (self_ev - deal_ev)  打法的贡献
                     + (actual  - self_ev)  运气(残差)

三项相加恒等于左边,是闭合分解,不是凑出来的权重。

* ``deal_ev`` —— **均等水平**蒙特卡洛的期望名次:四家用同一强度重打这副牌。
  座位之间的差异这时只剩牌和座次,所以它衡量"这副牌/这个位置本身值几位"。
* ``self_ev`` —— **真实水平**蒙特卡洛(``self-luck``)的期望名次:四家各按自己
  实测强度重打。它比 ``deal_ev`` 好多少,就是你的打法相对这桌人赚到的。

**为什么必须要有均等基线**:``self_ev`` 里同时含了牌和打法两样东西,单拿它当
"牌好不好"会把打法算进牌里去,四象限会系统性偏。多跑一次均等基线才能把两者分开。

## 四象限

牌好不好(``deal_ev`` 与 2.5 比)× 打得好不好(``self_ev`` 比 ``deal_ev`` 好多少),
再叠一句运气偏顺还是偏背。名次是**越小越好**,所以各处的正负号要当心。
"""

from __future__ import annotations

from dataclasses import dataclass

NEUTRAL = 2.5
"""四人局的中性名次。"""

BAND = 0.2
"""判"好/烂"的死区,单位是名次。小于这个幅度算"一般",避免把噪声读成结论。"""

LUCK_LO, LUCK_HI = 0.25, 0.75
"""运气判定的分位阈值。``luck_q``(实际名次在"自己水平分布"里的中位秩,0=最好端、
1=最差端方向;这里定义成"你赢过自身多少比例的重演",越高越顺)落在下 1/4 → 背、
上 1/4 → 顺、中间 50% → 愿赌服输。用**分位**而不是均值差,才不会被偏态分布骗
(双峰分布里 4 位可能很常见,均值差却把它误读成"惨背")。"""


def _stars(delta: float, *, span: float = 0.8) -> str:
    """把一个"越正越好"的偏移画成五颗星。``span`` 是满格对应的幅度。"""
    ratio = max(-1.0, min(1.0, delta / span))
    filled = round((ratio + 1) / 2 * 5)
    return "★" * filled + "☆" * (5 - filled)


@dataclass
class Diagnosis:
    hero: int
    actual: int
    """实际名次 1..4。"""
    deal_ev: float
    """均等水平下,这个座位的期望名次。"""
    self_ev: float
    """真实水平下(self-luck)的期望名次。"""
    deal_trials: int = 0
    self_trials: int = 0
    strengths: object = None
    """四家强度({seat: SeatStrength}),供展示;分解本身不用它。"""
    self_pcts: object = None
    """真实水平下 hero 的名次分布 [1位%, 2位%, 3位%, 4位%],供画横条 + 定运气。"""

    # ---- 三项贡献(统一成"正数=对你有利") ----
    @property
    def deal_gain(self) -> float:
        """牌与座次带来的名次收益。正=这副牌/这个座位占便宜。"""
        return NEUTRAL - self.deal_ev

    @property
    def skill_gain(self) -> float:
        """打法带来的额外收益。正=你的打法比这桌平均水平强,把期望往前推了。"""
        return self.deal_ev - self.self_ev

    @property
    def luck_gain(self) -> float:
        """运气残差。正=实际比期望好(顺),负=比期望差(背)。"""
        return self.self_ev - self.actual

    # ---- 分类 ----
    @property
    def deal_label(self) -> str:
        if self.deal_gain > BAND:
            return "好牌"
        if self.deal_gain < -BAND:
            return "烂牌"
        return "牌一般"

    @property
    def skill_label(self) -> str:
        if self.skill_gain > BAND:
            return "打得好"
        if self.skill_gain < -BAND:
            return "打得烂"
        return "打得一般"

    @property
    def luck_q(self) -> float | None:
        """实际名次在"自己水平分布"里的中位秩:"你赢过了自身多少比例的重演"。

        0 ≈ 落在你最差的一端(很背),1 ≈ 落在最好的一端(很顺),0.5 ≈ 典型结果。
        用 ½·P(=实际名次) 处理并列,任意偏态都稳。没有分布(self_pcts 缺)时返回 None。
        """
        if not self.self_pcts:
            return None
        p = [x / 100 for x in self.self_pcts]  # p[0]=1位 ... p[3]=4位
        a = self.actual  # 1..4,数字越大名次越差
        p_worse = sum(p[k] for k in range(4) if (k + 1) > a)
        p_equal = p[a - 1]
        return p_worse + 0.5 * p_equal

    @property
    def luck_label(self) -> str:
        q = self.luck_q
        if q is None:  # 退化:没有分布时回落到均值差
            if self.luck_gain > BAND:
                return "运气顺"
            if self.luck_gain < -BAND:
                return "运气背"
            return "运气正常"
        if q >= LUCK_HI:
            return "运气顺"
        if q <= LUCK_LO:
            return "运气背"
        return "运气正常"

    def ev_loss_rank(self) -> int | None:
        """hero 的 EV loss 在四家里的名次(1=最低=打得最干净)。没有 strengths 时 None。"""
        if not self.strengths:
            return None
        order = sorted(range(4), key=lambda s: self.strengths[s].ev_loss)
        return order.index(self.hero) + 1

    def skill_note(self) -> str:
        """一句直接、无噪声的水平读数:EV loss 值 + 四家里的排名。

        「打法」那颗星是这副牌上的名次增量,20~30 次蒙特卡洛下有 ±0.2 位噪声、会在
        边界抖;EV loss 是逐决策直接测的,不抖,才是判水平该看的。
        """
        r = self.ev_loss_rank()
        if r is None:
            return ""
        val = self.strengths[self.hero].ev_loss
        tag = {1: "四家最低", 2: "四家第 2 低", 3: "四家第 3 低", 4: "四家最高"}[r]
        return f"EV loss {val:.2f}({tag})"

    def _p_worse_equal(self) -> float:
        """P(名次 ≥ 实际):你的同水平打到"这么差或更差"的概率。"""
        if not self.self_pcts:
            return 0.0
        p = [x / 100 for x in self.self_pcts]
        return sum(p[k] for k in range(4) if (k + 1) >= self.actual)

    def luck_stars(self) -> str:
        """运气五颗星:直接由 ``luck_q`` 画(顺=满、背=空),和判定同源。"""
        q = self.luck_q
        if q is None:
            return _stars(self.luck_gain)
        filled = round(q * 5)
        return "★" * filled + "☆" * (5 - filled)

    @property
    def quadrant(self) -> str:
        """四象限标签。牌或打法落在死区时给出较温和的说法。"""
        d, s = self.deal_label, self.skill_label
        if d == "牌一般" or s == "打得一般":
            return f"{d},{s}"
        return {
            ("好牌", "打得好"): "好牌打好了",
            ("好牌", "打得烂"): "好牌打烂了",
            ("烂牌", "打得好"): "烂牌打好了",
            ("烂牌", "打得烂"): "烂牌打烂了",
        }[(d, s)]

    def verdict(self) -> str:
        """一句话结论:四象限 + 运气。"""
        q = self.quadrant
        if self.luck_label == "运气背":
            return f"{q},而且这把运气还背。"
        if self.luck_label == "运气顺":
            return f"{q},这把运气偏顺。"
        return f"{q},运气也没什么话说。"

    def check_closure(self) -> float:
        """分解闭合性自检:三项之和应等于 实际名次-2.5。返回残差(应为 0)。"""
        total = self.deal_gain + self.skill_gain + self.luck_gain
        return abs(total - (NEUTRAL - self.actual))

    def render(self, name: str = "") -> str:
        who = f"座{self.hero}" + (f" {name}" if name else "")
        lines = [
            f"=== 这把怪谁?  {who} ===",
            "",
            f"  牌   {_stars(self.deal_gain)}  {self.deal_label:<6}"
            f"均等水平下,这个座位期望 {self.deal_ev:.2f} 位",
            f"  打   {_stars(self.skill_gain)}  {self.skill_label:<6}"
            f"你的打法把期望推到 {self.self_ev:.2f} 位({self.skill_gain:+.2f})"
            + (f"   ← {self.skill_note()}" if self.skill_note() else ""),
            f"  运   {self.luck_stars()}  {self.luck_label:<6}"
            + (f"你的同水平里,{self.actual} 位或更差占 "
               f"{self._p_worse_equal()*100:.0f}%"
               if self.self_pcts else
               f"实际 {self.actual} 位,比期望差 {abs(self.luck_gain):.2f} 位"),
            "",
            f"  → {self.verdict()}",
            "",
            "  名次分解(以 2.5 位为中性起点,正数=对你有利):",
            f"    牌与座次 {self.deal_gain:+.2f}  +  打法 {self.skill_gain:+.2f}"
            f"  +  运气 {self.luck_gain:+.2f}  =  {NEUTRAL - self.actual:+.2f}",
        ]
        if self.deal_trials or self.self_trials:
            lines.append(
                f"    (每条基线 {self.self_trials} 次蒙特卡洛)"
            )
        return "\n".join(lines)

    def bars_text(self) -> str:
        """名次分布横条(文本版):这副牌上,你自己水平各名次的概率。"""
        if not self.self_pcts:
            return ""
        out = ["  这副牌上,你的名次概率(横条按 1/2/3/4 位切分,▲=实际):"]
        out.append(self._one_bar("你的真实水平  ", self.self_pcts, mark=self.actual))
        out.append("                  " + "".join(f"{p}位".ljust(9) for p in (1, 2, 3, 4)))
        return "\n".join(out)

    @staticmethod
    def _one_bar(label: str, pcts, width: int = 36, mark: int | None = None) -> str:
        glyphs = "①②③④"
        seg = ""
        for i, pct in enumerate(pcts):
            w = round(pct / 100 * width)
            seg += glyphs[i] * w
        seg = (seg + glyphs[3] * width)[:width]  # 补齐/截断到固定宽
        pct_txt = "  ".join(f"{p:.0f}%" for p in pcts)
        tail = f"  (实际 {mark} 位)" if mark else ""
        return f"  {label}[{seg}]  {pct_txt}{tail}"


def run_diagnose(
    record,
    humans,
    hero: int,
    weights,
    *,
    trials: int = 20,
    jobs=None,
    base_seed: int = 0,
    progress=None,
) -> "Diagnosis":
    """完整跑一次诊断,返回 :class:`Diagnosis`。CLI 与 GUI 共用这一套编排。

    分三步:测四家强度 → 均等水平基线(定牌/座)→ 真实水平(定打法 + 运气分布)。

    :param progress: 可选回调 ``(phase, done, total)``,phase ∈
        ``{"strength", "baseline", "real"}``。strength 阶段 total 未知,done=total=0。
    """
    from .calibrate import calibrate
    from .strength import measure_strength
    from ..montecarlo import SelfStrengthMonteCarlo, resolve_jobs
    from ..rules import placements

    jobs = resolve_jobs(jobs, trials)

    if progress:
        progress("strength", 0, 0)
    strengths = measure_strength(record, humans, weights.make_engine())
    seat_params = {s: calibrate(strengths[s].q_samples, strengths[s].ev_loss) for s in range(4)}

    # 均等基线:四家统一用"这桌平均水平",座位差异只剩牌与座次
    avg_ev = sum(strengths[s].ev_loss for s in range(4)) / 4
    ref = calibrate(strengths[hero].q_samples, avg_ev)
    equal_params = {s: ref for s in range(4)}

    def _cb(phase):
        return (lambda i, total, res: progress(phase, i, total)) if progress else None

    deal_dist = SelfStrengthMonteCarlo(
        record, equal_params, weights, base_seed=base_seed
    ).run_all(trials, jobs=jobs, progress=_cb("baseline"))[hero]

    self_dist = SelfStrengthMonteCarlo(
        record, seat_params, weights, base_seed=base_seed
    ).run_all(trials, jobs=jobs, progress=_cb("real"))[hero]

    dx = Diagnosis(
        hero=hero,
        actual=placements(record.final_scores)[hero],
        deal_ev=deal_dist.avg_placement,
        self_ev=self_dist.avg_placement,
        deal_trials=deal_dist.n,
        self_trials=self_dist.n,
        self_pcts=self_dist.pcts(),
    )
    dx.strengths = strengths  # 附带,给需要展示强度表的调用方
    return dx

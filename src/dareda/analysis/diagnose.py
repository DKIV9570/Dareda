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
    def luck_label(self) -> str:
        if self.luck_gain > BAND:
            return "运气顺"
        if self.luck_gain < -BAND:
            return "运气背"
        return "运气正常"

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
            f"你的打法把期望推到 {self.self_ev:.2f} 位({self.skill_gain:+.2f})",
            f"  运   {_stars(self.luck_gain)}  {self.luck_label:<6}"
            f"实际 {self.actual} 位,比期望{'好' if self.luck_gain >= 0 else '差'} "
            f"{abs(self.luck_gain):.2f} 位",
            "",
            f"  → {self.verdict()}",
            "",
            "  名次分解(以 2.5 位为中性起点,正数=对你有利):",
            f"    牌与座次 {self.deal_gain:+.2f}  +  打法 {self.skill_gain:+.2f}"
            f"  +  运气 {self.luck_gain:+.2f}  =  {NEUTRAL - self.actual:+.2f}",
        ]
        if self.deal_trials or self.self_trials:
            lines.append(
                f"    (均等基线 {self.deal_trials} 次 / 真实水平 {self.self_trials} 次蒙特卡洛)"
            )
        return "\n".join(lines)

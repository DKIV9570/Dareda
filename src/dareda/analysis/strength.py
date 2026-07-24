"""在人类日志上测每个对手相对 Mortal 的强度。

产出两个度量:

* **一致率**:该家实际动作 == Mortal 首选(greedy argmax)的比例。计算不需要动作
  索引映射,只比 mjai 动作串。缺点:把"真的弱"、"风格不同"、"决策本身是近平手"
  三件事混在一起。
* **EV loss**:每决策 ``Q(Mortal 首选) - Q(该家实际动作)`` 的平均,单位是 Mortal 的
  Q 值(近似顺位期望)。按分歧的**代价**加权 —— 近平手上的分歧几乎不计,明显错误
  才计。这是更干净的强度度量,标定应当用它。

做法:用 :class:`~dareda.engine.logfollow.LogFollowEngine` 的测量钩子跑 identity
replay(四家全照日志打,忠实复现原局)。它借 KyokuReplay 拿到**正确的决策时机**
(Mortal 在摸牌等使能事件上决策,不是在打牌事件上),每个决策做一次影子评估读出
Mortal 的选择与 ``q_values``,但仍采用日志动作 —— 牌局按人类原样推进。这比自己
手搓时机靠谱得多(手搓最容易把打牌事件当决策点,读不到 Q)。

EV loss 需要把人类动作映射到 libriichi 的 46 维动作空间,见 :func:`action_index`。
打牌占决策绝大多数、映射干净;鸣牌/立直也覆盖了。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# mjai 牌串 → 0..36(34 种 + 三张赤 5 占 34/35/36),即 libriichi 打牌动作的下标
_SUIT_BASE = {"m": 0, "p": 9, "s": 18}
_HONOR = {"E": 27, "S": 28, "W": 29, "N": 30, "P": 31, "F": 32, "C": 33}
_AKA = {"5mr": 34, "5pr": 35, "5sr": 36}

RIICHI_IDX = 37
CHI_LOW_IDX, CHI_MID_IDX, CHI_HIGH_IDX = 38, 39, 40
PON_IDX = 41
KAN_IDX = 42
AGARI_IDX = 43
RYUKYOKU_IDX = 44
PASS_IDX = 45

_AGENT_EVENTS = frozenset(
    {"dahai", "chi", "pon", "daiminkan", "ankan", "kakan", "reach", "hora", "ryukyoku"}
)


def tile37(mjai: str) -> int:
    """mjai 牌串 → 0..36。"""
    if mjai in _AKA:
        return _AKA[mjai]
    if mjai in _HONOR:
        return _HONOR[mjai]
    num = int(mjai[0])
    return _SUIT_BASE[mjai[1]] + num - 1


def _chi_index(pai: str, consumed: list[str]) -> int:
    """吃:按被吃牌在顺子里的位置分 low/mid/high。"""
    def rank(t: str) -> int:
        return 5 if t in _AKA else int(t[0])

    p = rank(pai)
    others = sorted(rank(c) for c in consumed)
    if p < others[0]:
        return CHI_LOW_IDX
    if p > others[1]:
        return CHI_HIGH_IDX
    return CHI_MID_IDX


def action_index(ev: dict) -> int | None:
    """一个 mjai 动作事件 → 46 维动作空间下标。认不出返回 None。"""
    t = ev["type"]
    if t == "dahai":
        return tile37(ev["pai"])
    if t == "reach":
        return RIICHI_IDX
    if t == "chi":
        return _chi_index(ev["pai"], ev["consumed"])
    if t == "pon":
        return PON_IDX
    if t in ("daiminkan", "ankan", "kakan"):
        return KAN_IDX
    if t == "hora":
        return AGARI_IDX
    if t == "ryukyoku":
        return RYUKYOKU_IDX
    return None


def _decompact_q(q_values: list[float], mask_bits: int) -> dict[int, float]:
    """meta 里的 q_values 是按合法动作压缩的,mask_bits 标出哪些下标合法。
    还原成 {动作下标: q}。"""
    legal = [i for i in range(46) if mask_bits & (1 << i)]
    if len(legal) != len(q_values):
        # 版本差异兜底:按顺序对齐能对上的部分
        legal = legal[: len(q_values)]
    return dict(zip(legal, q_values))


@dataclass
class SeatStrength:
    seat: int
    decisions: int
    agreements: int
    ev_loss_sum: float
    measured_ev: int
    """能算 EV loss 的决策数(动作能映射且 Q 齐全)。"""
    q_samples: list = None  # type: ignore[assignment]
    """每决策的合法动作 Q 值数组,供标定(见 calibrate.py)解析式求温度。"""
    losses: list = None  # type: ignore[assignment]
    """每决策的 ``(小局标签, 动作类型, 牌, EV 损失, Mortal 首选)``,用于看错误是否集中。"""

    def __post_init__(self):
        if self.q_samples is None:
            self.q_samples = []
        if self.losses is None:
            self.losses = []

    def concentration(self, top: int = 5) -> float:
        """最差 top 个决策贡献了总 EV 损失的多大比例。高 ⇒ 错误集中在少数致命路口。"""
        if not self.losses:
            return 0.0
        vals = sorted((l[3] for l in self.losses), reverse=True)
        total = sum(vals)
        return sum(vals[:top]) / total if total > 0 else 0.0

    def worst(self, top: int = 5) -> list:
        return sorted(self.losses, key=lambda l: -l[3])[:top]

    @property
    def agreement_rate(self) -> float:
        return self.agreements / self.decisions if self.decisions else 1.0

    @property
    def ev_loss(self) -> float:
        return self.ev_loss_sum / self.measured_ev if self.measured_ev else 0.0


def measure_strength(record, human_events_per_hand, mortal_engine, *, seats=range(4)):
    """在整场人类日志上测每家强度。返回 {seat: SeatStrength}。

    :param record: :class:`~dareda.record.GameRecord`,提供每小局牌山。
    """
    import libriichi

    from ..deal import split_wall
    from ..engine.logfollow import LogFollowEngine

    result = {s: SeatStrength(s, 0, 0, 0.0, 0) for s in seats}

    cur_label = [""]

    def sink(seat, human_ev, mortal_reaction):
        if seat in result:
            _score(result[seat], human_ev, mortal_reaction, cur_label[0])

    for hand, events in zip(record.hands, human_events_per_hand):
        cur_label[0] = hand.label
        eng = LogFollowEngine(events, {0, 1, 2, 3}, mortal_engine, measure_sink=sink)
        runner = libriichi.arena.KyokuReplay(eng)
        w = split_wall(hand.paishan, hand.oya)
        runner.run(
            haipai=[list(h) for h in w.haipai],
            yama=list(w.yama),
            rinshan=list(w.rinshan),
            dora_indicators=list(w.dora_indicators),
            ura_indicators=list(w.ura_indicators),
            kyoku=hand.chang * 4 + hand.ju,
            honba=hand.ben,
            kyotaku=hand.liqibang,
            scores=list(hand.scores),
        )
    return result


def _score(st: SeatStrength, human_ev: dict, mortal_reaction: dict, label: str = "") -> None:
    st.decisions += 1
    # 一致率:动作类型 + 关键字段是否相同
    same = mortal_reaction.get("type") == human_ev["type"] and mortal_reaction.get(
        "pai"
    ) == human_ev.get("pai")
    if same:
        st.agreements += 1

    meta = mortal_reaction.get("meta") or {}
    q = meta.get("q_values")
    mask = meta.get("mask_bits")
    if not q or mask is None:
        return
    qmap = _decompact_q(q, mask)
    if not qmap:
        return
    idx = action_index(human_ev)
    if idx is None or idx not in qmap:
        return
    loss = max(qmap.values()) - qmap[idx]
    st.ev_loss_sum += loss
    st.measured_ev += 1
    st.q_samples.append(list(qmap.values()))
    st.losses.append(
        (label, human_ev["type"], human_ev.get("pai", ""), loss, mortal_reaction.get("pai", ""))
    )


def render_strength(strengths: dict, names=None) -> str:
    lines = ["对手强度(相对 Mortal,在人类原局上测):"]
    lines.append(f"  {'座':<4}{'玩家':<12}{'决策':>5}{'一致率':>8}{'EV loss':>10}")
    for s in sorted(strengths):
        st = strengths[s]
        nm = names[s] if names and s < len(names) else ""
        lines.append(
            f"  {s:<4}{nm:<12}{st.decisions:>5}{st.agreement_rate*100:>7.0f}%"
            f"{st.ev_loss:>10.3f}"
        )
    return "\n".join(lines)

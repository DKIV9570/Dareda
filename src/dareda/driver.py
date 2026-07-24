"""spec §1.1 全序列 driver。

把半庄重定义为"K 个 hand 的固定序列",严格按原牌谱的 ``(chang, ju, ben)`` 走:

* replay 里庄家和了,**不额外插入连庄局**
* replay 里庄家没和,**不跳过序列里的本场局**
* 任一玩家点数 < 0 → 立即终止,允许实际局数 K' < K
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from .engine.base import HandSetup, ReplayEngine
from .record import GameRecord, Hand
from .rules import HandOutcome, HandSettlement, TableState, placements, settle


class StopReason(Enum):
    COMPLETED = "completed"
    """走完全部 K 局。"""
    BUSTED = "busted"
    """有人被击飞。§2:最优博弈下的击飞本身就是结论。"""


@dataclass
class HandLog:
    index: int
    hand: Hand
    scores_before: tuple[int, int, int, int]
    outcome: HandOutcome
    settlement: HandSettlement

    @property
    def label(self) -> str:
        return self.hand.label


@dataclass
class ReplayResult:
    record: GameRecord
    logs: list[HandLog] = field(default_factory=list)
    stop_reason: StopReason = StopReason.COMPLETED
    final_scores: tuple[int, int, int, int] = (25000,) * 4
    riichi_sticks_left: int = 0
    determinism_tag: str = ""
    """spec §4:build + device,浮点抖动可能翻边,必须随结果一起存。"""

    @property
    def hands_played(self) -> int:
        return len(self.logs)

    @property
    def placements(self) -> list[int]:
        return placements(self.final_scores)


def initial_state(record: GameRecord, start_score: int = 25000) -> TableState:
    """replay 的起始点数取原牌谱第一局的开局点数,没有就用 25000。"""
    if record.hands:
        return TableState(scores=list(record.hands[0].scores), riichi_sticks=record.hands[0].liqibang)
    return TableState(scores=[start_score] * 4)


def run_replay(
    record: GameRecord,
    engine: ReplayEngine,
    *,
    state: TableState | None = None,
    determinism_tag: str = "",
) -> ReplayResult:
    """按固定序列跑完 replay。"""
    st = state.copy() if state else initial_state(record)
    result = ReplayResult(record=record, determinism_tag=determinism_tag)

    for i, hand in enumerate(record.hands):
        setup = HandSetup(
            hand=hand,
            scores=tuple(st.scores),  # type: ignore[arg-type]
            riichi_sticks=st.riichi_sticks,
        )
        outcome = engine.play_hand(setup)
        stl = settle(st, outcome, honba=hand.ben)

        result.logs.append(
            HandLog(
                index=i,
                hand=hand,
                scores_before=tuple(st.scores),  # type: ignore[arg-type]
                outcome=outcome,
                settlement=stl,
            )
        )
        st = TableState(list(stl.scores_after), stl.riichi_sticks_after)

        if stl.busted:
            result.stop_reason = StopReason.BUSTED
            break

    result.final_scores = tuple(st.scores)  # type: ignore[assignment]
    result.riichi_sticks_left = st.riichi_sticks
    return result


# --------------------------------------------------------------------------- §6 输出


def _dwidth(s: str) -> int:
    """终端显示宽度 —— 中日韩全角字符占两列,不算进去表格会歪。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _dwidth(s))


def comparison_table(result: ReplayResult) -> str:
    """spec §6 的最小可用对照表。"""
    rec = result.record
    human_scores = rec.final_scores
    rows = [
        ("", "人类原局", "Mortal replay"),
        (
            "最终名次",
            _fmt_placements(human_scores),
            _fmt_placements(result.final_scores),
        ),
        ("最终点数", _fmt_scores(human_scores), _fmt_scores(result.final_scores)),
        ("实际局数", f"K = {rec.K}", f"K' = {result.hands_played}"),
        (
            "终止原因",
            "—",
            "走完" if result.stop_reason is StopReason.COMPLETED else "击飞",
        ),
    ]
    widths = [max(_dwidth(str(r[c])) for r in rows) for c in range(3)]
    out = []
    for idx, row in enumerate(rows):
        out.append(" | ".join(_pad(str(v), widths[c]) for c, v in enumerate(row)))
        if idx == 0:
            out.append("-+-".join("-" * w for w in widths))
    if result.determinism_tag:
        out.append(f"\n确定性标签: {result.determinism_tag}")
    if rec.meta.get("synthetic"):
        out.append("\n⚠ 合成数据,数字无意义 —— 只证明管道通了")
    return "\n".join(out)


def per_hand_table(result: ReplayResult) -> str:
    """加分项:逐局点数变化对照。"""
    label_w = max([_dwidth("局")] + [_dwidth(log.label) for log in result.logs])
    lines = [f"{_pad('局', label_w)} {'座0':>7} {'座1':>7} {'座2':>7} {'座3':>7}  结果"]
    for log in result.logs:
        s = log.settlement.scores_after
        lines.append(
            f"{_pad(log.label, label_w)} {s[0]:>7} {s[1]:>7} {s[2]:>7} {s[3]:>7}"
            f"  {log.outcome.outcome.value}"
        )
    return "\n".join(lines)


def _fmt_scores(scores) -> str:
    return "—" if scores is None else " / ".join(str(s) for s in scores)


def _fmt_placements(scores) -> str:
    if scores is None:
        return "—"
    return " / ".join(f"{p}位" for p in placements(scores))

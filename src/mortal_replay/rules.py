"""spec §2 裁定表。

分工上有一条线要划清楚:**番符→基本点**是麻将规则引擎(libriichi)的事,这里不重
复实现。引擎只回报"不含本场棒和立直棒的基本点数增减",本模块在其之上叠加 §2 里
那几条 replay 特有的裁定:

======== ==================================================
钉死     牌山、庄位(由 ju 定)、本场数(用**标签**的 honba 计分)
浮动     立直棒、各局起始点数、杠宝牌/岭上牌
终止     任一玩家点数 < 0 立即结束;或走完 K 局
======== ==================================================

"本场用标签值"这条是刻意的:序列既然外生钉死,计分跟着标签走才自洽 —— replay 里
庄家连不连庄都不改变下一局的标签,那本场棒也不该由 replay 自己数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

RIICHI_STICK = 1000
HONBA_RON = 300
"""荣和:本场棒由放铳者一人全付。"""
HONBA_TSUMO_EACH = 100
"""自摸:每家各付 100×本场。"""


class Outcome(Enum):
    RON = "ron"
    TSUMO = "tsumo"
    RYUUKYOKU = "ryuukyoku"
    ABORTIVE = "abortive"
    """途中流局(九种九牌、四风连打、四杠散了、四家立直)。"""


@dataclass
class HandOutcome:
    """引擎回报的单局结果。

    ``base_deltas`` 不含本场棒、不含立直棒结算,但**包含**流局罚符(听牌罚符)。
    立直宣言时扣掉的 1000 点由 ``riichi_declarations`` 表达,不要预先扣进 deltas。
    """

    outcome: Outcome
    base_deltas: tuple[int, int, int, int]
    winners: tuple[int, ...] = ()
    loser: int | None = None
    """荣和的放铳者;自摸/流局为 None。"""
    riichi_declarations: tuple[int, ...] = ()
    """本局宣言立直的座次。"""
    pre_settled: bool = False
    """引擎是否**已经**把本场棒、立直宣言与立直棒回收算进了 ``base_deltas``。

    libriichi 拿得到 honba 和 kyotaku,一局打完给的就是终值,这时 :func:`settle`
    必须原样采纳、不能再叠一次。手写/脚本引擎则给"裸"点数,由 :func:`settle` 补。
    """
    kyotaku_after: int | None = None
    """``pre_settled`` 时引擎报告的局末立直棒数。"""
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.base_deltas) != 4:
            raise ValueError("base_deltas 必须是 4 项")
        if not self.pre_settled and sum(self.base_deltas) != 0:
            # 已结算的结果会因立直棒进出而不守恒,守恒性由引擎适配层自己校验
            raise ValueError(f"base_deltas 不守恒: {self.base_deltas} 和为 {sum(self.base_deltas)}")
        if self.outcome is Outcome.RON and self.loser is None and not self.pre_settled:
            raise ValueError("荣和必须给出放铳者")
        if self.pre_settled and self.kyotaku_after is None:
            raise ValueError("pre_settled 的结果必须给出 kyotaku_after")


@dataclass
class TableState:
    """跨局结转的状态。点数和立直棒都是 §2 里的"浮动"项。"""

    scores: list[int] = field(default_factory=lambda: [25000] * 4)
    riichi_sticks: int = 0

    def copy(self) -> "TableState":
        return TableState(list(self.scores), self.riichi_sticks)


@dataclass
class HandSettlement:
    deltas: tuple[int, int, int, int]
    """本局各家最终增减,含本场棒、立直宣言扣分、立直棒回收。"""
    scores_after: tuple[int, int, int, int]
    riichi_sticks_after: int
    busted: tuple[int, ...]
    """点数 < 0 的座次。非空 ⇒ replay 立即终止。"""


def settle(state: TableState, outcome: HandOutcome, honba: int) -> HandSettlement:
    """把引擎结果叠加本场棒与立直棒,推进桌面状态。

    ``honba`` 取**牌谱标签**里的本场数,不是 replay 自己数出来的。
    """
    if outcome.pre_settled:
        assert outcome.kyotaku_after is not None
        scores_after = tuple(state.scores[i] + outcome.base_deltas[i] for i in range(4))
        return HandSettlement(
            deltas=outcome.base_deltas,
            scores_after=scores_after,  # type: ignore[arg-type]
            riichi_sticks_after=outcome.kyotaku_after,
            busted=tuple(i for i, s in enumerate(scores_after) if s < 0),
        )

    deltas = list(outcome.base_deltas)

    # 立直宣言:每个宣言者扣 1000 进场
    sticks = state.riichi_sticks
    for seat in outcome.riichi_declarations:
        deltas[seat] -= RIICHI_STICK
        sticks += 1

    # 本场棒
    if honba and outcome.winners:
        if outcome.outcome is Outcome.RON:
            assert outcome.loser is not None
            total = HONBA_RON * honba
            # 多人荣和(头跳规则外)时本场棒只给一家,取离放铳者最近的
            head = _closest_winner(outcome.winners, outcome.loser)
            deltas[head] += total
            deltas[outcome.loser] -= total
        elif outcome.outcome is Outcome.TSUMO:
            winner = outcome.winners[0]
            for seat in range(4):
                if seat != winner:
                    deltas[seat] -= HONBA_TSUMO_EACH * honba
                    deltas[winner] += HONBA_TSUMO_EACH * honba

    # 立直棒回收:有人和了就全部归和牌者(多家荣和取头跳),流局则结转到下一局
    if outcome.winners and sticks:
        target = (
            _closest_winner(outcome.winners, outcome.loser)
            if outcome.outcome is Outcome.RON and outcome.loser is not None
            else outcome.winners[0]
        )
        deltas[target] += sticks * RIICHI_STICK
        sticks = 0

    scores_after = tuple(state.scores[i] + deltas[i] for i in range(4))
    busted = tuple(i for i, s in enumerate(scores_after) if s < 0)
    return HandSettlement(
        deltas=tuple(deltas),  # type: ignore[arg-type]
        scores_after=scores_after,  # type: ignore[arg-type]
        riichi_sticks_after=sticks,
        busted=busted,
    )


def _closest_winner(winners: tuple[int, ...], loser: int) -> int:
    """头跳:从放铳者的下家开始数,第一个和牌者。"""
    return min(winners, key=lambda w: (w - loser) % 4)


def final_ranking(scores) -> list[int]:
    """返回名次 → 座次。同点按座次小者优先(近似起家顺位,精算未实现)。"""
    return sorted(range(4), key=lambda s: (-scores[s], s))


def placements(scores) -> list[int]:
    """返回座次 → 名次(1..4)。"""
    order = final_ranking(scores)
    out = [0] * 4
    for rank, seat in enumerate(order, start=1):
        out[seat] = rank
    return out

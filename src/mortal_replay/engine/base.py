"""引擎适配层接口。

driver 只管"按序列喂 hand、按 §2 结算、判终止";一局牌**怎么打**完全交给引擎。
这条缝划在这里,是为了让 Mortal / libriichi 的接入、以及将来换别的 mjai bot,
都不影响上面的裁定逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..record import Hand
from ..rules import HandOutcome


@dataclass(frozen=True)
class HandSetup:
    """喂给引擎的一局开局条件。牌山和庄位是钉死的,点数和立直棒是浮动的。"""

    hand: Hand
    """原牌谱的小局,提供 paishan / chang / ju / ben。"""
    scores: tuple[int, int, int, int]
    """replay 演化出来的开局点数(不是牌谱里的)。"""
    riichi_sticks: int
    """replay 演化出来的场上立直棒。"""

    @property
    def oya(self) -> int:
        return self.hand.oya

    @property
    def honba(self) -> int:
        """§2:本场按**标签**取,不由 replay 演化。"""
        return self.hand.ben

    @property
    def paishan(self) -> tuple[int, ...]:
        return self.hand.paishan


class ReplayEngine(Protocol):
    """在指定牌山下打完一局,回报结果。"""

    def play_hand(self, setup: HandSetup) -> HandOutcome: ...

    def close(self) -> None: ...


class ScriptedEngine:
    """按预设脚本回报结果的假引擎 —— 给 driver / §2 结算做测试用。"""

    def __init__(self, outcomes: list[HandOutcome]):
        self._outcomes = list(outcomes)
        self._i = 0

    def play_hand(self, setup: HandSetup) -> HandOutcome:
        if self._i >= len(self._outcomes):
            raise RuntimeError("脚本用完了,driver 请求的局数超出预设")
        out = self._outcomes[self._i]
        self._i += 1
        return out

    def close(self) -> None:
        return None

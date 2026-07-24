"""Mortal counterfactual replay —— 在同一牌山下用 Mortal 重打人类牌谱。

当前面向雀魂(牌山明文,见 spec §3.2)。天凤支持要先做 MT19937+SHA512 牌山还原,
留在 :mod:`dareda.tenhou`(未实现)。
"""

from .deal import WallConvention, deal
from .driver import ReplayResult, comparison_table, per_hand_table, run_replay
from .record import GameRecord, Hand
from .rules import HandOutcome, Outcome, TableState, settle
from .verify import infer_convention, verify_record

__version__ = "0.1.0"

__all__ = [
    "deal",
    "WallConvention",
    "GameRecord",
    "Hand",
    "verify_record",
    "infer_convention",
    "Outcome",
    "HandOutcome",
    "TableState",
    "settle",
    "run_replay",
    "ReplayResult",
    "comparison_table",
    "per_hand_table",
    "__version__",
]

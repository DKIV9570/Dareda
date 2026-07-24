"""内部牌表示。

统一到天凤系的 0–135 index(spec §3.3):

    tile_id = kind * 4 + copy

    kind:  0..8   = 1m..9m
           9..17  = 1p..9p
           18..26 = 1s..9s
           27..33 = 东 南 西 北 白 发 中

赤 5 固定占用该 kind 的 copy 0,即 id 16 / 52 / 88。选这套表示是为了后续能
直接对接 libriichi / mjai / 天凤工具链,不用再翻译一次。
"""

from __future__ import annotations

NUM_KINDS = 34
NUM_TILES = 136
SUITS = "mpsz"

#: 5m / 5p / 5s 的 kind
RED_KINDS = (4, 13, 22)
#: 赤 5 的 tile id
RED_IDS = frozenset(k * 4 for k in RED_KINDS)


class TileError(ValueError):
    """牌编码相关的错误。"""


def kind_of(tid: int) -> int:
    return tid // 4


def copy_of(tid: int) -> int:
    return tid % 4


def is_red(tid: int) -> bool:
    return tid in RED_IDS


def kind_from_code(num: int, suit: str) -> int:
    """``(3, 'm') -> 2``。``num == 0`` 视作赤 5。"""
    if suit not in SUITS:
        raise TileError(f"未知花色: {suit!r}")
    base = SUITS.index(suit) * 9
    if suit == "z":
        if not 1 <= num <= 7:
            raise TileError(f"字牌序号越界: {num}{suit}")
        return 27 + num - 1
    if num == 0:
        return base + 4  # 赤 5
    if not 1 <= num <= 9:
        raise TileError(f"数牌序号越界: {num}{suit}")
    return base + num - 1


def kind_to_code(kind: int) -> str:
    """``2 -> '3m'``。不带赤信息,赤请用 :func:`tile_to_code`。"""
    if not 0 <= kind < NUM_KINDS:
        raise TileError(f"kind 越界: {kind}")
    if kind >= 27:
        return f"{kind - 27 + 1}z"
    return f"{kind % 9 + 1}{SUITS[kind // 9]}"


def tile_to_code(tid: int) -> str:
    """tile id → 雀魂风格字符串,赤 5 输出 ``0m`` / ``0p`` / ``0s``。"""
    if not 0 <= tid < NUM_TILES:
        raise TileError(f"tile id 越界: {tid}")
    if is_red(tid):
        return f"0{SUITS[kind_of(tid) // 9]}"
    return kind_to_code(kind_of(tid))


def hand_to_str(tids: list[int]) -> str:
    """把一手牌排序后渲染成人类可读串,调试用。"""
    return " ".join(tile_to_code(t) for t in sorted(tids))

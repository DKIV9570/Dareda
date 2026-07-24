"""配牌函数:``(牌山, 庄位) -> 四家起手``(spec §1.3)。

整个 replay 的地基。这里唯一有争议的是**牌山约定** —— 牌山数组的哪一段是配牌、
王牌在头还是在尾。不同平台/不同 parser 的实现并不一致,而这件事无法从文档推,
只能拿真牌谱撞:所以约定被做成可切换的枚举,由 §5 的断言来选出正确的那个
(:func:`dareda.verify.infer_convention`)。

发牌顺序本身没有歧义:庄 → 下家 → 对家 → 上家,3 轮每人 4 张,最后每人 1 张。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

HAIPAI_SIZE = 13
NUM_SEATS = 4
DEAD_WALL_SIZE = 14


class WallConvention(Enum):
    """牌山数组的布局约定。"""

    DEAD_WALL_TAIL = "dead_wall_tail"
    """``paishan[0:52]`` 是配牌,自摸从 52 往后走,末尾 14 张是王牌。

    雀魂常见 parser(majsoul-record-parser / Majsoul-Converter)采用这一种,
    是本项目的默认值。
    """

    DEAD_WALL_HEAD = "dead_wall_head"
    """开头 14 张是王牌,配牌从 ``paishan[14]`` 开始。留作真牌谱撞不上时的备选。"""

    @property
    def live_start(self) -> int:
        return DEAD_WALL_SIZE if self is WallConvention.DEAD_WALL_HEAD else 0


DEFAULT_CONVENTION = WallConvention.DEAD_WALL_TAIL


def seat_order(oya: int) -> list[int]:
    """庄 → 下家 → 对家 → 上家。"""
    return [(oya + i) % NUM_SEATS for i in range(NUM_SEATS)]


# --------------------------------------------------------------- 王牌区布局
#
# 王牌 14 张 = 7 墩 × 2。按"从数组高位往低位"数墩:
#
#     S1=(n-2, n-1)  S2=(n-4, n-3)  S3=(n-6, n-5)  S4 …  S7=(n-14, n-13)
#      └ 岭上 ─┘      └ 岭上 ─┘      └ 宝牌墩 ┘
#
# 规则:岭上从端头两墩取,宝牌指示牌是第 3 墩的上张,里宝是它的下张;
# 每开一次杠,指示牌往远离岭上的方向推一墩。
#
# 实测锚点(250101-1a2b3c4d… 15 小局):
#   dora[0] == paishan[n-5]   15/15
#   ura[0]  == paishan[n-6]    4/4
# 这两点一钉,整个布局唯一确定。但**那局一次杠都没有**,所以 dora[k>0] /
# ura[k>0] / 岭上牌全部只是按上述规则推出来的,尚无实测。拿到有杠的牌谱请跑
# verify_dead_wall() 补验。
RINSHAN_OFFSETS = (1, 2, 3, 4)
"""岭上牌的摸取顺序,值为"距数组末尾的偏移"(1 表示 paishan[-1])。"""
DORA_OFFSETS = (5, 7, 9, 11, 13)
URA_OFFSETS = (6, 8, 10, 12, 14)


@dataclass(frozen=True)
class DealResult:
    haipai: tuple[tuple[int, ...], ...]
    """按**座次**索引(不是按发牌顺序),``haipai[0]`` 恒为座 0 的起手。"""
    draw_cursor: int
    """配牌发完后,下一张自摸牌在 ``paishan`` 里的下标。"""
    dead_wall: tuple[int, ...]


def deal(
    paishan: list[int] | tuple[int, ...],
    oya: int,
    convention: WallConvention = DEFAULT_CONVENTION,
) -> DealResult:
    """按约定发配牌。纯函数 —— 同样的 ``(paishan, oya)`` 必然给出同样的结果。"""
    if not 0 <= oya < NUM_SEATS:
        raise ValueError(f"庄位越界: {oya}")
    n = len(paishan)
    if n < HAIPAI_SIZE * NUM_SEATS + DEAD_WALL_SIZE:
        raise ValueError(f"牌山过短: {n}")

    if convention is WallConvention.DEAD_WALL_HEAD:
        dead_wall = tuple(paishan[:DEAD_WALL_SIZE])
    else:
        dead_wall = tuple(paishan[n - DEAD_WALL_SIZE :])

    cursor = convention.live_start
    hands: list[list[int]] = [[] for _ in range(NUM_SEATS)]
    order = seat_order(oya)

    for _ in range(3):  # 3 轮,每人 4 张
        for seat in order:
            hands[seat].extend(paishan[cursor : cursor + 4])
            cursor += 4
    for seat in order:  # 最后每人 1 张
        hands[seat].append(paishan[cursor])
        cursor += 1

    assert all(len(h) == HAIPAI_SIZE for h in hands)
    return DealResult(
        haipai=tuple(tuple(h) for h in hands),
        draw_cursor=cursor,
        dead_wall=dead_wall,
    )


@dataclass(frozen=True)
class BoardSetup:
    """切好的牌山,字段与方向都按 ``libriichi::arena::Board`` 的约定对齐。

    libriichi 的 ``Board`` 把这几项做成了 pub 字段(上游注释:"The fields are all
    pub on purpose so the caller will be able to set the yama, doras, scores
    directly"),所以注入牌山**不需要改 Rust**,只要按它的方向把数组摆对。

    方向是这里唯一的陷阱 —— 三个 "goes backward (pop)" 的字段必须**倒序存放**,
    让 ``pop()`` 吐出的第一张正好是实际摸到的第一张。
    """

    haipai: tuple[tuple[int, ...], ...]
    """按座次索引。对应 ``Board.haipai: [[Tile; 13]; 4]``。"""
    yama: tuple[int, ...]
    """70 张牌山,**倒序**(``Board.yama`` goes backward)。"""
    rinshan: tuple[int, ...]
    """4 张岭上,**倒序**(``Board.rinshan`` goes backward)。"""
    dora_indicators: tuple[int, ...]
    """5 张宝牌指示牌,**倒序**(``Board.dora_indicators`` goes backward)。"""
    ura_indicators: tuple[int, ...]
    """5 张里宝指示牌,**正序**(``Board.ura_indicators`` goes forward)。"""
    first_draw: int
    """庄家的第一枚自摸,即 ``yama[-1]``。留着做断言。"""

    def as_board_kwargs(self) -> dict:
        return {
            "haipai": [list(h) for h in self.haipai],
            "yama": list(self.yama),
            "rinshan": list(self.rinshan),
            "dora_indicators": list(self.dora_indicators),
            "ura_indicators": list(self.ura_indicators),
        }


def split_wall(
    paishan: list[int] | tuple[int, ...],
    oya: int,
    convention: WallConvention = DEFAULT_CONVENTION,
) -> BoardSetup:
    """雀魂 136 张 paishan → libriichi ``Board`` 的五个桶。"""
    n = len(paishan)
    result = deal(paishan, oya, convention)
    live_end = n - DEAD_WALL_SIZE
    live = list(paishan[result.draw_cursor : live_end])
    if len(live) != 70:
        raise ValueError(f"活牌山应为 70 张,实得 {len(live)}(牌山约定选错了?)")

    pick = lambda offsets: tuple(paishan[n - off] for off in offsets)  # noqa: E731
    return BoardSetup(
        haipai=result.haipai,
        yama=tuple(reversed(live)),
        rinshan=tuple(reversed(pick(RINSHAN_OFFSETS))),
        dora_indicators=tuple(reversed(pick(DORA_OFFSETS))),
        ura_indicators=pick(URA_OFFSETS),
        first_draw=live[0],
    )

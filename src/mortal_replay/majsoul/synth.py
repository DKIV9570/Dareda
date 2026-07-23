"""合成雀魂牌谱 —— 在拿到真牌谱之前把管道跑通。

**它能验什么、不能验什么**(重要,别把绿灯当成对):

* 能验:发牌的索引算术、赤宝编解码往返、庄位推导、序列驱动、CLI 端到端。
  这里的发牌是**逐张游标**写的,和 :mod:`mortal_replay.deal` 的切片实现是两条
  独立代码路径,off-by-one 类的错会被撞出来。
* **不能验**:牌山约定本身(``paishan[0:52]`` 是不是配牌、王牌在头还是尾)。
  合成数据是按我们**假设**的约定造的,自证不了假设。这一条只能拿一份真牌谱过
  :func:`mortal_replay.verify.infer_convention`。在那之前,§5 的"绿"只代表自洽。
"""

from __future__ import annotations

import random

from ..deal import DEAD_WALL_SIZE, seat_order
from ..tiles import RED_KINDS, SUITS, kind_to_code

# 王牌里宝牌指示牌的位置尚未用真牌谱核对过,只影响合成数据的 doras 字段,
# 不参与 §5 断言。
_DORA_OFFSET = 5


def full_wall_codes(*, red_fives: bool = True) -> list[str]:
    """一副 136 张的牌,雀魂编码。"""
    codes: list[str] = []
    for kind in range(34):
        code = kind_to_code(kind)
        for copy in range(4):
            if red_fives and kind in RED_KINDS and copy == 0:
                codes.append(f"0{SUITS[kind // 9]}")
            else:
                codes.append(code)
    assert len(codes) == 136
    return codes


def _deal_by_cursor(wall: list[str], oya: int) -> list[list[str]]:
    """逐张发牌 —— 刻意不复用 :func:`mortal_replay.deal.deal` 的切片写法。"""
    hands: list[list[str]] = [[] for _ in range(4)]
    cursor = 0
    order = seat_order(oya)
    for _ in range(3):
        for seat in order:
            for _ in range(4):
                hands[seat].append(wall[cursor])
                cursor += 1
    for seat in order:
        hands[seat].append(wall[cursor])
        cursor += 1
    hands[oya].append(wall[cursor])  # 庄家第一枚自摸,雀魂记在 tiles<oya> 里
    return hands


def make_sequence(k: int, *, honba_at: set[int] | None = None) -> list[tuple[int, int, int]]:
    """造一条 ``(chang, ju, ben)`` 序列。``honba_at`` 里的位置重复上一局并 +1 本场。"""
    honba_at = honba_at or set()
    seq: list[tuple[int, int, int]] = []
    chang, ju = 0, 0
    for i in range(k):
        if i in honba_at and seq:
            pchang, pju, pben = seq[-1]
            seq.append((pchang, pju, pben + 1))
            continue
        seq.append((chang, ju, 0))
        ju += 1
        if ju == 4:
            ju, chang = 0, chang + 1
    return seq


def synth_record(
    *,
    seed: int = 0,
    k: int = 10,
    honba_at: set[int] | None = None,
) -> dict:
    """生成一份归一化 JSON 牌谱,可直接喂 :func:`mortal_replay.majsoul.parse.parse_record`。"""
    rng = random.Random(seed)
    sequence = make_sequence(k, honba_at=honba_at if honba_at is not None else {1, 7})

    scores = [25000] * 4
    liqibang = 0
    hands = []
    for chang, ju, ben in sequence:
        wall = full_wall_codes()
        rng.shuffle(wall)
        oya = ju
        tiles = _deal_by_cursor(wall, oya)
        hands.append(
            {
                "chang": chang,
                "ju": ju,
                "ben": ben,
                "liqibang": liqibang,
                "scores": list(scores),
                "paishan": "".join(wall),
                "doras": [wall[len(wall) - DEAD_WALL_SIZE + _DORA_OFFSET]],
                "left_tile_count": 70,
                **{f"tiles{seat}": tiles[seat] for seat in range(4)},
            }
        )
        # 点数只是给对照表当参照物,随便走一走,保证总和守恒
        delta = rng.choice([1000, 2000, 3900, 8000])
        winner, loser = rng.sample(range(4), 2)
        scores[winner] += delta
        scores[loser] -= delta

    return {
        "source": f"synthetic:seed={seed}",
        "player_names": ("P0", "P1", "P2", "P3"),
        "meta": {"synthetic": True, "note": "合成数据,不能验证牌山约定"},
        "hands": hands,
        "final_scores": list(scores),
    }

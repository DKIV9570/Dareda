"""雀魂 ``paishan`` 字符串 ↔ 内部 tile id 数组。

雀魂 ``RecordNewRound.paishan`` 是明文牌山(spec §3.2),形如::

    "1m5p0s7z2m..."   # 每 2 字符一张,136 张 = 272 字符

难点在 spec §3.3 说的赤宝:雀魂用 ``0m/0p/0s`` 表示赤 5,而内部表示里赤 5 必须
落在 copy 0(id 16/52/88)。所以解码时不能简单地"按出现顺序发 copy 号",要给
5 这个 kind 单独留出 copy 0。这里用一个 per-kind 的可用 copy 池来做,保证:

* 赤 5 → copy 0
* 普通 5 → copy 1..3
* 无赤规则下多出来的第 4 张普通 5 → 回落到 copy 0(不会静默丢牌)

编码是解码的严格逆运算,``format_paishan(parse_paishan(s)) == s``。
"""

from __future__ import annotations

from ..tiles import NUM_KINDS, NUM_TILES, RED_KINDS, TileError, kind_from_code, tile_to_code


def parse_paishan(s: str, *, expect: int = NUM_TILES) -> list[int]:
    """解析雀魂牌山字符串为 tile id 数组(牌山顺序保持不变)。"""
    if len(s) % 2 != 0:
        raise TileError(f"牌山字符串长度不是偶数: {len(s)}")
    codes = [s[i : i + 2] for i in range(0, len(s), 2)]
    if expect is not None and len(codes) != expect:
        raise TileError(f"牌山张数应为 {expect},实际 {len(codes)}(三麻/特殊规则暂不支持)")

    pools: list[list[int]] = [[0, 1, 2, 3] for _ in range(NUM_KINDS)]
    out: list[int] = []
    for pos, code in enumerate(codes):
        num_ch, suit = code[0], code[1]
        if not num_ch.isdigit():
            raise TileError(f"牌山第 {pos} 张编码非法: {code!r}")
        num = int(num_ch)
        kind = kind_from_code(num, suit)
        pool = pools[kind]
        if not pool:
            raise TileError(f"牌山第 {pos} 张 {code!r} 超过 4 枚")

        if num == 0:  # 赤 5 必须吃 copy 0
            if 0 not in pool:
                raise TileError(f"牌山第 {pos} 张 {code!r}: copy 0 已被占用,赤 5 重复?")
            copy = 0
        elif kind in RED_KINDS:  # 普通 5 优先让开 copy 0
            copy = next((c for c in pool if c != 0), pool[0])
        else:
            copy = pool[0]
        pool.remove(copy)
        out.append(kind * 4 + copy)

    if len(set(out)) != len(out):
        raise TileError("牌山存在重复 tile id(内部错误)")
    return out


def format_paishan(tids: list[int]) -> str:
    """tile id 数组 → 雀魂牌山字符串。"""
    return "".join(tile_to_code(t) for t in tids)


def parse_tile_list(codes: list[str]) -> list[int]:
    """解析 ``tiles0``/``doras`` 这类零散牌列表。

    注意:这里的 copy 号是**独立分配**的,与牌山里同一张牌的 copy 号不保证一致。
    所以配牌恒等断言(spec §5)必须按 *kind + 赤* 比较,不能按 tile id 比较 ——
    见 :func:`mortal_replay.verify.compare_haipai`。
    """
    return parse_paishan("".join(codes), expect=None)

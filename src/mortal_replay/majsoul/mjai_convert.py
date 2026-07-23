"""雀魂 record 动作流 → mjai 事件流。

用途:让 libriichi 能把人类对局重演一遍 —— 既用于验证(四家全照日志打应当逐事件
复现原局),也是"对手照原样打、英雄座换 Mortal"这套反事实的前提。

难点不在主干,在几处 mjai 与雀魂表示不一致的地方:

* **庄家第一枚自摸**:雀魂记在 ``tiles<oya>`` 的第 14 张,不产生 ``RecordDealTile``;
  mjai 里它是独立的 ``tsumo`` 事件,``start_kyoku.tehais`` 只放 13 张。
* **立直**:雀魂在 ``RecordDiscardTile.is_liqi`` 上标一个 bool;mjai 要拆成宣言时的
  ``reach`` + 立直牌的 ``dahai`` + 下一手确认前的 ``reach_accepted`` 三个事件。
* **暗杠的赤宝构成**:雀魂只给一个牌种(``"5p"``),而 mjai 的 ``ankan.consumed``
  要四张具体牌 —— 若手里那张 5 是赤,构成就不同。所以必须逐家跟踪手牌。
* **protobuf 省略默认值**:``seat``/``moqie``/``is_liqi`` 等于 0/false 时字段直接不存在。

牌编码:雀魂 ``0m/1z/5z`` → mjai ``5mr/E/P``。见 :data:`_Z_MAP`。

正确性不靠肉眼,靠 :mod:`mortal_replay.majsoul.mjai_validate` 把整局喂进
``PlayerState.update`` —— 任何非法事件当场报错。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..record import Hand
from ..tiles import tile_to_code

# 雀魂字牌 → mjai 字牌
_Z_MAP = {1: "E", 2: "S", 3: "W", 4: "N", 5: "P", 6: "F", 7: "C"}
_BAKAZE = ("E", "S", "W", "N")


class ConvertError(ValueError):
    pass


def ms_to_mjai_tile(code: str) -> str:
    """雀魂牌串 → mjai 牌串。``0m→5mr``, ``5z→P``, ``3s→3s``。"""
    if len(code) != 2:
        raise ConvertError(f"非法牌: {code!r}")
    num, suit = code[0], code[1]
    if suit == "z":
        return _Z_MAP[int(num)]
    if num == "0":
        return f"5{suit}r"
    return code


def id_to_mjai_tile(tid: int) -> str:
    """内部 0–135 tile id → mjai 牌串。``Hand.haipai`` 存的是这套编码。"""
    return ms_to_mjai_tile(tile_to_code(tid))


def _deaka(mjai: str) -> str:
    """``5mr → 5m``,其余原样。用于按牌种归并。"""
    return mjai[:2] if mjai.endswith("r") else mjai


@dataclass
class _HandTracker:
    """跟踪四家手牌(mjai 牌串的多重集),供暗杠赤宝构成与合法性推断。"""

    hands: list[list[str]] = field(default_factory=lambda: [[] for _ in range(4)])

    def set(self, seat: int, tiles: list[str]) -> None:
        self.hands[seat] = list(tiles)

    def add(self, seat: int, tile: str) -> None:
        self.hands[seat].append(tile)

    def remove(self, seat: int, tile: str) -> None:
        try:
            self.hands[seat].remove(tile)
        except ValueError:
            raise ConvertError(f"座{seat} 手里没有 {tile},无法移除(手牌跟踪出错)") from None

    def remove_kind(self, seat: int, kind: str, n: int) -> list[str]:
        """移除 n 张某牌种(deaka 后相等),返回实际移除的具体牌(含赤)。"""
        got = [t for t in self.hands[seat] if _deaka(t) == kind]
        if len(got) < n:
            raise ConvertError(f"座{seat} 只有 {len(got)} 张 {kind},要不了 {n} 张")
        # 优先保留赤?不,暗杠是把手里该种全部消耗,直接取前 n 张(通常正好 n 张)
        for t in got[:n]:
            self.hands[seat].remove(t)
        return got[:n]


def _call_target(seat: int, froms: list[int]) -> tuple[int, int]:
    """从 froms 里找出被鸣的那张的来源座次;返回 (被鸣牌在 tiles 里的下标, 来源座)。"""
    for i, f in enumerate(froms):
        if f != seat:
            return i, f
    raise ConvertError(f"鸣牌 froms={froms} 里找不到外来牌(座{seat})")


def convert_hand(hand: Hand, actions: list[tuple[str, dict]]) -> list[dict]:
    """把一个小局(RecordNewRound + 后续动作)转成 mjai 事件列表。

    :param actions: :func:`mortal_replay.verify.split_actions_by_round` 产出的
        ``(动作名, 数据体)`` 列表。
    """
    tracker = _HandTracker()
    tehais: list[list[str]] = []
    for seat in range(4):
        tiles = [id_to_mjai_tile(t) for t in hand.haipai[seat]]
        tracker.set(seat, tiles)
        # 庄家 14 张,起手 tehais 只放前 13,第 14 张作为首个 tsumo
        tehais.append(tiles[:13])

    events: list[dict] = [
        {
            "type": "start_kyoku",
            "bakaze": _BAKAZE[hand.chang],
            "dora_marker": ms_to_mjai_tile(_dora_marker(hand)),
            "kyoku": hand.ju + 1,
            "honba": hand.ben,
            "kyotaku": hand.liqibang,
            "oya": hand.oya,
            "scores": list(hand.scores),
            "tehais": tehais,
        }
    ]

    # 庄家第一枚自摸
    oya_first = tracker.hands[hand.oya][13]
    events.append({"type": "tsumo", "actor": hand.oya, "pai": oya_first})

    dora_seen = 1  # start_kyoku 已给 1 张指示牌
    riichi_pending: int | None = None

    def flush_riichi():
        nonlocal riichi_pending
        if riichi_pending is not None:
            events.append({"type": "reach_accepted", "actor": riichi_pending})
            riichi_pending = None

    for name, e in actions:
        if name == "RecordDealTile":
            flush_riichi()
            seat = int(e.get("seat", 0))
            pai = ms_to_mjai_tile(e["tile"])
            tracker.add(seat, pai)
            events.append({"type": "tsumo", "actor": seat, "pai": pai})
            dora_seen = _emit_new_dora(events, e, dora_seen)

        elif name == "RecordDiscardTile":
            seat = int(e.get("seat", 0))
            pai = ms_to_mjai_tile(e["tile"])
            if e.get("is_liqi") or e.get("is_wliqi"):
                events.append({"type": "reach", "actor": seat})
                riichi_pending = seat
            tracker.remove(seat, pai)
            events.append(
                {
                    "type": "dahai",
                    "actor": seat,
                    "pai": pai,
                    "tsumogiri": bool(e.get("moqie", False)),
                }
            )
            dora_seen = _emit_new_dora(events, e, dora_seen)

        elif name == "RecordChiPengGang":
            flush_riichi()
            seat = int(e.get("seat", 0))
            tiles = [ms_to_mjai_tile(t) for t in e["tiles"]]
            froms = list(e.get("froms", []))
            idx, target = _call_target(seat, froms)
            pai = tiles[idx]
            consumed = [t for i, t in enumerate(tiles) if i != idx]
            for t in consumed:
                tracker.remove(seat, t)
            typ = int(e.get("type", 0))
            kind = {0: "chi", 1: "pon", 2: "daiminkan"}[typ]
            events.append(
                {"type": kind, "actor": seat, "target": target, "pai": pai, "consumed": consumed}
            )

        elif name == "RecordAnGangAddGang":
            flush_riichi()
            seat = int(e.get("seat", 0))
            typ = int(e.get("type", 0))
            tile = ms_to_mjai_tile(e["tiles"])
            if typ == 3:  # 暗杠
                consumed = tracker.remove_kind(seat, _deaka(tile), 4)
                events.append({"type": "ankan", "actor": seat, "consumed": consumed})
                dora_seen = _emit_new_dora(events, e, dora_seen)
            elif typ == 2:  # 加杠
                tracker.remove(seat, tile)
                consumed = _kakan_consumed(tile)
                events.append(
                    {"type": "kakan", "actor": seat, "pai": tile, "consumed": consumed}
                )
                dora_seen = _emit_new_dora(events, e, dora_seen)
            else:
                raise ConvertError(f"未知 AnGangAddGang type={typ}")

        elif name == "RecordHule":
            for hule in e["hules"]:
                actor = int(hule.get("seat", 0))
                zimo = bool(hule.get("zimo", False))
                target = actor if zimo else _last_discarder(events)
                ura = [ms_to_mjai_tile(t) for t in hule.get("li_doras", [])]
                ev = {
                    "type": "hora",
                    "actor": actor,
                    "target": target,
                    "deltas": list(e.get("delta_scores", [0, 0, 0, 0])),
                }
                if ura:
                    ev["ura_markers"] = ura
                events.append(ev)
            events.append({"type": "end_kyoku"})
            return events

        elif name == "RecordNoTile":
            deltas = e.get("delta_scores") or [0, 0, 0, 0]
            events.append({"type": "ryukyoku", "deltas": list(deltas)})
            events.append({"type": "end_kyoku"})
            return events

        elif name == "RecordLiuJu":
            events.append({"type": "ryukyoku", "deltas": [0, 0, 0, 0]})
            events.append({"type": "end_kyoku"})
            return events

        # 其它(RecordBaBei 拔北仅三麻等)在四麻里不出现,忽略

    # 走到这里说明没有终局事件(数据被截断)
    events.append({"type": "end_kyoku"})
    return events


def _dora_marker(hand: Hand) -> str:
    if hand.doras:
        return tile_to_code(hand.doras[0])
    raise ConvertError(f"{hand.label} 缺开局宝牌指示牌")


def _emit_new_dora(events: list[dict], e: dict, dora_seen: int) -> int:
    """majsoul 事件里 doras 列表增长时,补发 mjai 的 dora 事件。"""
    doras = e.get("doras")
    if doras and len(doras) > dora_seen:
        for code in doras[dora_seen:]:
            events.append({"type": "dora", "dora_marker": ms_to_mjai_tile(code)})
        return len(doras)
    return dora_seen


def _kakan_consumed(tile: str) -> list[str]:
    """加杠:被加的碰面子那三张。含赤则一张赤两张普通。"""
    base = _deaka(tile)
    if base[0] == "5" and base[1] in "mps":
        return [f"5{base[1]}r", base, base]
    return [base, base, base]


def _last_discarder(events: list[dict]) -> int:
    for ev in reversed(events):
        if ev["type"] == "dahai":
            return ev["actor"]
    raise ConvertError("荣和前找不到任何打牌事件")


def convert_game(record, actions_by_round: list[list[tuple[str, dict]]]) -> list[list[dict]]:
    """整场牌谱 → 每小局一个 mjai 事件列表。"""
    if len(record.hands) != len(actions_by_round):
        raise ConvertError(
            f"小局数不匹配: hands={len(record.hands)} actions={len(actions_by_round)}"
        )
    return [convert_hand(h, acts) for h, acts in zip(record.hands, actions_by_round)]

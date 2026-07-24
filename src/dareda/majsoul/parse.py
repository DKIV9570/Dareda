"""雀魂牌谱 → :class:`GameRecord`。

吃四种输入,都归一到同一个模型:

1. 本项目自己的归一化 JSON:``{"source":..., "hands":[{...}]}``
2. **downloadlogs 的 verbose 导出**:``{"mjshead":..., "mjslog":[...], "mjsrecordtypes":[...]}``
   —— 这是现实里最容易拿到的真牌谱,详见下面
3. 雀魂 record 动作流:``{"records": [...]}`` / ``{"actions": [...]}`` / 裸 list
4. 单个 ``RecordNewRound`` dict

动作 dict 允许两种形态:字段直接摊在顶层,或包在 ``{"name": ..., "data": {...}}`` 里。

关于 downloadlogs
-----------------
mjai-reviewer 推荐的那个 Tampermonkey 脚本默认输出**天凤格式**,那个格式里只有
被摸出来的牌,没有完整牌山 —— 对本项目不够用(replay 可能比人类那局多摸牌)。
但脚本里有个 ``VERBOSELOG`` 开关,打开后会把 ``fetchGameRecord`` 拿到的原始
record 一并塞进 ``mjslog``,``RecordNewRound`` 的 ``paishan`` 就在里面。

protobuf 序列化会**省略默认值**,所以 ``chang``/``ju``/``ben``/``liqibang``/``seat``
等于 0 时字段直接不存在。这里所有读取都带默认值,不要改成必填。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..record import GameRecord, Hand
from .codec import parse_paishan, parse_tile_list

NEW_ROUND = "RecordNewRound"


class ParseError(ValueError):
    pass


def _unwrap(action: dict) -> tuple[str, dict]:
    """返回 ``(动作名, 数据体)``。"""
    name = action.get("name") or action.get("type") or ""
    data = action.get("data")
    if isinstance(data, dict):
        return str(name).split(".")[-1], data
    if not name and "paishan" in action:
        name = NEW_ROUND
    return str(name).split(".")[-1], action


def parse_new_round(data: dict) -> Hand:
    """解析一个 ``RecordNewRound`` 数据体。"""
    try:
        paishan = parse_paishan(data["paishan"])
    except KeyError as exc:
        raise ParseError("RecordNewRound 缺少 paishan 字段") from exc

    haipai = []
    for seat in range(4):
        key = f"tiles{seat}"
        if key not in data:
            raise ParseError(f"RecordNewRound 缺少 {key}")
        haipai.append(tuple(parse_tile_list(list(data[key]))))

    scores = tuple(int(s) for s in data.get("scores", (25000,) * 4))
    if len(scores) != 4:
        raise ParseError(f"scores 长度应为 4,实际 {len(scores)}")

    return Hand(
        chang=int(data.get("chang", 0)),
        ju=int(data.get("ju", 0)),
        ben=int(data.get("ben", 0)),
        liqibang=int(data.get("liqibang", 0)),
        scores=scores,  # type: ignore[arg-type]
        paishan=tuple(paishan),
        haipai=tuple(haipai),
        doras=tuple(parse_tile_list(list(data.get("doras", [])))),
    )


def parse_downloadlogs(obj: dict) -> GameRecord:
    """解析 downloadlogs(``VERBOSELOG = true``)的导出。"""
    mjslog = obj.get("mjslog")
    if not isinstance(mjslog, list):
        raise ParseError("mjslog 不是数组")
    types = obj.get("mjsrecordtypes")
    if isinstance(types, list) and len(types) == len(mjslog):
        pairs = zip(types, mjslog)
    else:  # 没有类型数组就按有没有 paishan 认
        pairs = (("RecordNewRound" if "paishan" in e else "?", e) for e in mjslog)

    hands = [parse_new_round(data) for name, data in pairs if name == NEW_ROUND]
    if not hands:
        raise ParseError(
            "mjslog 里没有 RecordNewRound。"
            "多半是 downloadlogs 的 VERBOSELOG 没打开(默认 false,只导出天凤格式,不含牌山)。"
        )

    head = obj.get("mjshead") or {}
    accounts = sorted(head.get("accounts", []), key=lambda a: a.get("seat", 0))
    names = tuple(a.get("nickname", f"座{a.get('seat', 0)}") for a in accounts)

    final_scores = None
    players = (head.get("result") or {}).get("players") or []
    if len(players) == 4:
        by_seat = [0] * 4
        for p in players:
            by_seat[p.get("seat", 0)] = int(p.get("part_point_1", 0))
        final_scores = tuple(by_seat)

    return GameRecord(
        hands=hands,
        source=f"majsoul:{head.get('uuid', 'unknown')}",
        final_scores=final_scores,
        player_names=names,
        meta={"head": head},
    )


def parse_record(obj: Any) -> GameRecord:
    """从任意支持的形态构造 :class:`GameRecord`。"""
    if isinstance(obj, dict) and "mjslog" in obj:
        return parse_downloadlogs(obj)

    if isinstance(obj, dict) and "hands" in obj:
        hands = [parse_new_round(h) for h in obj["hands"]]
        return GameRecord(
            hands=hands,
            source=obj.get("source", "majsoul"),
            final_scores=tuple(obj["final_scores"]) if obj.get("final_scores") else None,
            player_names=tuple(obj.get("player_names", ())),
            meta=obj.get("meta", {}),
        )

    if isinstance(obj, dict):
        actions = obj.get("records") or obj.get("actions") or obj.get("data")
        source = obj.get("uuid") or obj.get("source") or "majsoul"
        if actions is None:
            if "paishan" in obj:
                return GameRecord(hands=[parse_new_round(obj)], source=str(source))
            raise ParseError("认不出的牌谱结构:既没有 hands,也没有 records/actions")
    elif isinstance(obj, list):
        actions, source = obj, "majsoul"
    else:
        raise ParseError(f"认不出的牌谱类型: {type(obj).__name__}")

    hands = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        name, data = _unwrap(action)
        if name == NEW_ROUND:
            hands.append(parse_new_round(data))
    if not hands:
        raise ParseError("动作流里没有找到任何 RecordNewRound")
    return GameRecord(hands=hands, source=f"majsoul:{source}")


def seat_of_account(record: GameRecord, account_id: int) -> int | None:
    """真实 account_id → 座次。认不出返回 None。

    §6 需要知道"吃四的是哪个座",不然对照表看不出重点。

    注意:**不要**把牌谱链接 ``_a`` 后面那个数传进来 —— 那是混淆过的分享码,
    和 account_id 对不上,见 :class:`dareda.majsoul.fetch.PaipuRef`。
    真实 account_id 可以从 ``head.accounts`` 里按昵称找。
    """
    head = record.meta.get("head") or {}
    for acc in head.get("accounts", []):
        if int(acc.get("account_id", -1)) == account_id:
            return int(acc.get("seat", 0))
    return None


def load_record(path: str | Path) -> GameRecord:
    return parse_record(json.loads(Path(path).read_text(encoding="utf-8")))

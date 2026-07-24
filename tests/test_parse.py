import pytest

from dareda.majsoul.fetch import parse_paipu_link
from dareda.majsoul.parse import ParseError, parse_record
from dareda.majsoul.synth import synth_record


def test_parses_normalized_form():
    rec = parse_record(synth_record(seed=2, k=8))
    assert rec.K == 8
    assert rec.hands[0].label == "东一"
    assert all(len(h.paishan) == 136 for h in rec.hands)


def test_oya_equals_ju_and_honba_does_not_move_it():
    """§1.2:本场数不影响庄位,标签本身即答案。"""
    rec = parse_record(synth_record(seed=4, k=10))
    for hand in rec.hands:
        assert hand.oya == hand.ju
    honba = [h for h in rec.hands if h.ben > 0]
    assert honba, "合成序列里应当有本场局"
    for h in honba:
        prev = rec.hands[rec.hands.index(h) - 1]
        assert h.oya == prev.oya  # 一本场的庄 = 上一局的庄


def test_parses_action_stream_with_wrapper():
    raw = synth_record(seed=6, k=2)
    actions = [
        {"name": ".lq.RecordNewRound", "data": raw["hands"][0]},
        {"name": ".lq.RecordDealTile", "data": {"seat": 0, "tile": "1m"}},
        {"name": ".lq.RecordNewRound", "data": raw["hands"][1]},
    ]
    rec = parse_record({"uuid": "abc", "records": actions})
    assert rec.K == 2
    assert rec.source == "majsoul:abc"


def test_parses_bare_action_list():
    raw = synth_record(seed=6, k=2)
    rec = parse_record([{"name": "RecordNewRound", **raw["hands"][0]}])
    assert rec.K == 1


def test_rejects_stream_without_new_round():
    with pytest.raises(ParseError, match="没有找到任何 RecordNewRound"):
        parse_record({"records": [{"name": "RecordDealTile", "data": {}}]})


def test_rejects_missing_paishan():
    with pytest.raises(ParseError, match="缺少 paishan"):
        parse_record({"hands": [{"chang": 0, "ju": 0}]})


def _as_downloadlogs(raw: dict, *, drop_defaults: bool = True) -> dict:
    """把合成牌谱伪装成 downloadlogs(VERBOSELOG=true)的导出。

    ``drop_defaults`` 模拟 protobuf 序列化省略默认值 —— 真导出里 ``ju: 0`` /
    ``ben: 0`` 这些字段是**不存在**的,解析器必须容忍。
    """
    mjslog, types = [], []
    for hand in raw["hands"]:
        entry = dict(hand)
        if drop_defaults:
            entry = {k: v for k, v in entry.items() if v not in (0, [], "")}
        mjslog.append(entry)
        types.append("RecordNewRound")
        mjslog.append({"seat": 1, "tile": "1m", "moqie": True})
        types.append("RecordDiscardTile")
    return {
        "mjshead": {
            "uuid": "250101-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
            "accounts": [
                {"nickname": "P1", "seat": 1},
                {"nickname": "P2", "seat": 2},
                {"nickname": "P0"},  # seat 0 被 protobuf 省略
                {"nickname": "P3", "seat": 3},
            ],
            "result": {
                "players": [
                    {"part_point_1": 8500},  # seat 0 被省略
                    {"seat": 1, "part_point_1": 41200},
                    {"seat": 2, "part_point_1": 25100},
                    {"seat": 3, "part_point_1": 25200},
                ]
            },
        },
        "mjslog": mjslog,
        "mjsrecordtypes": types,
    }


def test_parses_downloadlogs_verbose_export():
    rec = parse_record(_as_downloadlogs(synth_record(seed=9, k=10)))
    assert rec.K == 10
    assert rec.source == "majsoul:250101-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
    assert rec.player_names == ("P0", "P1", "P2", "P3")
    assert rec.final_scores == (8500, 41200, 25100, 25200)


def test_downloadlogs_survives_omitted_protobuf_defaults():
    """东一(chang=0, ju=0, ben=0)的字段会被整个省掉,不能当成解析失败。"""
    raw = synth_record(seed=9, k=4)
    dl = _as_downloadlogs(raw, drop_defaults=True)
    first = dl["mjslog"][0]
    assert "ju" not in first and "ben" not in first and "chang" not in first
    rec = parse_record(dl)
    assert rec.hands[0].label == "东一"
    assert rec.hands[0].oya == 0


def test_downloadlogs_still_passes_haipai_assertion():
    from dareda.verify import verify_record

    rec = parse_record(_as_downloadlogs(synth_record(seed=9, k=10)))
    assert verify_record(rec).ok


def test_downloadlogs_without_verboselog_gives_actionable_error():
    with pytest.raises(ParseError, match="VERBOSELOG"):
        parse_record({"mjshead": {}, "mjslog": [{"seat": 0, "tile": "1m"}]})


def test_seat_of_account():
    from dareda.majsoul.parse import seat_of_account

    dl = _as_downloadlogs(synth_record(seed=9, k=2))
    for acc, aid in zip(dl["mjshead"]["accounts"], [11, 22, 12345678, 44]):
        acc["account_id"] = aid
    rec = parse_record(dl)
    assert seat_of_account(rec, 12345678) == 0  # 该条 accounts 项省略了 seat
    assert seat_of_account(rec, 22) == 2
    assert seat_of_account(rec, 999) is None


def test_downloadlogs_falls_back_to_duck_typing():
    raw = synth_record(seed=9, k=2)
    dl = _as_downloadlogs(raw)
    del dl["mjsrecordtypes"]
    assert parse_record(dl).K == 2


@pytest.mark.parametrize(
    "link,uuid,share",
    [
        ("https://game.maj-soul.com/1/?paipu=250101-abcd1234-ef56-7890_a12345", "250101-abcd1234-ef56-7890", 12345),
        ("https://mahjongsoul.game.yo-star.com/?paipu=250101-abcd1234-ef56-7890", "250101-abcd1234-ef56-7890", None),
        ("250101-abcd1234-ef56-7890_a999", "250101-abcd1234-ef56-7890", 999),
    ],
)
def test_parse_paipu_link(link, uuid, share):
    ref = parse_paipu_link(link)
    assert ref.uuid == uuid
    assert ref.share_code == share


def test_parse_paipu_link_rejects_junk():
    with pytest.raises(ValueError):
        parse_paipu_link("https://game.maj-soul.com/1/?foo=bar")

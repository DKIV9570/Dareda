"""WebSocket 抓包解码的回归测试。

不依赖真抓包文件(那玩意 95 MB),而是用 liqi 的 protobuf 类现造一份等价的帧,
把大厅协议的帧头、Wrapper 嵌套、GameDetailRecords 两种承载形态都覆盖一遍。

真数据上的验证记录在 README:250101-1a2b3c4d… 这局,15/15 局配牌恒等通过。
"""

import base64
import json

import pytest

from dareda.majsoul.liqi import message_class
from dareda.majsoul.parse import parse_record
from dareda.majsoul.synth import synth_record
from dareda.majsoul.wscapture import CaptureError, decode_capture
from dareda.verify import verify_record

UUID = "250101-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


def _wrap(name: str, payload: bytes) -> bytes:
    W = message_class("lq.Wrapper")
    return W(name=name, data=payload).SerializeToString()


def _new_round_bytes(hand: dict) -> bytes:
    NR = message_class("lq.RecordNewRound")
    m = NR(
        chang=hand["chang"],
        ju=hand["ju"],
        ben=hand["ben"],
        liqibang=hand["liqibang"],
        scores=hand["scores"],
        paishan=hand["paishan"],
        tiles0=hand["tiles0"],
        tiles1=hand["tiles1"],
        tiles2=hand["tiles2"],
        tiles3=hand["tiles3"],
        doras=hand["doras"],
    )
    return m.SerializeToString()


def _detail_bytes(hands, *, use_records: bool = False) -> bytes:
    GDR = message_class("lq.GameDetailRecords")
    GA = message_class("lq.GameAction")
    wrapped = [_wrap(".lq.RecordNewRound", _new_round_bytes(h)) for h in hands]
    if use_records:
        return GDR(records=wrapped).SerializeToString()
    return GDR(actions=[GA(type=1, result=w) for w in wrapped]).SerializeToString()


def _head_bytes():
    RG = message_class("lq.RecordGame")
    AI = message_class("lq.RecordGame.AccountInfo")
    GER = message_class("lq.GameEndResult")
    PI = message_class("lq.GameEndResult.PlayerItem")
    return RG(
        uuid=UUID,
        accounts=[
            AI(seat=0, account_id=1001, nickname="P0"),
            AI(seat=1, account_id=1002, nickname="P1"),
            AI(seat=2, account_id=1003, nickname="P2"),
            AI(seat=3, account_id=1004, nickname="P3"),
        ],
        result=GER(
            players=[
                PI(seat=0, part_point_1=28300),
                PI(seat=1, part_point_1=9800),
                PI(seat=2, part_point_1=35700),
                PI(seat=3, part_point_1=26200),
            ]
        ),
    ).SerializeToString()


def _frame(blob: bytes, seq: int, dir_: str = "in", url: str | None = None) -> dict:
    fr = {"seq": seq, "dir": dir_, "t": seq, "size": len(blob), "b64": base64.b64encode(blob).decode()}
    if url:
        fr["url"] = url
    return fr


def _capture(frames: list[dict]) -> dict:
    return {"captured_at": "x", "page": "https://game.maj-soul.com/1/", "frames": frames}


def _res_frame(hands, *, use_records=False, data_url=None):
    """造一帧 fetchGameRecord 响应:[0x03][序号 u16 LE][Wrapper{data=ResGameRecord}]"""
    Res = message_class("lq.ResGameRecord")
    H = message_class("lq.RecordGame")
    head = H()
    head.ParseFromString(_head_bytes())
    kw = {"head": head}
    if data_url:
        kw["data_url"] = data_url
    else:
        kw["data"] = _wrap(".lq.GameDetailRecords", _detail_bytes(hands, use_records=use_records))
    body = _wrap("", Res(**kw).SerializeToString())
    return b"\x03" + (7).to_bytes(2, "little") + body


@pytest.fixture
def hands():
    return synth_record(seed=21, k=10)["hands"]


def test_decodes_inline_actions(hands):
    cap = _capture([
        _frame(b"\x00" * 64, 0, "http", "https://cdn/x.unity3d"),   # 噪声:资源下载
        _frame(b"\x01\x0a\x05hello", 1),                            # 噪声:解不动的帧
        _frame(_res_frame(hands), 2),
    ])
    out, rep = decode_capture(cap)
    assert rep.uuid == UUID
    assert rep.source == "inline"
    assert rep.new_rounds == 10
    assert rep.record_frame_seq == 2
    assert out["mjsrecordtypes"].count("RecordNewRound") == 10


def test_decoded_record_passes_haipai_assertion(hands):
    """解码链路端到端:抓包 → 牌谱 → §5 断言。"""
    out, _ = decode_capture(_capture([_frame(_res_frame(hands), 0)]))
    rec = parse_record(out)
    assert rec.K == 10
    assert verify_record(rec).ok


def test_decodes_legacy_records_field(hands):
    """老版客户端把动作放 records 而不是 actions。"""
    out, rep = decode_capture(_capture([_frame(_res_frame(hands, use_records=True), 0)]))
    assert rep.new_rounds == 10


def test_decodes_via_data_url(hands):
    """长牌谱:动作流不内嵌,走 data_url 另外下载。"""
    url = "https://cdn.example/record/blob?sig=abc"
    detail = _wrap(".lq.GameDetailRecords", _detail_bytes(hands))
    cap = _capture([
        _frame(_res_frame(hands, data_url=url), 0),
        _frame(detail, 1, "http", url),
    ])
    out, rep = decode_capture(cap)
    assert rep.source == "data_url"
    assert rep.new_rounds == 10


def test_data_url_missing_gives_actionable_error(hands):
    url = "https://cdn.example/record/blob"
    cap = _capture([_frame(_res_frame(hands, data_url=url), 0)])
    with pytest.raises(CaptureError, match="data_url"):
        decode_capture(cap)


def test_no_record_in_capture_gives_actionable_error():
    cap = _capture([_frame(b"\x00" * 128, 0), _frame(b"\x01\x02\x03", 1)])
    with pytest.raises(CaptureError, match="刷新页面"):
        decode_capture(cap)


def test_rejects_non_capture_json():
    with pytest.raises(CaptureError, match="frames"):
        decode_capture({"hello": "world"})


def test_uuid_filter_skips_other_games(hands):
    cap = _capture([_frame(_res_frame(hands), 0)])
    with pytest.raises(CaptureError):
        decode_capture(cap, uuid="999999-nope")
    out, rep = decode_capture(cap, uuid="250101-")
    assert rep.uuid == UUID


def test_head_survives_round_trip(hands):
    out, _ = decode_capture(_capture([_frame(_res_frame(hands), 0)]))
    rec = parse_record(out)
    assert rec.player_names == ("P0", "P1", "P2", "P3")
    assert rec.final_scores == (28300, 9800, 35700, 26200)
    assert json.dumps(out)  # 必须可 JSON 序列化,CLI 要落盘

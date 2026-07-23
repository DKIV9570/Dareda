"""从 WebSocket 抓包里挖出牌谱。

配套 ``tools/majsoul-ws-capture.user.js``。国服客户端是 Unity WebGL(canvas id=
``unity-canvas``),游戏逻辑在 WASM 里,``GameMgr`` / ``app.NetAgent`` 这些 JS 全局
不存在,所有"调页面全局导出牌谱"的脚本在那上面都失效。但 Unity WebGL 开不了原始
socket,网络必须借道浏览器 API —— 于是改成在 JS 层录下 WebSocket 原始帧,拿到这里
离线解。

大厅协议的帧结构::

    请求   [0x02][序号 u16 LE][Wrapper{name, data}]
    响应   [0x03][序号 u16 LE][Wrapper{name="", data}]
    通知   [0x01][Wrapper{name, data}]

响应帧里 ``Wrapper.name`` 是空的(靠序号和请求配对),所以不能按名字找,只能按
"能不能解成 ResGameRecord 且带 head/data"来认。这里对每帧试 0/1/3 三种头长,
逐一尝试,失败就跳过 —— 抓包里绝大多数帧是游戏资源和别的协议,解不动是常态。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

from .liqi import FRAME_HEADER_SIZES, message_class, parse, to_dict

NEW_ROUND_MARKER = b".lq.RecordNewRound"


class CaptureError(RuntimeError):
    pass


@dataclass
class DecodeReport:
    """解码过程的可观测记录 —— 失败时得知道是哪一步断的。"""

    frames_total: int = 0
    frames_tried: int = 0
    record_frame_seq: int | None = None
    uuid: str | None = None
    source: str = ""
    """牌谱动作流的来源:``inline``(帧里直接带)或 ``data_url``(另一帧的 HTTP 下载)。"""
    actions_total: int = 0
    new_rounds: int = 0
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"抓包帧数     : {self.frames_total}(尝试解析 {self.frames_tried} 帧)",
            f"牌谱所在帧   : {self.record_frame_seq if self.record_frame_seq is not None else '未找到'}",
            f"uuid         : {self.uuid or '—'}",
            f"动作流来源   : {self.source or '—'}",
            f"动作条数     : {self.actions_total}",
            f"RecordNewRound: {self.new_rounds} 个小局",
        ]
        lines += [f"  · {n}" for n in self.notes]
        return "\n".join(lines)


def _iter_wrappers(blob: bytes):
    """对一段字节尝试各种帧头长度,产出能解出来的 Wrapper。"""
    Wrapper = message_class("lq.Wrapper")
    for skip in FRAME_HEADER_SIZES:
        if len(blob) <= skip:
            continue
        w = Wrapper()
        try:
            # 用严格解析:protobuf 对垃圾数据往往也能"解出来",所以必须靠字段内容判真伪
            if w.ParseFromString(blob[skip:]) != len(blob) - skip:
                continue
        except Exception:
            continue
        if not w.data:
            continue
        if w.name and not w.name.lstrip(".").startswith("lq."):
            continue
        yield skip, w


def _try_res_game_record(blob: bytes):
    """认出 fetchGameRecord 的响应。返回 ``(ResGameRecord, 头长)`` 或 None。"""
    ResGameRecord = message_class("lq.ResGameRecord")
    for skip, w in _iter_wrappers(blob):
        res = ResGameRecord()
        try:
            if res.ParseFromString(w.data) != len(w.data):
                continue
        except Exception:
            continue
        # 判真:必须有 head.uuid,且动作流要么内嵌要么给了 data_url
        if res.head and res.head.uuid and (res.data or res.data_url):
            return res, skip
    return None


def _decode_detail(blob: bytes):
    """把 ``ResGameRecord.data`` 或 data_url 下载到的字节解成 GameDetailRecords。"""
    GameDetailRecords = message_class("lq.GameDetailRecords")
    # 常规:外面还包一层 Wrapper
    for _, w in _iter_wrappers(blob):
        d = GameDetailRecords()
        try:
            if d.ParseFromString(w.data) != len(w.data):
                continue
        except Exception:
            continue
        if d.actions or d.records:
            return d
    # 兜底:没有 Wrapper,直接就是 GameDetailRecords
    d = GameDetailRecords()
    try:
        d.ParseFromString(blob)
        if d.actions or d.records:
            return d
    except Exception:
        pass
    return None


def _actions_to_mjslog(detail) -> tuple[list[dict], list[str], int]:
    """GameDetailRecords → (mjslog, 类型名列表, 动作总数)。"""
    Wrapper = message_class("lq.Wrapper")
    payloads: list[bytes] = []
    if detail.actions:
        for a in detail.actions:
            if a.result:
                payloads.append(a.result)
    elif detail.records:
        payloads.extend(detail.records)

    mjslog: list[dict] = []
    types: list[str] = []
    for raw in payloads:
        w = Wrapper()
        try:
            w.ParseFromString(raw)
        except Exception:
            continue
        if not w.name:
            continue
        short = w.name.lstrip(".").split(".")[-1]
        try:
            msg = parse(f"lq.{short}", w.data)
        except Exception:
            continue
        mjslog.append(to_dict(msg))
        types.append(short)
    return mjslog, types, len(payloads)


def decode_capture(capture: dict, *, uuid: str | None = None) -> tuple[dict, DecodeReport]:
    """抓包 → downloadlogs 同款的 ``{mjshead, mjslog, mjsrecordtypes}``。

    :param uuid: 抓包里若含多局牌谱,用它指定要哪一局(前缀匹配即可)。
    """
    report = DecodeReport()
    frames = capture.get("frames")
    if not isinstance(frames, list):
        raise CaptureError("抓包文件里没有 frames 数组 —— 不是本项目的抓包脚本产出的?")
    report.frames_total = len(frames)

    # 先把 http 帧按 url 建索引,data_url 那条路要用
    by_url: dict[str, bytes] = {}
    found = None
    for fr in frames:
        b64 = fr.get("b64")
        if not b64:
            continue
        try:
            blob = base64.b64decode(b64)
        except Exception:
            continue
        if fr.get("dir") == "http" and fr.get("url"):
            by_url[fr["url"]] = blob
        report.frames_tried += 1
        if found is not None:
            continue
        hit = _try_res_game_record(blob)
        if hit is not None:
            res, _skip = hit
            if uuid and not res.head.uuid.startswith(uuid):
                continue
            found = (fr, res)

    if found is None:
        raise CaptureError(
            "抓包里没找到 fetchGameRecord 的响应。可能原因:\n"
            "  a) 抓包脚本是在 WebSocket 建连之后才生效的 —— 装好脚本后必须刷新页面\n"
            "  b) 抓包时没有真正点开牌谱(要等回放界面加载出来)\n"
            "  c) 客户端换了协议封装"
        )

    fr, res = found
    report.record_frame_seq = fr.get("seq")
    report.uuid = res.head.uuid

    detail = None
    if res.data:
        detail = _decode_detail(res.data)
        if detail is not None:
            report.source = "inline"
    if detail is None and res.data_url:
        blob = by_url.get(res.data_url)
        if blob is None:
            # url 可能带签名参数,退而求其次做包含匹配
            for u, b in by_url.items():
                if res.data_url.split("?")[0] in u:
                    blob = b
                    break
        if blob is None:
            raise CaptureError(
                f"牌谱动作流在 data_url 里,但抓包里没有那次下载:\n  {res.data_url}\n"
                "抓包脚本的 fetch/XHR 钩子可能没生效,或下载发生在开始抓之前。"
            )
        detail = _decode_detail(blob)
        if detail is not None:
            report.source = "data_url"

    if detail is None:
        raise CaptureError("拿到了 ResGameRecord,但动作流解不出来(GameDetailRecords 解析失败)")

    mjslog, types, total = _actions_to_mjslog(detail)
    report.actions_total = total
    report.new_rounds = types.count("RecordNewRound")
    if not report.new_rounds:
        report.notes.append("一个 RecordNewRound 都没有 —— 这份数据对 replay 没用")

    return (
        {
            "mjshead": to_dict(res.head),
            "mjslog": mjslog,
            "mjsrecordtypes": types,
        },
        report,
    )


def decode_capture_file(path: str | Path, *, uuid: str | None = None):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return decode_capture(data, uuid=uuid)

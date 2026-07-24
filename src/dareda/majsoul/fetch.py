"""牌谱链接 → 原始 record。

最终形态是"贴一个链接就能拉",但那条路要走雀魂的 liqi protobuf + websocket,
还要带账号凭据登录,属于独立一块工程。v1 先把**接口和链接解析**定下来,拉取实现
留成可插拔的 fetcher:

* :class:`LocalFileFetcher` —— 已经导出好的牌谱 JSON,现在就能用
* :class:`MajsoulApiFetcher` —— 联网拉取,未实现,接上 ``mahjong_soul_api`` 之后填

链接形态(各服域名不同,uuid 结构一致)::

    https://game.maj-soul.com/1/?paipu=<uuid>_a<accountid>
    https://mahjongsoul.game.yo-star.com/?paipu=<uuid>
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse

from ..record import GameRecord
from .parse import parse_record

_PAIPU_RE = re.compile(r"(?P<uuid>[0-9a-zA-Z]+-[0-9a-zA-Z-]+)(?:_a(?P<share>\d+))?$")


@dataclass(frozen=True)
class PaipuRef:
    uuid: str
    share_code: int | None = None
    """链接里 ``_a`` 后面那个数。

    **不是 account_id。** 实测(250101-1a2b3c4d… 这局)链接里的 12345678 与牌谱
    ``head.accounts`` 里的四个 account_id 都对不上,也不是简单的异或/偏移 ——
    雀魂对它做了混淆。想知道"我是哪个座",请直接用真实 account_id 配
    :func:`dareda.majsoul.parse.seat_of_account`,或者按昵称/点数认。
    """

    def __str__(self) -> str:
        return f"{self.uuid}_a{self.share_code}" if self.share_code else self.uuid


def parse_paipu_link(link: str) -> PaipuRef:
    """从牌谱链接(或裸 uuid)里抠出 uuid 与分享码。"""
    raw = link.strip()
    if "?" in raw or raw.startswith("http"):
        query = parse_qs(urlparse(raw).query)
        candidates = query.get("paipu") or []
        if not candidates:
            raise ValueError(f"链接里没有 paipu 参数: {link!r}")
        raw = unquote(candidates[0])
    m = _PAIPU_RE.match(raw)
    if not m:
        raise ValueError(f"认不出的牌谱标识: {raw!r}")
    share = m.group("share")
    return PaipuRef(uuid=m.group("uuid"), share_code=int(share) if share else None)


class RecordFetcher(Protocol):
    def fetch(self, ref: PaipuRef) -> GameRecord: ...


@dataclass
class LocalFileFetcher:
    """从本地目录读 ``<uuid>.json``。抓包/第三方工具导出的牌谱走这条。"""

    root: Path

    def fetch(self, ref: PaipuRef) -> GameRecord:
        path = Path(self.root) / f"{ref.uuid}.json"
        if not path.exists():
            raise FileNotFoundError(f"本地没有这份牌谱: {path}")
        return parse_record(json.loads(path.read_text(encoding="utf-8")))


class MajsoulApiFetcher:
    """联网拉取。**未实现。**

    要做的事,按依赖顺序:

    1. 取 liqi.json,生成 protobuf stub(``MahjongRepository/mahjong_soul_api``)
    2. websocket 连大厅,登录(账号密码或 access token),拿 session
    3. ``fetchGameRecord(game_uuid=...)`` → 拿到 ``GameDetailRecords``
    4. 解 wrapper,逐条还原动作,筛 ``RecordNewRound`` 交给
       :func:`dareda.majsoul.parse.parse_record`

    注意:登录态属于账号操作,频繁拉取有风控风险;实现时务必带本地缓存,
    同一 uuid 只拉一次。
    """

    def fetch(self, ref: PaipuRef) -> GameRecord:  # pragma: no cover - 未实现
        raise NotImplementedError(
            f"联网拉取尚未实现(目标 uuid={ref.uuid})。"
            "现在请用第三方工具导出牌谱 JSON,再用 LocalFileFetcher 或 CLI 的 --record 读取。"
        )

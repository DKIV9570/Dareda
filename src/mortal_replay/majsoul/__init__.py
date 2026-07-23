"""雀魂侧:牌山明文解析、牌谱拉取、合成数据。"""

from .codec import format_paishan, parse_paishan, parse_tile_list
from .fetch import LocalFileFetcher, MajsoulApiFetcher, PaipuRef, parse_paipu_link
from .parse import (
    ParseError,
    load_record,
    parse_downloadlogs,
    parse_new_round,
    parse_record,
)
from .synth import synth_record

__all__ = [
    "parse_paishan",
    "format_paishan",
    "parse_tile_list",
    "parse_record",
    "parse_new_round",
    "parse_downloadlogs",
    "load_record",
    "ParseError",
    "synth_record",
    "parse_paipu_link",
    "PaipuRef",
    "LocalFileFetcher",
    "MajsoulApiFetcher",
]

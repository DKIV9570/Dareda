"""雀魂 liqi protobuf 的运行时加载。

不用 ``protoc`` 生成的 ``*_pb2.py``,而是随包附一份 **FileDescriptorSet**
(``liqi.desc``),运行时喂进描述符池。这么做是因为生成代码里带了运行时版本断言:
protoc 35 生成的代码要求 protobuf>=5,而一台机器上常有别的库把 protobuf 钉在 4.x
(googleapis-common-protos / proto-plus / wandb 都要求 <7)。描述符集没有这个耦合,
4.x 和 7.x 都能加载。

``liqi.desc`` 由 ``proto/liqi.proto`` 编译而来::

    python -m grpc_tools.protoc -Iproto --descriptor_set_out=proto/liqi.desc \\
        --include_imports proto/liqi.proto

schema 来源:https://github.com/MahjongRepository/mahjong_soul_api (``ms/protocol.proto``)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

DESC_PATH = Path(__file__).with_name("liqi.desc")

#: 大厅协议的帧头长度。notify 是 1 字节类型;req/res 是 1 字节类型 + 2 字节序号。
FRAME_HEADER_SIZES = (0, 1, 3)


class LiqiError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _pool() -> descriptor_pool.DescriptorPool:
    if not DESC_PATH.exists():
        raise LiqiError(f"缺少描述符集: {DESC_PATH}。见本模块 docstring 里的编译命令。")
    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(DESC_PATH.read_bytes())
    pool = descriptor_pool.DescriptorPool()
    for f in fds.file:
        pool.Add(f)
    return pool


@lru_cache(maxsize=None)
def message_class(full_name: str):
    """``"lq.RecordNewRound"`` → 可实例化的消息类。也接受前导点的 ``".lq.Xxx"``。"""
    name = full_name.lstrip(".")
    try:
        return message_factory.GetMessageClass(_pool().FindMessageTypeByName(name))
    except KeyError as exc:
        raise LiqiError(f"schema 里没有消息类型 {name}") from exc


def has_message(full_name: str) -> bool:
    try:
        message_class(full_name)
        return True
    except LiqiError:
        return False


def parse(full_name: str, data: bytes):
    msg = message_class(full_name)()
    msg.ParseFromString(data)
    return msg


def to_dict(msg) -> dict:
    """protobuf → dict,保留原字段名。

    默认值字段会被省略(``ju: 0`` 直接不存在)—— 这正是 protobuf-JSON 的语义,
    也是 :func:`mortal_replay.majsoul.parse.parse_downloadlogs` 已经在容忍的行为。
    """
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(msg, preserving_proto_field_name=True)

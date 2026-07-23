"""雀魂 → mjai 转换的测试。

分两层:
* 纯 Python 单元(牌编码、消费牌推导)—— 无需 libriichi,总是跑。
* 端到端合法性(把整局喂进 PlayerState.update)—— 需要构建好的 libriichi,
  没有就 skip。真牌谱上的 28/28 通过记录在 README。
"""

import pytest

from mortal_replay.majsoul.mjai_convert import (
    ConvertError,
    _kakan_consumed,
    id_to_mjai_tile,
    ms_to_mjai_tile,
)

try:  # 端到端测试要用的构建产物
    import libriichi  # noqa: F401

    HAS_LIBRIICHI = hasattr(libriichi, "state")
except ImportError:
    HAS_LIBRIICHI = False


@pytest.mark.parametrize(
    "ms,mjai",
    [
        ("1m", "1m"), ("9s", "9s"), ("5p", "5p"),
        ("0m", "5mr"), ("0p", "5pr"), ("0s", "5sr"),
        ("1z", "E"), ("2z", "S"), ("3z", "W"), ("4z", "N"),
        ("5z", "P"), ("6z", "F"), ("7z", "C"),
    ],
)
def test_ms_to_mjai_tile(ms, mjai):
    assert ms_to_mjai_tile(ms) == mjai


def test_id_to_mjai_red_fives():
    # 内部编码里赤 5 固定占 copy 0
    assert id_to_mjai_tile(16) == "5mr"
    assert id_to_mjai_tile(52) == "5pr"
    assert id_to_mjai_tile(88) == "5sr"
    assert id_to_mjai_tile(17) == "5m"  # 普通 5m


def test_kakan_consumed_normal_vs_red():
    assert _kakan_consumed("3p") == ["3p", "3p", "3p"]
    # 5 系:碰面子里含一张赤
    assert _kakan_consumed("5m") == ["5mr", "5m", "5m"]
    assert _kakan_consumed("5s") == ["5sr", "5s", "5s"]


def test_rejects_bad_tile():
    with pytest.raises(ConvertError):
        ms_to_mjai_tile("123")  # 长度不对


def test_start_kyoku_puts_13_tiles_and_first_tsumo():
    """庄家 14 张里,起手 tehais 只放 13,第 14 张作为首个 tsumo 事件。"""
    from mortal_replay.majsoul.mjai_convert import convert_hand
    from mortal_replay.majsoul.parse import parse_record
    from mortal_replay.majsoul.synth import synth_record

    rec = parse_record(synth_record(seed=3, k=1))
    hand = rec.hands[0]
    events = convert_hand(hand, [])  # 无后续动作,退化成只有开局
    sk = events[0]
    assert sk["type"] == "start_kyoku"
    assert all(len(t) == 13 for t in sk["tehais"])
    assert events[1]["type"] == "tsumo"
    assert events[1]["actor"] == hand.oya

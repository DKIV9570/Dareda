import pytest

from mortal_replay.majsoul.codec import format_paishan, parse_paishan
from mortal_replay.majsoul.synth import full_wall_codes
from mortal_replay.tiles import RED_IDS, TileError, is_red, tile_to_code


def test_full_wall_roundtrip():
    s = "".join(full_wall_codes())
    ids = parse_paishan(s)
    assert len(ids) == 136
    assert len(set(ids)) == 136
    assert format_paishan(ids) == s


def test_red_five_takes_copy_zero():
    ids = parse_paishan("".join(full_wall_codes()))
    reds = [t for t in ids if is_red(t)]
    assert sorted(reds) == sorted(RED_IDS)
    assert {tile_to_code(t) for t in reds} == {"0m", "0p", "0s"}


def test_normal_fives_avoid_copy_zero():
    # 三张普通 5m 应当落在 copy 1..3,把 copy 0 留给赤
    ids = parse_paishan("5m5m5m0m", expect=None)
    assert ids[:3] == [17, 18, 19]
    assert ids[3] == 16  # 赤 5m


def test_no_red_rule_falls_back_to_copy_zero():
    ids = parse_paishan("5m5m5m5m", expect=None)
    assert sorted(ids) == [16, 17, 18, 19]


def test_rejects_fifth_copy():
    with pytest.raises(TileError, match="超过 4 枚"):
        parse_paishan("1m1m1m1m1m", expect=None)


def test_rejects_wrong_length():
    with pytest.raises(TileError, match="牌山张数"):
        parse_paishan("1m2m")


def test_rejects_bad_code():
    with pytest.raises(TileError):
        parse_paishan("8z", expect=None)

"""§5 配牌恒等断言的测试。

注意合成数据的射程:它能撞出索引算术和编解码的错,撞不出**牌山约定**的错
(约定是合成数据自己假设的)。所以这里额外用"手工构造的坏数据"来确认断言真的
会红,而不是永远绿。
"""

from mortal_replay.deal import WallConvention
from mortal_replay.majsoul.parse import parse_record
from mortal_replay.majsoul.synth import synth_record
from mortal_replay.verify import infer_convention, verify_record


def test_synthetic_record_passes():
    record = parse_record(synth_record(seed=7, k=10))
    report = verify_record(record)
    assert report.ok, report.render()
    assert report.passed == 10


def test_oya_seat_has_fourteen_tiles():
    """雀魂里庄家那档是 14 张(配牌 13 + 第一枚自摸),断言要把它一起吃掉。"""
    raw = synth_record(seed=1, k=4)
    for hand in raw["hands"]:
        oya = hand["ju"]
        counts = [len(hand[f"tiles{s}"]) for s in range(4)]
        assert counts[oya] == 14
        assert sum(counts) == 13 * 4 + 1


def test_detects_wrong_convention():
    """把牌山整体挪 14 张,默认约定就该红,而 infer 能找回正确的那个。"""
    raw = synth_record(seed=3, k=3)
    for hand in raw["hands"]:
        p = hand["paishan"]
        # 尾 14 张搬到头部 = DEAD_WALL_HEAD 布局
        hand["paishan"] = p[-28:] + p[:-28]
    record = parse_record(raw)
    assert not verify_record(record).ok
    assert infer_convention(record) is WallConvention.DEAD_WALL_HEAD


def test_detects_swapped_hands():
    """两家起手对调,断言必须红 —— 证明它不是恒真。"""
    raw = synth_record(seed=5, k=2)
    h = raw["hands"][0]
    h["tiles1"], h["tiles2"] = h["tiles2"], h["tiles1"]
    report = verify_record(parse_record(raw))
    assert not report.ok
    assert "座1" in report.render()


def test_detects_red_five_mangled():
    """把赤 5 写成普通 5,断言必须红 —— §3.3 最容易出错的地方。"""
    raw = synth_record(seed=11, k=6)
    hit = False
    for hand in raw["hands"]:
        for seat in range(4):
            tiles = hand[f"tiles{seat}"]
            for i, t in enumerate(tiles):
                if t.startswith("0"):
                    tiles[i] = "5" + t[1]
                    hit = True
                    break
            if hit:
                break
        if hit:
            break
    assert hit, "合成数据里居然没有赤 5,测试失效"
    assert not verify_record(parse_record(raw)).ok


def test_infer_returns_none_when_data_is_broken():
    raw = synth_record(seed=13, k=2)
    raw["hands"][0]["tiles0"] = list(reversed(raw["hands"][0]["tiles1"]))[:13]
    assert infer_convention(parse_record(raw)) is None

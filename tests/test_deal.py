import pytest

from dareda.deal import DEAD_WALL_SIZE, WallConvention, deal, seat_order, split_wall


@pytest.fixture
def wall():
    """0..135 的有序牌山 —— 位置即数值,索引算术错了一眼能看出来。"""
    return list(range(136))


def test_seat_order():
    assert seat_order(0) == [0, 1, 2, 3]
    assert seat_order(2) == [2, 3, 0, 1]


def test_deal_shape(wall):
    r = deal(wall, oya=0)
    assert [len(h) for h in r.haipai] == [13] * 4
    assert r.draw_cursor == 52
    assert r.dead_wall == tuple(range(136 - DEAD_WALL_SIZE, 136))


def test_deal_order_is_4_4_4_1_from_oya(wall):
    r = deal(wall, oya=0)
    # 庄家:前三轮各拿 4 张(0-3, 16-19, 32-35),最后一轮 1 张(48)
    assert r.haipai[0] == (0, 1, 2, 3, 16, 17, 18, 19, 32, 33, 34, 35, 48)
    assert r.haipai[1] == (4, 5, 6, 7, 20, 21, 22, 23, 36, 37, 38, 39, 49)
    assert r.haipai[3] == (12, 13, 14, 15, 28, 29, 30, 31, 44, 45, 46, 47, 51)


def test_oya_shifts_who_gets_first_block(wall):
    r = deal(wall, oya=2)
    assert r.haipai[2][:4] == (0, 1, 2, 3)  # 庄家先拿
    assert r.haipai[3][:4] == (4, 5, 6, 7)  # 下家
    assert r.haipai[1][:4] == (12, 13, 14, 15)  # 上家最后
    # 无论庄位怎么变,配牌总是消耗前 52 张
    assert r.draw_cursor == 52


def test_partition_is_exact(wall):
    for oya in range(4):
        r = deal(wall, oya)
        dealt = sorted(t for h in r.haipai for t in h)
        assert dealt == list(range(52))


def test_dead_wall_head_convention(wall):
    r = deal(wall, oya=0, convention=WallConvention.DEAD_WALL_HEAD)
    assert r.dead_wall == tuple(range(DEAD_WALL_SIZE))
    assert r.haipai[0][0] == DEAD_WALL_SIZE
    assert r.draw_cursor == DEAD_WALL_SIZE + 52


def test_rejects_bad_oya(wall):
    with pytest.raises(ValueError, match="庄位越界"):
        deal(wall, oya=4)


# ------------------------------------------------------- split_wall / libriichi 对接


def test_split_wall_partitions_exactly(wall):
    """136 张必须不重不漏地分进五个桶 —— 方向怎么摆都不该丢牌。"""
    for oya in range(4):
        s = split_wall(wall, oya)
        allocated = sorted(
            [t for h in s.haipai for t in h]
            + list(s.yama)
            + list(s.rinshan)
            + list(s.dora_indicators)
            + list(s.ura_indicators)
        )
        assert allocated == list(range(136))
        assert [len(s.yama), len(s.rinshan), len(s.dora_indicators), len(s.ura_indicators)] == [70, 4, 5, 5]


def test_yama_pops_in_draw_order(wall):
    """libriichi 的 yama 是尾部 pop,所以必须倒序存放。"""
    s = split_wall(wall, oya=0)
    y = list(s.yama)
    assert y.pop() == 52  # 庄家第一枚自摸
    assert y.pop() == 53
    assert y.pop() == 54
    assert s.first_draw == 52
    assert s.yama[0] == 121  # 最后一张摸的牌躺在数组头部


def test_dead_wall_offsets(wall):
    """王牌区按 7 墩还原:岭上取端头两墩,宝牌是第 3 墩上张,里宝是其下张。"""
    s = split_wall(wall, oya=0)
    # 倒序存放,pop 出来才是实际顺序
    assert list(reversed(s.rinshan)) == [135, 134, 133, 132]
    assert list(reversed(s.dora_indicators)) == [131, 129, 127, 125, 123]
    # ura 是正序 iter
    assert list(s.ura_indicators) == [130, 128, 126, 124, 122]


def test_dora_and_ura_are_stack_pairs(wall):
    """每张宝牌指示牌与同序号的里宝必须来自同一墩(相邻两张)。"""
    s = split_wall(wall, oya=0)
    for dora, ura in zip(reversed(s.dora_indicators), s.ura_indicators):
        assert abs(dora - ura) == 1


def test_split_wall_haipai_matches_deal(wall):
    for oya in range(4):
        assert split_wall(wall, oya).haipai == deal(wall, oya).haipai


def test_split_wall_rejects_wrong_convention(wall):
    """约定选错会导致活牌山不是 70 张,应当当场报错而不是悄悄算下去。"""
    with pytest.raises(ValueError, match="活牌山应为 70 张"):
        split_wall(wall, oya=0, convention=WallConvention.DEAD_WALL_HEAD)

from mortal_replay.rules import (
    HandOutcome,
    Outcome,
    TableState,
    placements,
    settle,
)


def ron(winner, loser, points, **kw):
    d = [0, 0, 0, 0]
    d[winner] += points
    d[loser] -= points
    return HandOutcome(Outcome.RON, tuple(d), winners=(winner,), loser=loser, **kw)


def tsumo(winner, each, **kw):
    d = [-each] * 4
    d[winner] = each * 3
    return HandOutcome(Outcome.TSUMO, tuple(d), winners=(winner,), **kw)


def test_ron_honba_paid_by_dealin_only():
    st = TableState()
    s = settle(st, ron(1, 3, 3900), honba=2)
    assert s.deltas == (0, 3900 + 600, 0, -(3900 + 600))
    assert s.scores_after == (25000, 29500, 25000, 20500)


def test_tsumo_honba_split_across_three():
    st = TableState()
    s = settle(st, tsumo(0, 1000), honba=3)
    assert s.deltas[0] == 3000 + 900
    assert all(d == -(1000 + 300) for d in s.deltas[1:])
    assert sum(s.deltas) == 0


def test_honba_zero_is_noop():
    st = TableState()
    s = settle(st, ron(1, 3, 3900), honba=0)
    assert s.deltas == (0, 3900, 0, -3900)


def test_riichi_declaration_moves_stick_to_table():
    st = TableState()
    s = settle(st, HandOutcome(Outcome.RYUUKYOKU, (0, 0, 0, 0), riichi_declarations=(2,)), honba=1)
    assert s.deltas == (0, 0, -1000, 0)
    assert s.riichi_sticks_after == 1  # 流局结转到下一局


def test_winner_collects_carried_sticks():
    st = TableState(riichi_sticks=2)
    s = settle(st, ron(1, 3, 1000), honba=0)
    assert s.deltas[1] == 1000 + 2000
    assert s.riichi_sticks_after == 0


def test_declarer_who_wins_gets_own_stick_back():
    st = TableState()
    s = settle(st, ron(1, 3, 1300, riichi_declarations=(1,)), honba=0)
    assert s.deltas[1] == 1300 - 1000 + 1000
    assert s.riichi_sticks_after == 0


def test_double_ron_head_bump_takes_honba_and_sticks():
    """放铳者座 0,和牌者座 2 与座 3 —— 座 1 起数,最近的是座 2。"""
    st = TableState(riichi_sticks=1)
    out = HandOutcome(
        Outcome.RON, (-5000, 0, 3000, 2000), winners=(2, 3), loser=0
    )
    s = settle(st, out, honba=1)
    assert s.deltas[2] == 3000 + 300 + 1000
    assert s.deltas[3] == 2000
    assert s.deltas[0] == -5000 - 300


def test_bust_detected():
    st = TableState(scores=[1000, 25000, 25000, 49000])
    s = settle(st, ron(3, 0, 8000), honba=0)
    assert s.scores_after[0] == -7000
    assert s.busted == (0,)


def test_no_bust_at_exactly_zero():
    """§2 的终止条件是 < 0,刚好 0 点不算击飞。"""
    st = TableState(scores=[8000, 25000, 25000, 42000])
    s = settle(st, ron(3, 0, 8000), honba=0)
    assert s.scores_after[0] == 0
    assert s.busted == ()


def test_placements():
    assert placements((30000, 25000, 20000, 25000)) == [1, 2, 4, 3]

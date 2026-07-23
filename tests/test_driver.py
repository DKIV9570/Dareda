from mortal_replay.driver import StopReason, comparison_table, run_replay
from mortal_replay.engine.base import ScriptedEngine
from mortal_replay.majsoul.parse import parse_record
from mortal_replay.majsoul.synth import synth_record
from mortal_replay.rules import HandOutcome, Outcome

DRAW = HandOutcome(Outcome.RYUUKYOKU, (0, 0, 0, 0))


def _record(k=10, seed=0):
    return parse_record(synth_record(seed=seed, k=k))


def test_sequence_is_pinned_regardless_of_who_wins():
    """庄家连和也不插连庄局,序列由牌谱外生给定(§1.1)。"""
    rec = _record(k=10)
    oya_wins = [
        HandOutcome(Outcome.TSUMO, tuple(1500 if s == h.oya else -500 for s in range(4)),
                    winners=(h.oya,))
        for h in rec.hands
    ]
    result = run_replay(rec, ScriptedEngine(oya_wins))
    assert result.hands_played == rec.K
    assert [log.hand.key for log in result.logs] == rec.sequence
    assert result.stop_reason is StopReason.COMPLETED


def test_honba_comes_from_label_not_from_replay():
    """序列里的本场局,即使 replay 里上一局是庄家放铳,也照标签算本场棒。"""
    rec = _record(k=10)
    honba_idx = next(i for i, h in enumerate(rec.hands) if h.ben > 0)
    outcomes = [DRAW] * rec.K
    outcomes[honba_idx] = HandOutcome(
        Outcome.RON, (0, 1000, 0, -1000), winners=(1,), loser=3
    )
    result = run_replay(rec, ScriptedEngine(outcomes))
    log = result.logs[honba_idx]
    assert log.hand.ben == 1
    assert log.settlement.deltas[1] == 1000 + 300


def test_bust_terminates_early():
    rec = _record(k=10)
    outcomes = [DRAW, DRAW, HandOutcome(Outcome.RON, (-32000, 32000, 0, 0),
                                        winners=(1,), loser=0)]
    result = run_replay(rec, ScriptedEngine(outcomes))
    assert result.stop_reason is StopReason.BUSTED
    assert result.hands_played == 3 < rec.K
    assert result.final_scores[0] < 0


def test_scores_carry_across_hands():
    rec = _record(k=3)
    start = rec.hands[0].scores
    outcomes = [
        HandOutcome(Outcome.RON, (0, 2000, 0, -2000), winners=(1,), loser=3),
        DRAW,
        HandOutcome(Outcome.RON, (0, 0, 1000, -1000), winners=(2,), loser=3),
    ]
    result = run_replay(rec, ScriptedEngine(outcomes))
    assert result.logs[1].scores_before[1] == start[1] + 2000
    assert sum(result.final_scores) == sum(start)


def test_riichi_sticks_carry_across_hands():
    rec = _record(k=3)
    outcomes = [
        HandOutcome(Outcome.RYUUKYOKU, (0, 0, 0, 0), riichi_declarations=(0, 1)),
        DRAW,
        HandOutcome(Outcome.RON, (0, 0, 1000, -1000), winners=(2,), loser=3),
    ]
    result = run_replay(rec, ScriptedEngine(outcomes))
    assert result.logs[1].scores_before == result.logs[0].settlement.scores_after
    assert result.logs[2].settlement.deltas[2] == 1000 + 2000
    assert result.riichi_sticks_left == 0


def test_comparison_table_renders():
    rec = _record(k=4)
    result = run_replay(rec, ScriptedEngine([DRAW] * 4))
    table = comparison_table(result)
    assert "Mortal replay" in table
    assert "K' = 4" in table
    assert "合成数据" in table

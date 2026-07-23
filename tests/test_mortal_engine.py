"""Mortal/libriichi 适配层的测试。

只测**纯 Python 的那一半** —— 结果分类与结算通路。真正跑牌需要构建好的
libriichi 扩展和 130 MB 权重,不适合放进单测;那条路由 scripts/smoke_kyoku.py
和 `mortal-replay replay` 覆盖。
"""

from types import SimpleNamespace

import pytest

from mortal_replay.engine.mortal_engine import _classify, to_hand_outcome
from mortal_replay.engine.base import HandSetup
from mortal_replay.majsoul.parse import parse_record
from mortal_replay.majsoul.synth import synth_record
from mortal_replay.rules import Outcome, TableState, settle


def _outcome(deltas, *, hora=False, abortive=False, kyotaku_left=0, log=()):
    return SimpleNamespace(
        deltas=list(deltas),
        has_hora=hora,
        has_abortive_ryukyoku=abortive,
        can_renchan=False,
        kyotaku_left=kyotaku_left,
        mjai_log=list(log),
    )


def _setup(sticks=0, scores=(25000,) * 4):
    hand = parse_record(synth_record(seed=1, k=1)).hands[0]
    return HandSetup(hand=hand, scores=scores, riichi_sticks=sticks)


# ------------------------------------------------------------------ 结果分类


def test_classifies_tsumo_from_mjai_log():
    log = ['{"type":"hora","actor":2,"target":2,"pai":"5p"}']
    kind, winners, loser = _classify(_outcome([-1000, -1000, 3000, -1000], hora=True, log=log))
    assert (kind, winners, loser) == (Outcome.TSUMO, (2,), None)


def test_classifies_ron_from_mjai_log():
    log = ['{"type":"hora","actor":1,"target":3,"pai":"1z"}']
    kind, winners, loser = _classify(_outcome([0, 3900, 0, -3900], hora=True, log=log))
    assert (kind, winners, loser) == (Outcome.RON, (1,), 3)


def test_classifies_double_ron():
    log = [
        '{"type":"hora","actor":1,"target":0,"pai":"1z"}',
        '{"type":"hora","actor":2,"target":0,"pai":"1z"}',
    ]
    kind, winners, loser = _classify(_outcome([-8000, 5000, 3000, 0], hora=True, log=log))
    assert kind is Outcome.RON
    assert set(winners) == {1, 2}
    assert loser == 0


def test_classifies_ryuukyoku_and_abortive():
    assert _classify(_outcome([0] * 4))[0] is Outcome.RYUUKYOKU
    assert _classify(_outcome([0] * 4, abortive=True))[0] is Outcome.ABORTIVE


def test_falls_back_when_log_has_no_hora():
    """日志格式变了也不能崩,退回按点数正负判断。"""
    kind, winners, loser = _classify(_outcome([0, 2000, 0, -2000], hora=True, log=['{"type":"dahai"}']))
    assert (kind, winners, loser) == (Outcome.RON, (1,), None)


# ------------------------------------------------------------ 已结算通路


def test_pre_settled_outcome_is_taken_verbatim():
    """libriichi 给的是终值,rules 不能再叠本场棒和立直棒。"""
    setup = _setup(sticks=0)
    log = ['{"type":"hora","actor":1,"target":3,"pai":"1z"}']
    out = to_hand_outcome(_outcome([0, 5800, 0, -5800], hora=True, log=log), setup)
    assert out.pre_settled and out.kyotaku_after == 0

    st = TableState(scores=[25000] * 4)
    s = settle(st, out, honba=3)  # 本场数不为 0,但绝不能再加 900
    assert s.deltas == (0, 5800, 0, -5800)
    assert s.scores_after == (25000, 30800, 25000, 19200)


def test_pre_settled_carries_engine_stick_count():
    setup = _setup(sticks=1)
    out = to_hand_outcome(_outcome([-1000, 0, 0, 0], kyotaku_left=2), setup)
    s = settle(TableState(scores=[25000] * 4, riichi_sticks=1), out, honba=0)
    assert s.riichi_sticks_after == 2
    assert s.scores_after[0] == 24000


def test_pre_settled_detects_bust():
    setup = _setup(scores=(1000, 25000, 25000, 49000))
    log = ['{"type":"hora","actor":3,"target":0,"pai":"1z"}']
    out = to_hand_outcome(_outcome([-8000, 0, 0, 8000], hora=True, log=log), setup)
    s = settle(TableState(scores=[1000, 25000, 25000, 49000]), out, honba=0)
    assert s.busted == (0,)


def test_rejects_non_conserving_engine_result():
    """引擎报了不守恒的点数必须当场炸,不能悄悄往下算。"""
    with pytest.raises(RuntimeError, match="点数不守恒"):
        to_hand_outcome(_outcome([0, 5000, 0, -3000]), _setup())


def test_stick_movement_counts_toward_conservation():
    """两家立直:场上多 2000,deltas 和为 -2000 才对。"""
    out = to_hand_outcome(_outcome([-1000, -1000, 0, 0], kyotaku_left=2), _setup(sticks=0))
    assert sum(out.base_deltas) == -2000

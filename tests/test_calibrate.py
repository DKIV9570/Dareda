"""boltzmann 标定的测试(纯数值,无需 libriichi/权重)。"""

import math

from dareda.analysis.calibrate import (
    BoltzmannParams,
    calibrate,
    mean_softmax_ev_loss,
)


def test_zero_target_gives_greedy():
    q = [[0.0, -1.0, -2.0]] * 5
    p = calibrate(q, 0.0)
    assert p == BoltzmannParams(0.0, 1.0)


def test_no_samples_gives_greedy():
    assert calibrate([], 0.5) == BoltzmannParams(0.0, 1.0)


def test_target_below_base_solves_epsilon_at_temp1():
    q = [[0.0, -0.5, -1.0], [0.0, -0.3, -0.9]]
    base = mean_softmax_ev_loss(q, 1.0)
    target = base * 0.5
    p = calibrate(q, target)
    assert p.temp == 1.0
    assert 0 < p.epsilon < 1
    # 验证:eps 下的期望 EV loss 应回到 target
    assert math.isclose(p.epsilon * base, target, rel_tol=1e-9)


def test_target_above_base_raises_temp():
    q = [[0.0, -0.5, -1.0], [0.0, -0.4, -0.8]]
    base = mean_softmax_ev_loss(q, 1.0)
    ceiling = mean_softmax_ev_loss(q, 1e9)  # 均匀采样的 EV loss 上限
    target = (base + ceiling) / 2  # 比满采样弱、但在上限内,可达
    p = calibrate(q, target)
    assert p.epsilon == 1.0
    assert p.temp > 1.0
    assert math.isclose(mean_softmax_ev_loss(q, p.temp), target, rel_tol=1e-3)


def test_unreachable_target_caps_at_max_temp():
    """目标超过均匀采样上限时,温度顶到最大而不报错(随机也弱不到那个程度)。"""
    q = [[0.0, -0.5, -1.0], [0.0, -0.4, -0.8]]
    ceiling = mean_softmax_ev_loss(q, 1e9)
    p = calibrate(q, ceiling * 5)
    assert p.epsilon == 1.0
    assert mean_softmax_ev_loss(q, p.temp) <= ceiling + 1e-6


def test_ev_loss_monotonic_in_temp():
    q = [[0.0, -0.5, -1.0, -1.5]]
    lo = mean_softmax_ev_loss(q, 0.5)
    mid = mean_softmax_ev_loss(q, 1.0)
    hi = mean_softmax_ev_loss(q, 3.0)
    assert lo < mid < hi


def test_single_legal_action_has_zero_loss():
    assert mean_softmax_ev_loss([[1.5]], 1.0) == 0.0

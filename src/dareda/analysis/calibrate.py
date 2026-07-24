"""把目标 EV loss 标定成 Mortal 的 boltzmann 参数。

Mortal 的采样策略是 epsilon-greedy + softmax:
* 以 ``1-eps`` 概率取 argmax(该决策 EV loss = 0);
* 以 ``eps`` 概率从 ``softmax(Q / temp)`` 里采样(EV loss = Σ p_a·(Qmax - Q_a))。

所以某温度下一个策略的**期望 EV loss** 完全由测量时收集的每决策 Q 数组决定,
不用重跑网络:

    E[loss](eps, temp) = eps · mean_over_decisions( Σ_a softmax(Q/temp)_a·(Qmax - Q_a) )

固定 ``temp=1``(Mortal 自身的 Q 尺度),对 eps 是**线性**的,直接解:

    eps = target_ev / base_ev,   base_ev = temp=1 满采样的平均 EV loss

若 target 比 base 还大(该家比满采样更弱),eps 顶到 1 后再往上调 temp。

**这一层是"去偏 + 敏感性",不是保真度修复**(见 counterfactual.py 与 README):
它让脱轨后的对手强度对齐真人,去掉"对手变超人"这个偏差,但脱轨部分依旧是猜;而且
一致率/EV loss 是在对手面对**真人**hero 时测的,用到面对 **Mortal** hero 的局面上属
分布外近似。所以正确用法是在几档强度下各跑一遍看结论稳不稳,而非当成单一真值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _softmax_ev_loss(q: list[float], temp: float) -> float:
    """单个决策在 softmax(Q/temp) 下的期望 EV loss = Σ p_a (Qmax - Q_a)。"""
    if len(q) <= 1:
        return 0.0
    qmax = max(q)
    z = [(x - qmax) / temp for x in q]  # 减 qmax 防溢出
    exps = [math.exp(v) for v in z]
    s = sum(exps)
    ps = [e / s for e in exps]
    return sum(p * (qmax - x) for p, x in zip(ps, q))


def mean_softmax_ev_loss(q_samples: list[list[float]], temp: float) -> float:
    if not q_samples:
        return 0.0
    return sum(_softmax_ev_loss(q, temp) for q in q_samples) / len(q_samples)


@dataclass
class BoltzmannParams:
    epsilon: float
    temp: float

    def as_kwargs(self) -> dict:
        return {"boltzmann_epsilon": self.epsilon, "boltzmann_temp": self.temp}


def calibrate(q_samples: list[list[float]], target_ev_loss: float) -> BoltzmannParams:
    """求一组 boltzmann 参数,使期望 EV loss ≈ ``target_ev_loss``。

    * target ≤ 0 或无样本 → greedy(eps=0)。
    * target ≤ base(temp=1 满采样)→ 固定 temp=1,解 eps = target/base。
    * target > base → eps=1,二分抬高 temp 直到期望 EV loss 命中 target。
    """
    if target_ev_loss <= 0 or not q_samples:
        return BoltzmannParams(0.0, 1.0)

    base = mean_softmax_ev_loss(q_samples, temp=1.0)
    if base <= 0:
        return BoltzmannParams(0.0, 1.0)

    if target_ev_loss <= base:
        return BoltzmannParams(min(1.0, target_ev_loss / base), 1.0)

    # 需要比满采样更弱:eps=1,二分温度(EV loss 随 temp 单调增)
    lo, hi = 1.0, 2.0
    for _ in range(40):
        if mean_softmax_ev_loss(q_samples, hi) >= target_ev_loss:
            break
        hi *= 2
        if hi > 1e6:
            break
    for _ in range(60):
        mid = (lo + hi) / 2
        if mean_softmax_ev_loss(q_samples, mid) < target_ev_loss:
            lo = mid
        else:
            hi = mid
    return BoltzmannParams(1.0, (lo + hi) / 2)

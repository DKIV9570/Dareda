"""蒙特卡洛内核:跑 N 条随机轨迹,聚合名次分布。

单次反事实(hero 换 Mortal)方差极大、被脱轨瀑布主导(见 counterfactual.py)。要下
结论,得跑**分布**而非单点。这里把两件事统一在一套机器上:

* **对手按标定强度**:hero=greedy Mortal,三个对手用各自 EV loss 标定的温度化 Mortal
  作脱轨后 fallback。对手带随机性,所以要跑 N 次看 hero 名次分布,并可在几档强度上
  各跑一遍做敏感性分析。
* (未来)**固定配牌重采样**(§7.1):锁 hero 起手+庄位,重洗剩余牌 —— 复用同一个
  N 轨迹 + 分布聚合框架。

**可复现**:Mortal 的唯一随机源是 boltzmann 采样(torch 全局 RNG)。每条轨迹前
``torch.manual_seed(base_seed + i)``,整个 MC 就可复现。greedy 引擎无随机,温度化引擎
才吃种子。
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field

from .driver import run_replay
from .engine.base import HandSetup
from .engine.logfollow import LogFollowEngine
from .engine.mortal_engine import to_hand_outcome
from .majsoul.mjai_convert import convert_hand
from .rules import placements


@dataclass
class Distribution:
    """某座名次(1..4)的分布。"""

    seat: int
    counts: Counter = field(default_factory=Counter)
    final_scores: list = field(default_factory=list)

    def add(self, scores) -> None:
        self.counts[placements(scores)[self.seat]] += 1
        self.final_scores.append(scores[self.seat])

    @property
    def n(self) -> int:
        return sum(self.counts.values())

    @property
    def avg_placement(self) -> float:
        return sum(p * c for p, c in self.counts.items()) / self.n if self.n else 0.0

    @property
    def avg_score(self) -> float:
        return sum(self.final_scores) / len(self.final_scores) if self.final_scores else 0.0

    def render(self, label: str = "") -> str:
        head = f"{label}  n={self.n}  平均顺位 {self.avg_placement:.2f}  平均点数 {self.avg_score:.0f}"
        bars = []
        for p in (1, 2, 3, 4):
            c = self.counts.get(p, 0)
            pct = c / self.n * 100 if self.n else 0
            bars.append(f"    {p}位 {pct:>5.1f}%  {'█' * round(pct / 3)}")
        return head + "\n" + "\n".join(bars)


def luck_verdict(dist: "Distribution", actual_place: int) -> str:
    """把实际名次放进分布,给个运气判断。

    ``p_worse_equal`` = 我的同水平自己打到"这么差或更差"的概率。很小 ⇒ 这次偏背;
    很大 ⇒ 这次结果对我的水平来说属正常甚至偏顺。
    """
    n = dist.n
    p_this_place = dist.counts.get(actual_place, 0) / n if n else 0
    p_worse_equal = sum(c for p, c in dist.counts.items() if p >= actual_place) / n if n else 0
    p_better = sum(c for p, c in dist.counts.items() if p < actual_place) / n if n else 0
    exp = dist.avg_placement

    if p_worse_equal <= 0.25:
        tone = f"偏背 —— 你的同水平只有 {p_worse_equal*100:.0f}% 会打到 {actual_place} 位或更差"
    elif p_better <= 0.25:
        tone = f"偏顺 —— 你的同水平有 {p_better*100:.0f}% 能打得比 {actual_place} 位更好,你已在好的一端"
    else:
        tone = f"基本正常 —— {actual_place} 位在你同水平的常见范围内"
    return (
        f"实际 {actual_place} 位;同水平自打期望 {exp:.2f} 位。\n"
        f"  P(打到{actual_place}位)={p_this_place*100:.0f}%  "
        f"P(≤{actual_place}位,即这么差或更差)={p_worse_equal*100:.0f}%  "
        f"P(比{actual_place}位更好)={p_better*100:.0f}%\n"
        f"  判断:{tone}"
    )


class CounterfactualMonteCarlo:
    """hero 换 Mortal、对手按标定强度打,跑 N 条随机轨迹。"""

    def __init__(
        self,
        record,
        actions_by_round,
        hero_seat: int,
        weights,
        opponent_params: dict,
        *,
        base_seed: int = 0,
    ):
        """:param opponent_params: {seat: BoltzmannParams},非 hero 座各自的采样参数。"""
        import libriichi

        self._libriichi = libriichi
        self._record = record
        self._humans = [convert_hand(h, a) for h, a in zip(record.hands, actions_by_round)]
        self._hero = hero_seat
        self._follow = {s for s in range(4) if s != hero_seat}
        self._base_seed = base_seed

        # 每座一个引擎:hero greedy,对手按标定温度。共享权重张量,不重载。
        self._engines = []
        for seat in range(4):
            if seat == hero_seat:
                self._engines.append(weights.make_engine(name=f"hero{seat}-greedy"))
            else:
                p = opponent_params[seat]
                self._engines.append(
                    weights.make_engine(name=f"opp{seat}", **p.as_kwargs())
                )

    def _run_one(self, seed: int):
        import torch

        torch.manual_seed(seed)
        engines = self._engines

        class _Engine:
            def __init__(inner):
                inner.idx = 0

            def play_hand(inner, setup: HandSetup):
                from .deal import split_wall

                i = inner.idx
                inner.idx += 1
                le = LogFollowEngine(self._humans[i], self._follow, engines)
                runner = self._libriichi.arena.KyokuReplay(le)
                w = split_wall(setup.hand.paishan, setup.hand.oya)
                out = runner.run(
                    haipai=[list(h) for h in w.haipai],
                    yama=list(w.yama), rinshan=list(w.rinshan),
                    dora_indicators=list(w.dora_indicators),
                    ura_indicators=list(w.ura_indicators),
                    kyoku=setup.hand.chang * 4 + setup.hand.ju,
                    honba=setup.hand.ben, kyotaku=setup.riichi_sticks,
                    scores=list(setup.scores),
                )
                return to_hand_outcome(out, setup)

            def close(inner):
                pass

        return run_replay(self._record, _Engine())

    def run(self, n: int, *, progress=None) -> Distribution:
        dist = Distribution(self._hero)
        for i in range(n):
            res = self._run_one(self._base_seed + i)
            dist.add(res.final_scores)
            if progress:
                progress(i + 1, n, res)
        return dist


class SelfStrengthMonteCarlo:
    """全员按各自标定强度的 Mortal,在固定牌山上重打 N 次。

    回答"以我(和对手)的现有水平,这一局的结果是运气好还是差":四家都是自己强度的
    温度化 Mortal,没人照日志走 —— 所以**不涉及保真度**,是最干净的一个反事实。把我
    的实际名次放进这个分布里看它落在什么位置,就知道运气成分。

    唯一的近似还是标定本身:强度是在"对手面对真人"时测的单局估计,用到"面对 Mortal"
    的局面上属分布外,且样本只有一场约 200 决策,有噪声。所以看的是**大致运气方向**,
    不是精确概率。
    """

    def __init__(self, record, seat_params: dict, weights, *, base_seed: int = 0):
        """:param seat_params: {seat: BoltzmannParams},四家各自的采样参数。"""
        import libriichi

        self._libriichi = libriichi
        self._record = record
        self._seat_params = seat_params
        self._weights = weights
        self._base_seed = base_seed
        self._engines = [
            weights.make_engine(name=f"seat{s}", **seat_params[s].as_kwargs())
            for s in range(4)
        ]

    def _run_one(self, seed: int):
        return _play_trajectory(self._record, self._engines, self._libriichi, seed)

    def run_all(self, n: int, *, jobs=None, progress=None) -> dict:
        """跑 N 条轨迹,**一次拿到四家**的名次分布。

        每条轨迹是一整局四人对局,四家的终局点数都在里面 —— 按 hero 分别重跑是浪费。

        :param jobs: 并行进程数。None=自动(见 :func:`resolve_jobs`);1=顺序。每条轨迹按
            ``base_seed+i`` 播种,**结果与进程数无关** —— jobs=1 和 jobs=8 出一样的分布。
        """
        jobs = resolve_jobs(jobs, n)
        dists = {s: Distribution(s) for s in range(4)}

        if jobs <= 1:
            for i in range(n):
                scores = self._run_one(self._base_seed + i)
                for s in range(4):
                    dists[s].add(scores)
                if progress:
                    progress(i + 1, n, scores)
            return dists

        # 跨轨迹多进程:每个 worker 各自加载权重、单线程,互不干扰(见 _worker_init)。
        from concurrent.futures import ProcessPoolExecutor, as_completed

        init_args = (
            self._weights.state_file,
            self._weights.device,
            self._weights.mortal_src,
            self._seat_params,
            self._record,
        )
        done = 0
        with ProcessPoolExecutor(
            max_workers=jobs, initializer=_worker_init, initargs=init_args
        ) as ex:
            futures = {ex.submit(_worker_run, self._base_seed + i): i for i in range(n)}
            for fut in as_completed(futures):
                scores = fut.result()
                for s in range(4):
                    dists[s].add(scores)
                done += 1
                if progress:
                    progress(done, n, None)
        return dists

    def run(self, hero_seat: int, n: int, *, jobs=None, progress=None) -> Distribution:
        """只要某一座的分布(内部仍是一次跑完四家)。"""
        return self.run_all(n, jobs=jobs, progress=progress)[hero_seat]


# --------------------------------------------------------------- 并行支持
#
# 轨迹逻辑抽成模块级函数,才能既给顺序模式用、又能 pickle 到子进程。
# batch=1 的推理下,16 线程反而比 8 线程慢一倍(实测),所以:主进程 torch 上限设
# min(8, 核数),每个 worker 单线程(进程间已经在并行了,再多线程只会互相抢核)。


class _FourEngineAdapter:
    """driver 认的 ReplayEngine:四家各自的引擎,逐局用 KyokuReplay 打完。"""

    def __init__(self, engines, libriichi):
        self._engines = engines
        self._lib = libriichi

    def play_hand(self, setup: HandSetup):
        from .deal import split_wall

        w = split_wall(setup.hand.paishan, setup.hand.oya)
        out = self._lib.arena.KyokuReplay(self._engines).run(
            haipai=[list(h) for h in w.haipai],
            yama=list(w.yama), rinshan=list(w.rinshan),
            dora_indicators=list(w.dora_indicators),
            ura_indicators=list(w.ura_indicators),
            kyoku=setup.hand.chang * 4 + setup.hand.ju,
            honba=setup.hand.ben, kyotaku=setup.riichi_sticks,
            scores=list(setup.scores),
        )
        return to_hand_outcome(out, setup)

    def close(self):
        pass


def _play_trajectory(record, engines, libriichi, seed):
    """跑一整局(一条轨迹),返回四家终局点数。播种在这里做,保证可复现。"""
    import torch

    torch.manual_seed(seed)
    return tuple(run_replay(record, _FourEngineAdapter(engines, libriichi)).final_scores)


def resolve_jobs(jobs, n: int) -> int:
    """定进程数。None=自动:min(核数//2, 4, n) —— 除以二留余量、封顶 4 控内存
    (每进程各要一份 ~130MB 权重),下限 1。"""
    if jobs is not None:
        return max(1, min(int(jobs), n))
    cores = os.cpu_count() or 2
    return max(1, min(cores // 2, 4, n))


# 每个 worker 进程的全局状态(权重、引擎、牌谱只在 init 时建一次,任务只传种子)
_WORKER: dict = {}


def _worker_init(state_file, device, mortal_src, seat_params, record):
    import torch

    torch.set_num_threads(1)  # 进程已并行,worker 内再多线程只会抢核
    import libriichi

    from .engine.mortal_engine import load_weights

    w = load_weights(state_file, device=device, mortal_src=mortal_src)
    _WORKER["lib"] = libriichi
    _WORKER["record"] = record
    _WORKER["engines"] = [
        w.make_engine(name=f"seat{s}", **seat_params[s].as_kwargs()) for s in range(4)
    ]


def _worker_run(seed):
    return _play_trajectory(_WORKER["record"], _WORKER["engines"], _WORKER["lib"], seed)

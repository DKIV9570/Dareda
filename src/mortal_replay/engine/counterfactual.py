"""反事实 replay:只有英雄座换成 Mortal,三个对手照人类原样打。

回答的问题:"在对手每小局开局都和真实局一样打的前提下,如果**我**换成 Mortal 的打法,
牌局会怎么走。" 这是比"四家全 Mortal"更贴近个人复盘的反事实 —— 它把"对手不同"这个
最大的干扰源尽量摁住。

**但它有个绕不开的天花板**(见 spec §7.2 与 README):对手只能忠实到"你的偏离波及到
他们之前"。你一旦打出和真实局不同的牌、或鸣了不同的牌,turn order 与摸牌就错位,
对手日志失去对齐 —— 从那一刻起他们回落到 Mortal。所以每个小局都带一个**保真度**:
脱轨发生在第几个事件、占该局多大比例。保真度低的局,其反事实结论要打折看。

保真度悖论:Mortal 打得越像你,对手照打得越久(保真度高),但反事实越没信息量;
Mortal 打得越不同,越早脱轨(保真度低),恰恰是你最想分析的局。这是反事实本身的
性质,不是实现缺陷。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..majsoul.mjai_convert import convert_hand
from ..record import GameRecord
from ..rules import HandOutcome
from .base import HandSetup
from .logfollow import LogFollowEngine
from .mortal_engine import load_mortal_engine, to_hand_outcome


@dataclass
class HandFidelity:
    label: str
    divergence_pos: int | None
    """脱轨发生在第几个 mjai 事件;None 表示全程未脱轨(你打得和 Mortal 一致)。"""
    total_events: int

    @property
    def faithful_fraction(self) -> float:
        if self.divergence_pos is None:
            return 1.0
        return self.divergence_pos / self.total_events if self.total_events else 0.0

    @property
    def label_pct(self) -> str:
        if self.divergence_pos is None:
            return "100%(全程一致)"
        return f"{self.faithful_fraction * 100:.0f}%"


class CounterfactualReplayEngine:
    """driver 认的 :class:`ReplayEngine`:英雄座 Mortal,对手照日志打。

    :param record: 人类牌谱(需含动作流,即抓包解出来的那种)。
    :param actions_by_round: 每小局动作,见 :func:`mortal_replay.verify.split_actions_by_round`。
    :param hero_seat: 换成 Mortal 的绝对座次(通常是你)。
    :param state_file: Mortal 权重。
    """

    def __init__(
        self,
        record: GameRecord,
        actions_by_round,
        hero_seat: int,
        *,
        state_file,
        device: str = "cpu",
        mortal_src=None,
    ):
        import libriichi

        self._libriichi = libriichi
        self._humans = [
            convert_hand(h, a) for h, a in zip(record.hands, actions_by_round)
        ]
        self._hero = hero_seat
        self._follow = {s for s in range(4) if s != hero_seat}
        self._engine, tag = load_mortal_engine(state_file, device=device, mortal_src=mortal_src)
        self.determinism_tag = (
            f"{tag}|libriichi={libriichi.__version__}/{libriichi.__profile__}|hero={hero_seat}"
        )
        self.fidelity: list[HandFidelity] = []
        self._idx = 0

    def play_hand(self, setup: HandSetup) -> HandOutcome:
        from ..deal import split_wall

        i = self._idx
        self._idx += 1
        human = self._humans[i]
        log_engine = LogFollowEngine(human, self._follow, self._engine)
        runner = self._libriichi.arena.KyokuReplay(log_engine)

        wall = split_wall(setup.hand.paishan, setup.hand.oya)
        out = runner.run(
            haipai=[list(h) for h in wall.haipai],
            yama=list(wall.yama),
            rinshan=list(wall.rinshan),
            dora_indicators=list(wall.dora_indicators),
            ura_indicators=list(wall.ura_indicators),
            kyoku=setup.hand.chang * 4 + setup.hand.ju,
            honba=setup.hand.ben,
            kyotaku=setup.riichi_sticks,
            scores=list(setup.scores),
        )
        self.fidelity.append(
            HandFidelity(setup.hand.label, log_engine.divergence_position, len(human))
        )
        return to_hand_outcome(out, setup)

    def close(self) -> None:
        pass

    def fidelity_table(self) -> str:
        lines = [f"保真度(英雄=座{self._hero},对手照人类原样打):"]
        lines.append(f"  {'局':<10} {'脱轨@事件':>9} {'该局事件':>8} {'忠实比例':>14}")
        for f in self.fidelity:
            pos = "全程" if f.divergence_pos is None else str(f.divergence_pos)
            lines.append(f"  {f.label:<10} {pos:>9} {f.total_events:>8} {f.label_pct:>14}")
        fully = sum(1 for f in self.fidelity if f.divergence_pos is None)
        med = sorted(f.faithful_fraction for f in self.fidelity)
        median = med[len(med) // 2] if med else 0
        lines.append(f"  —— {fully}/{len(self.fidelity)} 局全程一致;忠实比例中位数 {median*100:.0f}%")
        return "\n".join(lines)

"""接真 Mortal 权重 + libriichi 的 ``KyokuReplay``。

组装方式抄自上游 ``mortal/mortal.py``:从 checkpoint 里读 ``config`` 决定网络形状,
``mortal`` / ``current_dqn`` 两个 state_dict 分别装进 ``Brain`` / ``DQN``。

确定性(spec §4):``MortalEngine`` 的 ``boltzmann_epsilon`` 默认 0,即 greedy
argmax,不采样。固定牌山 + 四个确定性策略 ⇒ 唯一轨迹。唯一的抖动源是浮点 ——
不同 device / AMP / cuDNN algo 下 Q 值末位会变,接近平手的决策可能翻边。所以
:attr:`MortalReplayEngine.determinism_tag` 会把 build 和 device 一起记下来,
跟着结果走。默认 ``enable_amp=False``,别为了快把它打开。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..deal import split_wall
from ..record import Hand
from ..rules import HandOutcome, Outcome
from .base import HandSetup


class EngineUnavailable(RuntimeError):
    """libriichi 扩展或权重没就位。"""


def _import_libriichi():
    try:
        import libriichi
    except ImportError as exc:  # pragma: no cover - 取决于本机构建
        raise EngineUnavailable(
            "导入 libriichi 失败。需要先构建带 KyokuReplay 的扩展:\n"
            "  cd vendor/Mortal/libriichi && cargo build --release\n"
            "然后把 target/release/riichi.dll(Linux 为 libriichi.so)复制成 libriichi.pyd 放进 PYTHONPATH。\n"
            "注意文件名 —— 模块入口是 PyInit_libriichi,而 crate 产物叫 riichi。"
        ) from exc
    if not hasattr(libriichi.arena, "KyokuReplay"):
        raise EngineUnavailable(
            "libriichi 里没有 KyokuReplay —— 用的是未打补丁的构建。"
            "本项目的补丁是 vendor/Mortal/libriichi/src/arena/replay.rs(纯新增文件)。"
        )
    return libriichi


@dataclass
class MortalWeights:
    """载入一次的权重 + 元信息,可反复造不同 boltzmann 参数的引擎(共享张量,不重载)。"""

    brain: object
    dqn: object
    version: int
    device: str
    tag: str
    steps: object
    torch_version: str

    def make_engine(
        self,
        *,
        boltzmann_epsilon: float = 0.0,
        boltzmann_temp: float = 1.0,
        enable_amp: bool = False,
        name: str | None = None,
    ):
        import torch

        from engine import MortalEngine  # type: ignore[import-not-found]

        return MortalEngine(
            self.brain,
            self.dqn,
            version=self.version,
            is_oracle=False,
            device=torch.device(self.device),
            enable_amp=enable_amp,
            enable_quick_eval=False,
            enable_rule_based_agari_guard=True,
            name=name or self.tag,
            boltzmann_epsilon=boltzmann_epsilon,
            boltzmann_temp=boltzmann_temp,
        )


def load_weights(
    state_file: str | Path,
    *,
    device: str = "cpu",
    mortal_src: str | Path | None = None,
) -> MortalWeights:
    """载入 checkpoint,返回可反复造引擎的 :class:`MortalWeights`。"""
    import torch

    src = Path(mortal_src) if mortal_src else Path(__file__).resolve().parents[3] / "vendor" / "Mortal" / "mortal"
    if not (src / "model.py").exists():
        raise EngineUnavailable(f"找不到 Mortal 的 Python 源码: {src}")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from model import DQN, Brain  # type: ignore[import-not-found]

    state = torch.load(state_file, weights_only=True, map_location="cpu")
    cfg = state["config"]
    version = cfg["control"].get("version", 1)
    num_blocks = cfg["resnet"]["num_blocks"]
    conv_channels = cfg["resnet"]["conv_channels"]

    brain = Brain(version=version, num_blocks=num_blocks, conv_channels=conv_channels).eval()
    dqn = DQN(version=version).eval()
    brain.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])

    if "tag" in state:
        tag = state["tag"]
    else:
        stamp = datetime.fromtimestamp(state["timestamp"], tz=timezone.utc).strftime("%y%m%d%H")
        tag = f"mortal{version}-b{num_blocks}c{conv_channels}-t{stamp}"

    return MortalWeights(
        brain=brain, dqn=dqn, version=version, device=device,
        tag=tag, steps=state.get("steps"), torch_version=torch.__version__,
    )


def load_mortal_engine(
    state_file: str | Path,
    *,
    device: str = "cpu",
    mortal_src: str | Path | None = None,
    enable_amp: bool = False,
):
    """从 checkpoint 造一个 greedy ``MortalEngine``。返回 ``(engine, tag)``。"""
    w = load_weights(state_file, device=device, mortal_src=mortal_src)
    engine = w.make_engine(enable_amp=enable_amp)
    full_tag = f"{w.tag}|steps={w.steps}|device={device}|amp={enable_amp}|torch={w.torch_version}"
    return engine, full_tag


@dataclass
class MortalReplayEngine:
    """把 libriichi 的 ``KyokuReplay`` 适配成 driver 认的 :class:`ReplayEngine`。

    四家共用同一个引擎实例 —— 权重相同,而且 libriichi 会把四家的观测打成一个
    batch 走一次前向,比开四个进程快得多。
    """

    state_file: str | Path
    device: str = "cpu"
    mortal_src: str | Path | None = None
    enable_amp: bool = False

    def __post_init__(self) -> None:
        libriichi = _import_libriichi()
        engine, tag = load_mortal_engine(
            self.state_file,
            device=self.device,
            mortal_src=self.mortal_src,
            enable_amp=self.enable_amp,
        )
        self._runner = libriichi.arena.KyokuReplay(engine)
        self.determinism_tag = f"{tag}|libriichi={libriichi.__version__}/{libriichi.__profile__}"

    def play_hand(self, setup: HandSetup) -> HandOutcome:
        outcome = self._run_raw(setup.hand, setup.scores, setup.riichi_sticks)
        return to_hand_outcome(outcome, setup)

    def _run_raw(self, hand: Hand, scores, kyotaku: int):
        wall = split_wall(hand.paishan, hand.oya)
        return self._runner.run(
            haipai=[list(h) for h in wall.haipai],
            yama=list(wall.yama),
            rinshan=list(wall.rinshan),
            dora_indicators=list(wall.dora_indicators),
            ura_indicators=list(wall.ura_indicators),
            kyoku=hand.chang * 4 + hand.ju,  # libriichi 用 0..7 连续局号
            honba=hand.ben,
            kyotaku=kyotaku,
            scores=list(scores),
        )

    def close(self) -> None:
        self._runner = None


def to_hand_outcome(outcome, setup: HandSetup) -> HandOutcome:
    """``KyokuOutcome`` → :class:`HandOutcome`。

    分工见 :mod:`dareda.rules`:libriichi 已经把本场棒和立直棒算进 deltas 了
    (它拿到了 honba 和 kyotaku),所以这里**不能**再让 rules.settle 叠一次。
    把结果原样交出去,并把 riichi_declarations 留空 —— 立直扣分同样已含在内。
    """
    deltas = tuple(int(d) for d in outcome.deltas)
    stick_delta = (outcome.kyotaku_left - setup.riichi_sticks) * 1000
    if sum(deltas) + stick_delta != 0:
        raise RuntimeError(
            f"{setup.hand.label} 点数不守恒: deltas={deltas} 供托 {setup.riichi_sticks}→{outcome.kyotaku_left}"
        )

    kind, winners, loser = _classify(outcome)
    return HandOutcome(
        outcome=kind,
        base_deltas=deltas,
        winners=winners,
        loser=loser,
        riichi_declarations=(),
        pre_settled=True,
        kyotaku_after=int(outcome.kyotaku_left),
        detail={
            "can_renchan": bool(outcome.can_renchan),
            "mjai_log": list(outcome.mjai_log),
        },
    )


def _classify(outcome) -> tuple[Outcome, tuple[int, ...], int | None]:
    """从 mjai 日志认出和了形态。

    ``KyokuOutcome`` 只给 ``has_hora`` 布尔量,分不出荣和与自摸,而 §6 的分歧点
    分析要用。mjai 的 ``hora`` 事件带 ``actor``/``target``,两者相等即自摸。
    多家荣和会有多个 hora 事件。
    """
    import json

    if not outcome.has_hora:
        return (
            (Outcome.ABORTIVE if outcome.has_abortive_ryukyoku else Outcome.RYUUKYOKU),
            (),
            None,
        )

    winners: list[int] = []
    target: int | None = None
    for line in outcome.mjai_log:
        try:
            ev = json.loads(line)
        except (ValueError, TypeError):
            continue
        if ev.get("type") == "hora":
            winners.append(int(ev["actor"]))
            target = int(ev["target"])

    if not winners:  # 日志格式变了,退回按点数正负判断
        return Outcome.RON, tuple(i for i, d in enumerate(outcome.deltas) if d > 0), None
    if target is not None and target in winners:
        return Outcome.TSUMO, tuple(winners), None
    return Outcome.RON, tuple(winners), target

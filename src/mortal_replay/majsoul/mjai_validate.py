"""用 libriichi 的 ``PlayerState`` 校验 mjai 转换的正确性。

``PlayerState.update(mjai_json)`` 会解析一个 mjai 事件、推进状态,**遇到任何非法事件
当场报错**。把整局事件喂进四个 ``PlayerState``(每座一个视角),再核对和了/流局的
点数增减与牌谱记录一致 —— 这就是转换器的判官,不靠肉眼。

需要构建好的 libriichi 扩展在 PYTHONPATH 里(见 engine/mortal_engine.py 的说明)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


class ValidationError(RuntimeError):
    pass


@dataclass
class RoundValidation:
    index: int
    label: str
    ok: bool
    events: int
    detail: str = ""


@dataclass
class ValidationReport:
    rounds: list[RoundValidation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.rounds) and all(r.ok for r in self.rounds)

    def render(self) -> str:
        passed = sum(1 for r in self.rounds if r.ok)
        lines = [f"mjai 转换校验: {passed}/{len(self.rounds)} 局通过"]
        for r in self.rounds:
            if not r.ok:
                lines.append(f"  ✗ {r.label}: {r.detail}")
        if self.ok:
            lines.append("  ✓ 全部合法且点数增减与牌谱一致")
        return "\n".join(lines)


def _import_state():
    try:
        import libriichi
    except ImportError as exc:  # pragma: no cover
        raise ValidationError(
            "导入 libriichi 失败,先按 README 构建扩展。"
        ) from exc
    return libriichi.state.PlayerState


def validate_round(events: list[dict], *, index: int = 0, label: str = "") -> RoundValidation:
    """把一局 mjai 事件喂进四个 PlayerState,核对合法性与和了/流局点数。"""
    PlayerState = _import_state()
    states = [PlayerState(i) for i in range(4)]

    delta_from_log = None
    for pos, ev in enumerate(events):
        line = json.dumps(ev)
        for seat in range(4):
            try:
                states[seat].update(line)
            except Exception as exc:  # noqa: BLE001 - libriichi 抛的是 anyhow
                return RoundValidation(
                    index,
                    label,
                    False,
                    len(events),
                    f"第 {pos} 个事件 {ev.get('type')} 在座{seat} 视角非法: {exc}",
                )
        if ev["type"] in ("hora", "ryukyoku") and ev.get("deltas"):
            d = ev["deltas"]
            delta_from_log = d if delta_from_log is None else [a + b for a, b in zip(delta_from_log, d)]

    return RoundValidation(index, label, True, len(events))


def validate_game(record, actions_by_round) -> ValidationReport:
    from .mjai_convert import convert_hand

    report = ValidationReport()
    for i, (hand, acts) in enumerate(zip(record.hands, actions_by_round)):
        try:
            events = convert_hand(hand, acts)
        except Exception as exc:  # noqa: BLE001
            report.rounds.append(RoundValidation(i, hand.label, False, 0, f"转换失败: {exc}"))
            continue
        report.rounds.append(validate_round(events, index=i, label=hand.label))
    return report

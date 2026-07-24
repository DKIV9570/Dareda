"""里程碑 3 冒烟测试:在真牌谱的牌山上跑完一局。

用一个"总是选第一个合法动作"的假引擎,验证的是**注入通路**本身:
牌山切分对不对、方向摆对没有、libriichi 能不能正常打完一局并给出合法终局。
不验证棋力 —— 那要等接上 Mortal 权重。

    python scripts/smoke_kyoku.py record.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dareda.deal import split_wall  # noqa: E402
from dareda.majsoul.parse import parse_record  # noqa: E402

import libriichi  # noqa: E402

ACTION_SPACE = libriichi.consts.ACTION_SPACE


class FirstLegalEngine:
    """恒选第一个合法动作。libriichi 要求的是 Mortal 那套 react_batch 接口。"""

    engine_type = "mortal"
    name = "first-legal"
    is_oracle = False
    version = 4
    enable_quick_eval = False
    enable_rule_based_agari_guard = False

    def react_batch(self, states, masks, invisible_states):
        actions, q_values, masks_out, is_greedy = [], [], [], []
        for mask in masks:
            mask = np.asarray(mask, dtype=bool)
            legal = np.flatnonzero(mask)
            actions.append(int(legal[0]) if legal.size else 0)
            q_values.append(np.zeros(ACTION_SPACE, dtype=np.float32))
            masks_out.append(mask)
            is_greedy.append(True)
        return actions, q_values, masks_out, is_greedy


def main(path: str) -> int:
    record = parse_record(json.loads(Path(path).read_text(encoding="utf-8")))
    runner = libriichi.arena.KyokuReplay(FirstLegalEngine())

    print(f"牌谱 {record.source}  K={record.K}\n")
    ok = 0
    for i, hand in enumerate(record.hands):
        setup = split_wall(hand.paishan, hand.oya)
        kyoku = hand.chang * 4 + hand.ju  # libriichi 用 0..7 的连续局号
        try:
            out = runner.run(
                haipai=[list(h) for h in setup.haipai],
                yama=list(setup.yama),
                rinshan=list(setup.rinshan),
                dora_indicators=list(setup.dora_indicators),
                ura_indicators=list(setup.ura_indicators),
                kyoku=kyoku,
                honba=hand.ben,
                kyotaku=0,
                scores=list(hand.scores),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {hand.label:<9} {type(exc).__name__}: {exc}")
            continue

        end = "和了" if out.has_hora else ("途中流局" if out.has_abortive_ryukyoku else "流局")
        conserved = sum(out.deltas) + out.kyotaku_left * 1000 == 0
        print(
            f"  {'✓' if conserved else '✗'} {hand.label:<9} {end:<5} "
            f"deltas={list(out.deltas)}  供托={out.kyotaku_left}  事件={len(out.mjai_log)}"
        )
        ok += conserved

    print(f"\n{ok}/{record.K} 局打完且点数守恒")
    return 0 if ok == record.K else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "record.json"))

"""命令行入口。

    mortal-replay synth  --out record.json     # 造一份合成牌谱
    mortal-replay verify --record record.json  # §5 配牌恒等断言(准入关卡)
    mortal-replay inspect --record record.json # 看序列
    mortal-replay link "https://game.maj-soul.com/1/?paipu=..."  # 解析牌谱链接
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .majsoul.fetch import parse_paipu_link
from .majsoul.parse import load_record
from .majsoul.synth import synth_record
from .verify import infer_convention, verify_record


def _cmd_synth(args) -> int:
    data = synth_record(seed=args.seed, k=args.hands)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"已写出 {args.out}({len(data['hands'])} 局,seed={args.seed})")
    else:
        print(text)
    return 0


def _cmd_verify(args) -> int:
    record = load_record(args.record)
    print(f"牌谱: {record.source}  K = {record.K}")
    report = verify_record(record)
    print(report.render())

    # 王牌区(岭上/宝牌/里宝)—— 需要动作流,只有原始导出才有
    raw = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and raw.get("mjslog"):
        from .verify import split_actions_by_round, verify_dead_wall

        dw = verify_dead_wall(record, split_actions_by_round(raw))
        print()
        print(dw.render())
    if not report.ok:
        other = infer_convention(record)
        if other is not None:
            print(f"\n提示:换成 {other.value} 约定可以全部通过 —— 默认约定选错了。")
        else:
            print("\n所有牌山约定都撞不上,问题在更底层(编解码 / 发牌顺序 / 数据本身)。")
        return 1
    if record.meta.get("synthetic"):
        print("\n⚠ 这是合成数据:只证明了实现自洽,证明不了牌山约定。用真牌谱再跑一次。")
    return 0


def _cmd_inspect(args) -> int:
    record = load_record(args.record)
    print(f"牌谱: {record.source}")
    if record.player_names:
        print("玩家: " + " / ".join(f"座{i} {n}" for i, n in enumerate(record.player_names)))
    if record.final_scores:
        from .rules import placements

        ranks = placements(record.final_scores)
        print(
            "终局: "
            + " / ".join(f"{s}({ranks[i]}位)" for i, s in enumerate(record.final_scores))
        )
    print(f"序列 (K={record.K}): {record.describe_sequence()}")
    for h in record.hands:
        print(f"  {h.label:<8} 庄=座{h.oya}  本场={h.ben}  立直棒={h.liqibang}  点数={list(h.scores)}")
    return 0


def _cmd_decode_capture(args) -> int:
    from .majsoul.wscapture import CaptureError, decode_capture_file

    try:
        out, report = decode_capture_file(args.capture, uuid=args.uuid)
    except CaptureError as exc:
        print(f"解码失败:\n{exc}")
        return 1
    print(report.render())
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"\n已写出 {args.out}")
    if report.new_rounds:
        print(f"下一步: mortal-replay verify --record {args.out}")
    return 0 if report.new_rounds else 1


def _cmd_replay(args) -> int:
    from .driver import comparison_table, per_hand_table, run_replay
    from .engine.mortal_engine import EngineUnavailable, MortalReplayEngine

    record = load_record(args.record)
    try:
        engine = MortalReplayEngine(
            state_file=args.model, device=args.device, mortal_src=args.mortal_src
        )
    except EngineUnavailable as exc:
        print(f"引擎不可用:\n{exc}")
        return 1

    print(f"牌谱 {record.source}  K={record.K}")
    print(f"引擎 {engine.determinism_tag}\n")
    result = run_replay(record, engine, determinism_tag=engine.determinism_tag)
    print(comparison_table(result))
    print()
    print(per_hand_table(result))

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "record": record.source,
                    "determinism_tag": engine.determinism_tag,
                    "human_final_scores": record.final_scores,
                    "replay_final_scores": list(result.final_scores),
                    "hands_played": result.hands_played,
                    "stop_reason": result.stop_reason.value,
                    "per_hand": [
                        {
                            "label": log.label,
                            "outcome": log.outcome.outcome.value,
                            "deltas": list(log.settlement.deltas),
                            "scores_after": list(log.settlement.scores_after),
                        }
                        for log in result.logs
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n已写出 {args.out}")
    return 0


def _cmd_counterfactual(args) -> int:
    from .driver import comparison_table, per_hand_table, run_replay
    from .engine.counterfactual import CounterfactualReplayEngine
    from .engine.mortal_engine import EngineUnavailable
    from .verify import split_actions_by_round

    raw = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if not (isinstance(raw, dict) and raw.get("mjslog")):
        print("反事实 replay 需要含动作流的牌谱(抓包解出来的那种),当前文件没有 mjslog。")
        return 1
    record = load_record(args.record)
    actions = split_actions_by_round(raw)

    try:
        engine = CounterfactualReplayEngine(
            record, actions, args.hero, state_file=args.model,
            device=args.device, mortal_src=args.mortal_src,
        )
    except EngineUnavailable as exc:
        print(f"引擎不可用:\n{exc}")
        return 1

    print(f"牌谱 {record.source}  K={record.K}")
    if record.player_names:
        print(f"英雄座 {args.hero} = {record.player_names[args.hero]}")
    print(f"引擎 {engine.determinism_tag}\n")
    result = run_replay(record, engine, determinism_tag=engine.determinism_tag)
    print(comparison_table(result))
    print()
    print(engine.fidelity_table())
    print()
    print(per_hand_table(result))
    return 0


def _cmd_montecarlo(args) -> int:
    import sys as _sys

    from .analysis.calibrate import BoltzmannParams, calibrate
    from .analysis.strength import measure_strength, render_strength
    from .engine.mortal_engine import EngineUnavailable, load_weights
    from .majsoul.mjai_convert import convert_hand
    from .montecarlo import CounterfactualMonteCarlo
    from .verify import split_actions_by_round

    raw = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if not (isinstance(raw, dict) and raw.get("mjslog")):
        print("蒙特卡洛需要含动作流的牌谱(抓包解出来的),当前文件没有 mjslog。")
        return 1
    record = load_record(args.record)
    actions = split_actions_by_round(raw)
    humans = [convert_hand(h, a) for h, a in zip(record.hands, actions)]

    if args.mortal_src:
        _sys.path.insert(0, args.mortal_src)
    try:
        weights = load_weights(args.model, device=args.device, mortal_src=args.mortal_src)
    except EngineUnavailable as exc:
        print(f"引擎不可用:\n{exc}")
        return 1

    greedy = weights.make_engine()
    print(f"牌谱 {record.source}  hero=座{args.hero}"
          + (f"({record.player_names[args.hero]})" if record.player_names else ""))
    print("测对手强度(在人类原局上)...", flush=True)
    strengths = measure_strength(record, humans, greedy)
    print(render_strength(strengths, record.player_names))

    # 各强度档:calibrated=真实强度;full=对手也 greedy(最强);weak=EV loss 翻倍(更弱)
    levels = {"calibrated": 1.0}
    if args.sensitivity:
        levels = {"full-mortal": 0.0, "calibrated": 1.0, "weaker": 2.0}

    for name, mult in levels.items():
        params = {
            s: (BoltzmannParams(0.0, 1.0) if mult == 0.0
                else calibrate(strengths[s].q_samples, strengths[s].ev_loss * mult))
            for s in range(4) if s != args.hero
        }
        temps = {s: round(params[s].temp, 2) for s in params}
        print(f"\n=== 强度档 [{name}] 对手温度 {temps} ===", flush=True)
        mc = CounterfactualMonteCarlo(record, actions, args.hero, weights, params, base_seed=args.seed)
        done = [0]

        def prog(i, total, res):
            done[0] = i
            print(f"\r  轨迹 {i}/{total}", end="", flush=True)

        dist = mc.run(args.trials, progress=prog)
        print()
        print(dist.render(f"座{args.hero} @ {name}"))
    return 0


def _cmd_selfluck(args) -> int:
    import sys as _sys

    from .analysis.calibrate import calibrate
    from .analysis.strength import measure_strength, render_strength
    from .engine.mortal_engine import EngineUnavailable, load_weights
    from .majsoul.mjai_convert import convert_hand
    from .montecarlo import SelfStrengthMonteCarlo, luck_verdict
    from .rules import placements
    from .verify import split_actions_by_round

    raw = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if not (isinstance(raw, dict) and raw.get("mjslog")):
        print("需要含动作流的牌谱(抓包解出来的)。")
        return 1
    record = load_record(args.record)
    actions = split_actions_by_round(raw)
    humans = [convert_hand(h, a) for h, a in zip(record.hands, actions)]

    if args.mortal_src:
        _sys.path.insert(0, args.mortal_src)
    try:
        weights = load_weights(args.model, device=args.device, mortal_src=args.mortal_src)
    except EngineUnavailable as exc:
        print(f"引擎不可用:\n{exc}")
        return 1

    print(f"牌谱 {record.source}  hero=座{args.hero}"
          + (f"({record.player_names[args.hero]})" if record.player_names else ""))
    print("测四家强度...", flush=True)
    strengths = measure_strength(record, humans, weights.make_engine())
    print(render_strength(strengths, record.player_names))
    params = {s: calibrate(strengths[s].q_samples, strengths[s].ev_loss) for s in range(4)}
    print("标定温度:", {s: round(params[s].temp, 2) for s in range(4)})

    mc = SelfStrengthMonteCarlo(record, params, weights, base_seed=args.seed)

    def prog(i, total, res):
        print(f"\r  轨迹 {i}/{total}", end="", flush=True)

    print(f"\n全员按各自水平重打 {args.trials} 次(固定牌山)...", flush=True)
    dists = mc.run_all(args.trials, progress=prog)  # 一次跑完,四家都拿到
    print()

    actual_places = placements(record.final_scores)
    names = record.player_names or ("",) * 4

    # 四家总览:强度 vs 这副牌上的实际期望 —— 直接看出"是牌/座位的锅还是水平的锅"
    print(f"{'座':<3}{'玩家':<12}{'EV loss':>8}{'实际':>6}{'同水平期望':>10}"
          f"{'1位':>7}{'2位':>7}{'3位':>7}{'4位':>7}")
    for s in range(4):
        d = dists[s]
        pct = [d.counts.get(p, 0) / d.n * 100 if d.n else 0 for p in (1, 2, 3, 4)]
        mark = " ←你" if s == args.hero else ""
        print(
            f"{s:<3}{names[s]:<12}{strengths[s].ev_loss:>8.3f}"
            f"{actual_places[s]:>5}位{d.avg_placement:>9.2f}"
            + "".join(f"{p:>6.0f}%" for p in pct) + mark
        )

    print()
    print(dists[args.hero].render(f"座{args.hero} 同水平自打分布"))
    print()
    print(luck_verdict(dists[args.hero], actual_places[args.hero]))
    return 0


def _cmd_demo(args) -> int:
    """用假引擎跑一遍 driver,看 §6 输出长什么样。**不是 replay 结果。**"""
    import random

    from .driver import comparison_table, per_hand_table, run_replay
    from .engine.base import ScriptedEngine
    from .rules import HandOutcome, Outcome

    record = load_record(args.record)
    rng = random.Random(args.seed)
    outcomes = []
    for _ in record.hands:
        winner, loser = rng.sample(range(4), 2)
        pts = rng.choice([1000, 2600, 5200, 8000])
        deltas = [0] * 4
        deltas[winner], deltas[loser] = pts, -pts
        outcomes.append(
            HandOutcome(Outcome.RON, tuple(deltas), winners=(winner,), loser=loser)
        )

    result = run_replay(record, ScriptedEngine(outcomes), determinism_tag="fake-engine")
    print("⚠ 引擎是随机假货(libriichi 未接),下面的数字只用来看管道和排版\n")
    print(comparison_table(result))
    print()
    print(per_hand_table(result))
    return 0


def _cmd_link(args) -> int:
    ref = parse_paipu_link(args.link)
    print(f"uuid       : {ref.uuid}")
    print(f"share_code : {ref.share_code if ref.share_code is not None else '—'}  (混淆过的分享码,不是 account_id)")
    print("\n联网拉取尚未实现(见 majsoul/fetch.py 的 MajsoulApiFetcher)。")
    print("现在请用 tools/majsoul-ws-capture.user.js 抓包,再跑 decode-capture。")
    return 0


def _force_utf8_stdio() -> None:
    """Windows 控制台默认 cp1252/936,输出中文会炸。这里强制成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(prog="mortal-replay", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("synth", help="生成合成牌谱")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--hands", type=int, default=10, help="小局数 K")
    p.add_argument("--out")
    p.set_defaults(func=_cmd_synth)

    p = sub.add_parser("decode-capture", help="WebSocket 抓包 → 牌谱 JSON")
    p.add_argument("--capture", required=True, help="majsoul-ws-*.json")
    p.add_argument("--out", default="record.json")
    p.add_argument("--uuid", help="抓包含多局时,指定要哪一局(前缀匹配)")
    p.set_defaults(func=_cmd_decode_capture)

    p = sub.add_parser("verify", help="§5 配牌恒等断言")
    p.add_argument("--record", required=True)
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("inspect", help="查看牌谱序列")
    p.add_argument("--record", required=True)
    p.set_defaults(func=_cmd_inspect)

    p = sub.add_parser("replay", help="用 Mortal 在原牌山上重打全序列")
    p.add_argument("--record", required=True)
    p.add_argument("--model", default="models/mortal_298k.pth")
    p.add_argument("--device", default="cpu", help="cpu 或 cuda:0。换 device 会改变确定性标签")
    p.add_argument("--mortal-src", help="Mortal 的 Python 源码目录,默认 vendor/Mortal/mortal")
    p.add_argument("--out", help="把结果写成 JSON")
    p.set_defaults(func=_cmd_replay)

    p = sub.add_parser("counterfactual", help="英雄座换 Mortal,对手照人类原样打")
    p.add_argument("--record", required=True, help="含动作流的牌谱(抓包解出来的)")
    p.add_argument("--hero", type=int, required=True, help="换成 Mortal 的座次 0..3")
    p.add_argument("--model", default="models/mortal_298k.pth")
    p.add_argument("--device", default="cpu")
    p.add_argument("--mortal-src")
    p.set_defaults(func=_cmd_counterfactual)

    p = sub.add_parser("montecarlo", help="hero 换 Mortal、对手按标定强度,跑 N 轨迹名次分布")
    p.add_argument("--record", required=True, help="含动作流的牌谱")
    p.add_argument("--hero", type=int, required=True)
    p.add_argument("--trials", type=int, default=20)
    p.add_argument("--sensitivity", action="store_true", help="额外跑 full-mortal / weaker 两档")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--model", default="models/mortal_298k.pth")
    p.add_argument("--device", default="cpu")
    p.add_argument("--mortal-src")
    p.set_defaults(func=_cmd_montecarlo)

    p = sub.add_parser("self-luck", help="全员按各自水平重打,看这局对你是运气好/差")
    p.add_argument("--record", required=True, help="含动作流的牌谱")
    p.add_argument("--hero", type=int, required=True)
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--model", default="models/mortal_298k.pth")
    p.add_argument("--device", default="cpu")
    p.add_argument("--mortal-src")
    p.set_defaults(func=_cmd_selfluck)

    p = sub.add_parser("demo", help="用假引擎跑 driver,预览 §6 输出")
    p.add_argument("--record", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=_cmd_demo)

    p = sub.add_parser("link", help="解析牌谱链接")
    p.add_argument("link")
    p.set_defaults(func=_cmd_link)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

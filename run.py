"""一键分析:找到牌谱 → 解码 → 自检 → 选座 → 出「这把怪谁」结论。

不用记命令。双击 run.cmd(Windows)或 run.sh(Linux/macOS)就能跑;它会:

1. 自动找最新的抓包文件(优先 Downloads 和当前目录里的 majsoul-ws-*.json),
   或用已解好的 record.json,或用你拖进来 / 命令行给的文件;
2. 解码成牌谱并跑配牌恒等自检;
3. 列出四家,让你选自己是几号座;
4. 跑 diagnose,给出牌 / 打法 / 运气的三项分解。

也可以直接 `python run.py 某文件.json`。
"""

from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path


def _newest(patterns, dirs):
    cands = []
    for d in dirs:
        for pat in patterns:
            cands += glob.glob(str(Path(d) / pat))
    cands = [c for c in cands if os.path.isfile(c)]
    return max(cands, key=os.path.getmtime) if cands else None


def _kind(path: Path) -> str:
    """看一眼文件是抓包(capture)还是已解好的牌谱(record),还是都不是。"""
    try:
        head = path.read_text(encoding="utf-8")[:4000]
    except OSError:
        return "unknown"
    if '"frames"' in head:
        return "capture"
    if '"mjslog"' in head:
        return "record"
    return "unknown"


def _pick_input(argv) -> Path | None:
    if len(argv) > 1 and Path(argv[1]).is_file():
        return Path(argv[1])
    here = Path.cwd()
    downloads = Path.home() / "Downloads"
    cap = _newest(["majsoul-ws-*.json"], [downloads, here])
    if cap:
        return Path(cap)
    rec = here / "record.json"
    if rec.is_file():
        return rec
    return None


def _fail(msg: str) -> int:
    print("\n[×] " + msg)
    return 1


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv
    try:
        from dareda import cli
    except ImportError:
        return _fail("导入 dareda 失败。先跑安装脚本 install.ps1 / install.sh,并确认在虚拟环境里。")

    # libriichi 没构建好的话,早点给出有用的提示
    try:
        import libriichi  # noqa: F401
    except ImportError:
        return _fail(
            "找不到麻将引擎 libriichi。八成是没编译或没设 PYTHONPATH。\n"
            "    请用 install.ps1 / install.sh 安装;用 run.cmd / run.sh 启动会自动设好路径。"
        )

    src = _pick_input(argv)
    if src is None:
        return _fail(
            "没找到牌谱。请先按 README 用浏览器导出一份(会下到 Downloads),\n"
            "    或把文件拖到这个脚本上,或 python run.py 某文件.json。"
        )
    print(f"[输入] {src}")

    record_path = Path("record.json")
    kind = _kind(src)
    if kind == "capture":
        print("\n[1] 解码抓包...")
        if cli.main(["decode-capture", "--capture", str(src), "--out", str(record_path)]) != 0:
            return _fail("解码失败,见上方信息。")
    elif kind == "record":
        record_path = src
    else:
        return _fail(f"认不出这个文件({src.name})。要么是抓包 majsoul-ws-*.json,要么是解好的 record.json。")

    print("\n[2] 自检牌山...")
    if cli.main(["verify", "--record", str(record_path)]) != 0:
        return _fail("配牌恒等自检没过 —— 牌山没取对,后面分析没意义。多半是抓包没抓全,重导一次。")

    # 列出四家,让用户选座
    print("\n[3] 这局的玩家:")
    record = cli.load_record(str(record_path))
    from dareda.rules import placements

    names = record.player_names or ("",) * 4
    places = placements(record.final_scores) if record.final_scores else [0] * 4
    for s in range(4):
        pt = f"{record.final_scores[s]}({places[s]}位)" if record.final_scores else ""
        print(f"    座{s}  {names[s] or '(无名)':<16} {pt}")

    hero = _ask_seat()
    if hero is None:
        return _fail("没选座位,退出。")

    trials = int(os.environ.get("DAREDA_TRIALS", "20"))
    print(f"\n[4] 开始分析(每条基线跑 {trials} 次,约十分钟,请耐心等)...\n")
    return cli.main(
        ["diagnose", "--record", str(record_path), "--hero", str(hero), "--trials", str(trials)]
    )


def _ask_seat():
    try:
        raw = input("\n你是几号座?输入 0-3(看上面哪个昵称是你): ").strip()
    except EOFError:
        return None
    if raw in {"0", "1", "2", "3"}:
        return int(raw)
    print("  只能是 0/1/2/3。")
    return _ask_seat() if sys.stdin.isatty() else None


if __name__ == "__main__":
    code = main()
    # 双击运行时,留住窗口让用户看到结果
    if sys.stdin.isatty():
        try:
            input("\n按回车键关闭。")
        except EOFError:
            pass
    sys.exit(code)

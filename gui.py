"""誰だ 图形界面 —— 选牌谱、选座、看「这把怪谁」。

Tkinter(Python 自带,不加依赖)。用 gui.cmd(Windows)/ gui.sh(Linux/macOS)启动,
它们会设好虚拟环境和 PYTHONPATH。

两条要命的工程约束:

* **分析要跑几分钟且内部开多进程**,绝不能在 GUI 线程里跑,否则窗口卡死。所以分析在
  后台线程里跑,进度通过线程安全的队列回传,主线程用 ``after`` 轮询刷新。
* **多进程 spawn 会重新 import 本模块**。所以模块顶层**绝不能建 Tk 窗口或跑分析** ——
  一切都在 ``if __name__ == "__main__"`` 之下 / 函数之内,否则每个 worker 都会弹一个
  窗口(spawn 炸弹)。
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

# 深色主题(和仓库 banner 一套)
BG = "#1a1a19"
FG = "#ffffff"
MUTED = "#9a998f"
ACCENT = "#3987e5"
BAD = "#e66767"
CARD = "#26261f"


class DaredaGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.record = None
        self.record_path = None
        self.q: queue.Queue = queue.Queue()
        self.model = "models/mortal_298k.pth"

        root.title("誰だ / dareda —— 这把怪谁")
        root.configure(bg=BG)
        root.geometry("640x680")
        root.minsize(560, 620)

        self._build()

    # ---------------------------------------------------------------- 布局
    def _build(self):
        tk.Label(self.root, text="這把怪誰?", bg=BG, fg=ACCENT,
                 font=("Microsoft YaHei", 20, "bold")).pack(pady=(10, 2))
        tk.Label(self.root, text="在原牌山上重打几十遍,看牌、打法、运气各占多少锅",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei", 10)).pack()

        # 1. 选文件
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=24, pady=(12, 4))
        self.file_lbl = tk.Label(row, text="① 还没选牌谱", bg=BG, fg=FG, anchor="w",
                                 font=("Microsoft YaHei", 10))
        self.file_lbl.pack(side="left", fill="x", expand=True)
        tk.Button(row, text="选牌谱 / 抓包文件", command=self._pick,
                  bg=CARD, fg=FG, relief="flat", padx=10).pack(side="right")

        # 2. 选座
        self.seat_frame = tk.LabelFrame(self.root, text=" ② 你是哪一家 ",
                                        bg=BG, fg=MUTED, font=("Microsoft YaHei", 10))
        self.seat_frame.pack(fill="x", padx=24, pady=6)
        self.seat_var = tk.IntVar(value=-1)
        self.seat_hint = tk.Label(self.seat_frame, text="选好牌谱后这里会列出四家",
                                  bg=BG, fg=MUTED, font=("Microsoft YaHei", 9))
        self.seat_hint.pack(anchor="w", padx=8, pady=6)

        # 3. 跑
        run_row = tk.Frame(self.root, bg=BG)
        run_row.pack(fill="x", padx=24, pady=(4, 6))
        self.run_btn = tk.Button(run_row, text="③ 开始分析", command=self._start,
                                 bg=ACCENT, fg="#ffffff", relief="flat",
                                 font=("Microsoft YaHei", 11, "bold"), state="disabled",
                                 padx=16, pady=4)
        self.run_btn.pack(side="left")
        tk.Label(run_row, text="次数", bg=BG, fg=MUTED).pack(side="left", padx=(14, 2))
        self.trials = tk.IntVar(value=20)
        ttk.Combobox(run_row, textvariable=self.trials, width=5, state="readonly",
                     values=(10, 20, 30, 50)).pack(side="left")

        self.prog = ttk.Progressbar(self.root, mode="determinate")
        self.prog.pack(fill="x", padx=24, pady=(2, 2))
        self.status = tk.Label(self.root, text="", bg=BG, fg=MUTED,
                               font=("Microsoft YaHei", 9))
        self.status.pack()

        # 4. 结果
        self.result = tk.Text(self.root, bg=CARD, fg=FG, relief="flat", height=12,
                              font=("Consolas", 11), padx=14, pady=12, wrap="word")
        self.result.pack(fill="both", expand=True, padx=24, pady=(6, 14))
        self.result.tag_config("good", foreground=ACCENT)
        self.result.tag_config("bad", foreground=BAD)
        self.result.tag_config("muted", foreground=MUTED)
        self.result.configure(state="disabled")

    # ---------------------------------------------------------------- 选文件
    def _pick(self):
        # 默认打开 Downloads,那是抓包文件的落点
        init = str(Path.home() / "Downloads")
        path = filedialog.askopenfilename(
            title="选牌谱或抓包文件", initialdir=init,
            filetypes=[("牌谱 / 抓包", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self._load(Path(path))

    def _load(self, path: Path):
        self._set_status(f"读取 {path.name} ...")
        try:
            from dareda import cli
            import json

            head = path.read_text(encoding="utf-8")[:4000]
            if '"frames"' in head:  # 抓包 → 先解码
                out = path.with_name("record.json")
                if cli.main(["decode-capture", "--capture", str(path), "--out", str(out)]) != 0:
                    self._set_status("解码失败,可能抓包没抓全,重导一次。")
                    return
                path = out
            record = cli.load_record(str(path))
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"读取失败:{exc}")
            return

        self.record = record
        self.record_path = path
        self.file_lbl.config(text=f"① {path.name}  ({record.K} 小局)")
        self._show_seats()
        self._set_status("选好座位,点开始分析。")

    def _show_seats(self):
        for w in self.seat_frame.winfo_children():
            w.destroy()
        from dareda.rules import placements

        names = self.record.player_names or ("",) * 4
        places = placements(self.record.final_scores) if self.record.final_scores else [0] * 4
        for s in range(4):
            pt = ""
            if self.record.final_scores:
                pt = f"   {self.record.final_scores[s]}({places[s]}位)"
            tk.Radiobutton(
                self.seat_frame, variable=self.seat_var, value=s,
                text=f"座{s}   {names[s] or '(无名)'}{pt}",
                bg=BG, fg=FG, selectcolor=CARD, activebackground=BG, activeforeground=ACCENT,
                font=("Microsoft YaHei", 10), anchor="w", command=self._maybe_enable,
            ).pack(anchor="w", padx=8, pady=1)

    def _maybe_enable(self):
        if self.record is not None and self.seat_var.get() in (0, 1, 2, 3):
            self.run_btn.config(state="normal")

    # ---------------------------------------------------------------- 跑分析
    def _start(self):
        hero = self.seat_var.get()
        if self.record is None or hero not in (0, 1, 2, 3):
            return
        self.run_btn.config(state="disabled")
        self._set_result("")
        self.prog.config(mode="indeterminate")
        self.prog.start(12)
        self._set_status("加载引擎、测四家强度...")

        t = threading.Thread(target=self._worker, args=(hero, int(self.trials.get())), daemon=True)
        t.start()
        self.root.after(100, self._poll)

    def _worker(self, hero, trials):
        """后台线程:跑 run_diagnose,进度塞进队列。"""
        try:
            from dareda.analysis.diagnose import run_diagnose
            from dareda.engine.mortal_engine import load_weights
            from dareda.majsoul.mjai_convert import convert_hand
            from dareda.verify import split_actions_by_round
            import json

            raw = json.loads(self.record_path.read_text(encoding="utf-8"))
            actions = split_actions_by_round(raw)
            humans = [convert_hand(h, a) for h, a in zip(self.record.hands, actions)]
            weights = load_weights(self.model, device="cpu")

            def prog(phase, done, total):
                self.q.put(("progress", phase, done, total))

            dx = run_diagnose(self.record, humans, hero, weights,
                              trials=trials, progress=prog)
            self.q.put(("done", dx))
        except Exception as exc:  # noqa: BLE001
            import traceback
            self.q.put(("error", f"{exc}\n{traceback.format_exc()}"))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    self._on_progress(*msg[1:])
                elif msg[0] == "done":
                    self._on_done(msg[1])
                    return
                elif msg[0] == "error":
                    self._on_error(msg[1])
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    _PHASE = {"strength": "① 测四家强度", "baseline": "② 均等水平基线", "real": "③ 真实水平"}

    def _on_progress(self, phase, done, total):
        self._set_status(self._PHASE.get(phase, phase) + (f"  {done}/{total}" if total else " ..."))
        if total:
            if self.prog["mode"] != "determinate":
                self.prog.stop()
                self.prog.config(mode="determinate", maximum=total)
            self.prog["value"] = done

    def _on_done(self, dx):
        self.prog.stop()
        self.prog.config(mode="determinate", value=self.prog["maximum"])
        self._set_status("完成。")
        self.run_btn.config(state="normal")
        names = self.record.player_names or ("",) * 4
        self._render_diagnosis(dx, names[dx.hero])

    def _on_error(self, text):
        self.prog.stop()
        self._set_status("出错了。")
        self.run_btn.config(state="normal")
        self._set_result("分析失败:\n\n" + text)

    # ---------------------------------------------------------------- 渲染
    def _render_diagnosis(self, dx, name):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")

        def line(text, tag=None):
            self.result.insert("end", text + "\n", tag or ())

        line(f"座{dx.hero} {name}", "muted")
        line("")
        line(f"牌   {_stars(dx.deal_gain)}  {dx.deal_label}")
        line(f"打   {_stars(dx.skill_gain)}  {dx.skill_label}  ({dx.skill_gain:+.2f})")
        luck_tag = "good" if dx.luck_gain > 0 else "bad"
        line(f"运   {_stars(dx.luck_gain)}  {dx.luck_label}"
             f"  (实际 {dx.actual} 位)", luck_tag)
        line("")
        line("→ " + dx.verdict(), "good" if "顺" in dx.luck_label else
             ("bad" if "背" in dx.luck_label else None))
        line("")
        line(f"牌与座次 {dx.deal_gain:+.2f}  +  打法 {dx.skill_gain:+.2f}"
             f"  +  运气 {dx.luck_gain:+.2f}  =  {2.5 - dx.actual:+.2f}", "muted")
        line("")
        quip, tag = _luck_quip(dx.luck_label)
        line(quip, tag)
        self.result.configure(state="disabled")

    def _set_status(self, text):
        self.status.config(text=text)

    def _set_result(self, text):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        self.result.configure(state="disabled")


def _stars(delta, span=0.8):
    r = max(-1.0, min(1.0, delta / span))
    filled = round((r + 1) / 2 * 5)
    return "★" * filled + "☆" * (5 - filled)


def _luck_quip(luck_label):
    """给运气判定配一句发牌姬吐槽,返回 (文案, 颜色 tag)。"""
    if "背" in luck_label:
        return "运气背 —— 牌姬搞你,开喷!", "bad"
    if "顺" in luck_label:
        return "运气顺 —— 发牌姬:无辜的喵~", "good"
    return "运气正常 —— 这把发牌姬没参与,愿赌服输", "muted"


def main():
    root = tk.Tk()
    DaredaGUI(root)
    root.mainloop()


def _selftest():
    """headless 自检:证明 gui.py 作为 __main__ 时,多进程 worker 不会弹窗
    (spawn 炸弹)。跑一次极小的并行 diagnose,能正常返回即通过。
    不建任何 Tk 窗口 —— 正是要确认 worker 重新 import 本模块时也不建窗口。"""
    import json

    from dareda.analysis.diagnose import run_diagnose
    from dareda.engine.mortal_engine import load_weights
    from dareda.majsoul.mjai_convert import convert_hand
    from dareda.majsoul.parse import load_record
    from dareda.verify import split_actions_by_round

    raw = json.loads(Path("record.json").read_text(encoding="utf-8"))
    rec = load_record("record.json")
    humans = [convert_hand(h, a) for h, a in zip(rec.hands, split_actions_by_round(raw))]
    w = load_weights("models/mortal_298k.pth", device="cpu")
    dx = run_diagnose(rec, humans, 1, w, trials=2, jobs=2)
    print("SELFTEST OK closure=%.2g verdict=%s" % (dx.check_closure(), dx.verdict()))


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()

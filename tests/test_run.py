"""一键脚本 run.py 的输入识别逻辑测试(不跑分析,只测选文件那部分)。"""

import importlib.util
import sys
from pathlib import Path

# run.py 在仓库根,不在包里,单独加载
_spec = importlib.util.spec_from_file_location(
    "dareda_run", Path(__file__).resolve().parents[1] / "run.py"
)
run = importlib.util.module_from_spec(_spec)
sys.modules["dareda_run"] = run
_spec.loader.exec_module(run)


def test_kind_detects_capture(tmp_path):
    f = tmp_path / "majsoul-ws-1.json"
    f.write_text('{"frames":[{"seq":0}]}', encoding="utf-8")
    assert run._kind(f) == "capture"


def test_kind_detects_record(tmp_path):
    f = tmp_path / "record.json"
    f.write_text('{"mjslog":[],"mjsrecordtypes":[]}', encoding="utf-8")
    assert run._kind(f) == "record"


def test_kind_rejects_unrelated_json(tmp_path):
    f = tmp_path / "x.json"
    f.write_text('{"hello":"world"}', encoding="utf-8")
    assert run._kind(f) == "unknown"


def test_newest_picks_latest_mtime(tmp_path):
    import os
    import time

    old = tmp_path / "majsoul-ws-old.json"
    old.write_text("{}", encoding="utf-8")
    new = tmp_path / "majsoul-ws-new.json"
    new.write_text("{}", encoding="utf-8")
    os.utime(old, (time.time() - 100, time.time() - 100))
    picked = run._newest(["majsoul-ws-*.json"], [tmp_path])
    assert Path(picked) == new


def test_explicit_arg_wins(tmp_path):
    f = tmp_path / "given.json"
    f.write_text("{}", encoding="utf-8")
    assert run._pick_input(["run.py", str(f)]) == f


def test_missing_input_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run.Path, "home", lambda: tmp_path)  # 空的 Downloads
    assert run._pick_input(["run.py"]) is None

"""并行进程数解析的测试(纯逻辑,无需 libriichi/权重)。

真正的"并行结果==顺序结果"等价性需要权重和构建好的 libriichi,不适合放进单测;
那条在开发时手动验过(同 seed 下两种模式的名次分布逐项相同)。
"""

from dareda.montecarlo import resolve_jobs


def test_explicit_jobs_respected():
    assert resolve_jobs(2, 100) == 2
    assert resolve_jobs(1, 100) == 1


def test_jobs_never_exceeds_trials():
    # 只有 3 条轨迹时,开 8 进程没意义
    assert resolve_jobs(8, 3) == 3


def test_jobs_floor_is_one():
    assert resolve_jobs(0, 10) == 1
    assert resolve_jobs(-5, 10) == 1


def test_auto_is_capped_and_positive(monkeypatch):
    # 自动模式:min(核数//2, 4, 轨迹数),下限 1
    monkeypatch.setattr("os.cpu_count", lambda: 16)
    assert resolve_jobs(None, 100) == 4  # 封顶 4
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    assert resolve_jobs(None, 100) == 2  # 4//2
    monkeypatch.setattr("os.cpu_count", lambda: 2)
    assert resolve_jobs(None, 100) == 1  # 2//2
    monkeypatch.setattr("os.cpu_count", lambda: 16)
    assert resolve_jobs(None, 3) == 3    # 轨迹数更小时以它为准


def test_auto_handles_unknown_cpu_count(monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: None)
    assert resolve_jobs(None, 100) >= 1

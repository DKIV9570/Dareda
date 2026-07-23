"""mjai 协议进程封装(spec §4)。

mjai 是 stdin/stdout 的 JSON lines 协议:主控每发一个事件对象(一行 JSON),bot
回一行反应。Mortal 部署形态就是这个,四个实例各起一个进程。

这里只封"进程 + 收发 + 生命周期",不含牌局逻辑 —— 牌局逻辑属于 libriichi
(见 :mod:`mortal_replay.engine.mortal_engine`)。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


class MjaiError(RuntimeError):
    pass


@dataclass
class MjaiBotProcess:
    """一个 mjai bot 子进程。

    :param command: 启动命令,例如 ``["python", "mortal/mjai.py"]``
    :param player_id: 座次 0..3,握手时告诉 bot 它是谁
    """

    command: list[str]
    player_id: int
    env: dict[str, str] | None = None
    cwd: str | None = None
    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._proc is not None:
            raise MjaiError("进程已经起了")
        self._proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=self.env,
            cwd=self.cwd,
        )

    def send(self, event: dict) -> dict:
        """发一个事件,读回一个反应。"""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise MjaiError("进程没起或管道已关")
        self._proc.stdin.write(json.dumps(event, separators=(",", ":")) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            raise MjaiError(f"bot(座{self.player_id}) 无响应就退出了。stderr:\n{stderr}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise MjaiError(f"bot(座{self.player_id}) 回了非 JSON: {line!r}") from exc

    def start_game(self) -> dict:
        return self.send({"type": "start_game", "id": self.player_id})

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
        finally:
            self._proc = None

    def __enter__(self) -> "MjaiBotProcess":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass
class MortalBotSpec:
    """怎么起一个 Mortal 实例。

    Mortal 本体是 AGPL-3.0 开源的,但**官方不公开分发训练好的权重**;可用的是
    第三方 checkpoint(如 HuggingFace ``VoidShine/mortal-298k``,ResNet 192ch/40block,
    四麻半庄)。注意那个 checkpoint 是拿天凤数据训的 —— 对雀魂牌谱正好撞上 spec
    §4.1 说的规则 mismatch,输出里要标注。

    :param determinism_tag: spec §4 要求把 build 和 device 记进输出。固定牌山 +
        greedy argmax ⇒ 唯一轨迹,但不同 device/cuDNN 下 Q 值末位会抖,接近平手的
        决策可能翻边,所以这个标签必须跟着结果一起存。
    """

    command: list[str]
    model_path: str | None = None
    device: str = "cpu"
    determinism_tag: str = ""
    env: dict[str, str] | None = None
    cwd: str | None = None

    def spawn(self, player_id: int) -> MjaiBotProcess:
        return MjaiBotProcess(
            command=list(self.command), player_id=player_id, env=self.env, cwd=self.cwd
        )

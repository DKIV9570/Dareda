"""日志回放引擎 —— 对手照人类原样打,脱轨后回落到 Mortal。

这是"对手照原样打、英雄座换 Mortal"这套反事实的核心。实现 libriichi 的
``engine_type = 'mjai-log'`` 协议:``react_batch(game_states)`` 里每个 ``game_state``
带 ``.game_index`` / ``.state``(``PlayerState``)/ ``.events_json``(replay 到目前为止的
完整公共事件历史)。

**对齐**(实测):历史长度 N 恰好是人类日志下一个事件的下标。首次 react 是庄家在
``[start_kyoku, tsumo]`` 之后(N=2)被要求产出 2 号事件。

**回放**:被询问的座 P,若仍在轨且 ``human[N]`` 是 P 能产出的动作 → 照打;否则忠实地
"过"(none)。英雄座、以及脱轨后的座次 → 交给 Mortal。

**Mortal fallback 用 libriichi 的 ``mjai.Bot``**。实测(见 git 历史的探针)Bot 能以
``can_act=False`` 全程观察公共事件流(含它自己被照打的历史动作)而保持内部状态同步,
只在轮到它决策时(``can_act=True``,即摸牌后决定打牌 / 别家打牌后决定鸣牌)才跑网络。
所以 fallback Bot 始终与真实牌局同步,脱轨那一刻直接接手,给出的是 Mortal 的选择。

一个 :class:`LogFollowEngine` 只服务**一个小局**(fresh bots),由上层逐局新建 ——
既简单又避开了跨局复用 runner 触发的 libriichi panic。
"""

from __future__ import annotations

import json

_AGENT_EVENTS = frozenset(
    {"dahai", "chi", "pon", "daiminkan", "ankan", "kakan", "reach", "hora", "ryukyoku"}
)
_KEY_FIELDS = ("type", "actor", "target", "pai", "consumed")


def _action_key(ev: dict):
    return tuple(
        tuple(ev[f]) if f == "consumed" and f in ev else ev.get(f) for f in _KEY_FIELDS
    )


def _same_action(a: dict, b: dict) -> bool:
    return a.get("type") == b.get("type") and _action_key(a) == _action_key(b)


class LogFollowEngine:
    """单小局:照人类日志打,脱轨/英雄座回落 Mortal。

    :param human_events: 本小局的 mjai 事件列表(:func:`dareda.majsoul.mjai_convert.convert_hand`)。
    :param follow_seats: 照日志打的**绝对座次**集合。不在其中的即英雄座,全程 Mortal。
    :param mortal_engine: ``engine_type='mortal'`` 的引擎,用来建 4 个 fallback Bot。
    :param on_divergence: 可选 ``(seat, position)`` 回调,首次脱轨时触发,供保真度统计。
    """

    engine_type = "mjai-log"

    def __init__(
        self,
        human_events,
        follow_seats,
        mortal_engine,
        *,
        on_divergence=None,
        measure_sink=None,
    ):
        import libriichi

        self.name = "logfollow"
        self._human = human_events
        # measure_sink: 可选回调 (seat, human_event, mortal_reaction_dict)。设了它,照日志
        # 打的座次每次决策会额外做一次 can_act=True 的影子评估读出 Mortal 的选择与 Q 值
        # (但仍返回日志动作),用于在忠实复现的同时测量该家相对 Mortal 的强度。
        self._measure = measure_sink
        # 对齐用的"核心"序列:剔除 dora 事件。libriichi 从自己的牌山发 dora,且加杠的
        # dora 时机(摸岭上后、打牌前)与雀魂报告时机(打牌时)差一位;dora 是牌山的
        # 确定性产物、非玩家决策,从对齐里剔掉才不会被这一位错位误判成脱轨。
        self._human_core = [e for e in human_events if e.get("type") != "dora"]
        self._follow = set(follow_seats)
        self._on_divergence = on_divergence
        self.player_ids = None
        self._derailed = False
        self._divergence_pos = None
        self._checked = 0  # 已做脱轨比对的事件数

        # mortal_engine 可以是单个引擎(四座共用),或 4 个引擎的列表(每座独立强度 ——
        # 英雄 greedy、各对手按标定温度)。fallback bot 逐座用对应引擎建。
        engines = mortal_engine if isinstance(mortal_engine, (list, tuple)) else [mortal_engine] * 4
        if len(engines) != 4:
            raise ValueError(f"engines 需 1 个或 4 个,得到 {len(engines)}")
        self._bots = [libriichi.mjai.Bot(engines[i], i) for i in range(4)]
        self._fed = 0  # 已喂给所有 bot 的公共事件数
        for b in self._bots:
            b.react(json.dumps({"type": "start_game"}), can_act=False)

    def set_player_ids(self, player_ids):
        self.player_ids = list(player_ids)

    def start_game(self, game_idx):
        pass

    def end_kyoku(self, game_idx):
        pass

    def end_game(self, game_idx, scores):
        pass

    @property
    def derailed(self) -> bool:
        return self._derailed

    @property
    def divergence_position(self):
        return self._divergence_pos

    def react_batch(self, game_states):
        events = json.loads(game_states[0].events_json)
        n = len(events)
        core = [e for e in events if e.get("type") != "dora"]
        n_core = len(core)

        # 脱轨检测:在剔除 dora 的核心序列上逐事件比对(所有类型,含 tsumo)。一旦某位置
        # 不一致,位置对齐从此失效,标记脱轨。**必须比所有类型** —— 英雄"该鸣没鸣 /
        # 不该鸣却鸣"会表现为 tsumo 替换了 call(或反之),只比 agent 事件会漏掉,
        # 导致后面对手照错位日志出手、打出手里没有的牌而崩溃。
        while not self._derailed and self._checked < n_core:
            k = self._checked
            self._checked += 1
            if k >= len(self._human_core) or not _same_action(core[k], self._human_core[k]):
                self._derailed = True
                self._divergence_pos = k
                break

        # 把新事件(除最后一个)以 can_act=False 喂给所有 bot,保持同步
        if n - 1 > self._fed:
            for pos in range(self._fed, n - 1):
                line = json.dumps(events[pos])
                for b in self._bots:
                    b.react(line, can_act=False)
            self._fed = n - 1

        asked = {self.player_ids[gs.game_index]: gs for gs in game_states}
        last_line = json.dumps(events[n - 1]) if n >= 1 else None

        # 最后一个事件:对每个 bot 决定 can_act。被问到且需要 Mortal 决策的座 → True。
        # 测量模式下,照日志打的座也用 can_act=True 做影子评估(读 Q,但仍用日志动作)。
        # 每座每事件只 react 一次 —— react 无论 can_act 都同样更新状态,双调用会重复处理
        # 事件、把 bot 状态搞乱。
        results = {}
        for seat in range(4):
            gs = asked.get(seat)
            need_mortal = gs is not None and (self._derailed or seat not in self._follow)
            following = gs is not None and not need_mortal
            want_inference = bool(need_mortal) or (following and self._measure is not None)
            r = self._bots[seat].react(last_line, can_act=want_inference) if last_line else None
            if gs is None:
                continue
            if need_mortal:
                results[seat] = r if r is not None else '{"type":"none"}'
            else:
                if self._measure is not None and r is not None:
                    target = self._human_core[n_core] if n_core < len(self._human_core) else None
                    if target is not None and target.get("actor") == seat:
                        self._measure(seat, target, json.loads(r))
                results[seat] = self._log_action(seat, n_core)
        self._fed = n  # 最后一个事件也喂过了

        return [results[self.player_ids[gs.game_index]] for gs in game_states]

    def _log_action(self, seat: int, n_core: int) -> str:
        # 在剔除 dora 的核心序列上索引:下一个核心事件即人类此刻的动作
        target = self._human_core[n_core] if n_core < len(self._human_core) else None
        if (
            target is not None
            and target.get("type") in _AGENT_EVENTS
            and target.get("actor") == seat
        ):
            return json.dumps(target)
        return '{"type":"none"}'

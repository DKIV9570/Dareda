"""spec §5 配牌恒等断言 —— 项目的准入关卡。

    输入:牌谱里的 paishan + ju
    执行:自己的发牌函数
    断言:逐张匹配 tiles0..tiles3

全 K 局都对上 ⇒ 发牌顺序、赤宝编码、牌山起始定点三件事同时被证明,后续不必再
怀疑配牌层。

两个实现上的坑:

1. 牌谱里的 ``tiles0`` 和 ``paishan`` 是两个独立的字符串,解码时各自分配 copy 号,
   同一张 5m 在两边可能拿到不同的 tile id。所以比较必须按 **kind + 赤**(即渲染回
   ``5m``/``0m`` 这层)做多重集比较,不能直接比 tile id。
2. 雀魂里**庄家那一档有 14 张** —— 配牌 13 张加上庄家的第一枚自摸。这时把第 14 张
   按 ``paishan[draw_cursor]`` 一并校验,顺带把自摸游标也钉死了,断言反而更强。
"""

from __future__ import annotations

from dataclasses import dataclass

from .deal import DEFAULT_CONVENTION, WallConvention, deal, split_wall
from .record import GameRecord, Hand
from .tiles import tile_to_code


def _codes(tids) -> list[str]:
    return sorted(tile_to_code(t) for t in tids)


def compare_haipai(dealt, recorded) -> bool:
    """按 kind+赤 比较四家起手(多重集,忽略排列顺序)。"""
    return [_codes(h) for h in dealt] == [_codes(h) for h in recorded]


def expected_hands(hand: Hand, result) -> list[list[int]]:
    """按牌谱记录的张数,补上庄家的第一枚自摸,得到应当匹配的四家牌。"""
    out: list[list[int]] = []
    for seat in range(4):
        exp = list(result.haipai[seat])
        n = len(hand.haipai[seat])
        if n == 14:
            exp.append(hand.paishan[result.draw_cursor])
        elif n != 13:
            raise ValueError(f"{hand.label} 座{seat} 记录了 {n} 张牌,只接受 13 或 14")
        out.append(exp)
    return out


@dataclass
class HandCheck:
    hand: Hand
    ok: bool
    detail: str = ""


@dataclass
class VerifyReport:
    convention: WallConvention
    checks: list[HandCheck]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    def render(self) -> str:
        lines = [f"牌山约定: {self.convention.value}", f"配牌恒等: {self.passed}/{len(self.checks)} 局通过"]
        for c in self.checks:
            if not c.ok:
                lines.append(f"  ✗ {c.hand.label}: {c.detail}")
        if self.ok:
            lines.append("  ✓ 全部通过 —— 发牌顺序 / 赤宝编码 / 牌山定点均正确")
        return "\n".join(lines)


def verify_record(
    record: GameRecord, convention: WallConvention = DEFAULT_CONVENTION
) -> VerifyReport:
    checks: list[HandCheck] = []
    for hand in record.hands:
        if not hand.haipai or len(hand.haipai) != 4:
            checks.append(HandCheck(hand, False, "牌谱缺 tiles0..tiles3,无法断言"))
            continue
        result = deal(hand.paishan, hand.oya, convention)
        try:
            expected = expected_hands(hand, result)
        except ValueError as exc:
            checks.append(HandCheck(hand, False, str(exc)))
            continue
        if compare_haipai(expected, hand.haipai):
            checks.append(HandCheck(hand, True))
        else:
            detail = []
            for seat in range(4):
                got, want = _codes(expected[seat]), _codes(hand.haipai[seat])
                if got != want:
                    detail.append(f"座{seat} 牌谱 {' '.join(want)} / 实发 {' '.join(got)}")
            checks.append(HandCheck(hand, False, "; ".join(detail)))
    return VerifyReport(convention, checks)


# --------------------------------------------------------------- 王牌区验证


@dataclass
class DeadWallReport:
    """王牌区布局的实测覆盖情况。

    §5 只验配牌;要把牌山喂进 libriichi,还得把王牌区(岭上/宝牌/里宝)摆对。
    这里逐项统计"有多少样本、对上多少",**没有样本的项目会明说没验**,
    不会拿零样本冒充通过。
    """

    dora_ok: int = 0
    dora_total: int = 0
    ura_ok: int = 0
    ura_total: int = 0
    rinshan_ok: int = 0
    rinshan_total: int = 0

    @property
    def ok(self) -> bool:
        """只看有样本的项目;全项零样本视为未通过。"""
        checks = [
            (self.dora_ok, self.dora_total),
            (self.ura_ok, self.ura_total),
            (self.rinshan_ok, self.rinshan_total),
        ]
        if all(t == 0 for _, t in checks):
            return False
        return all(o == t for o, t in checks)

    def render(self) -> str:
        def line(name, ok, total, derived_note):
            if total == 0:
                return f"  {name}: 无样本 —— 未验证({derived_note})"
            flag = "✓" if ok == total else "✗"
            return f"  {name}: {flag} {ok}/{total}"

        return "\n".join(
            [
                "王牌区布局:",
                line("宝牌指示牌", self.dora_ok, self.dora_total, "牌谱里没开杠"),
                line("里宝指示牌", self.ura_ok, self.ura_total, "牌谱里没有立直和了"),
                line("岭上牌", self.rinshan_ok, self.rinshan_total, "牌谱里没开杠"),
            ]
        )


def verify_dead_wall(record: GameRecord, actions_by_round: list[list[tuple[str, dict]]]) -> DeadWallReport:
    """拿动作流核对王牌区布局。

    :param actions_by_round: 每个小局的 ``(动作名, 数据体)`` 列表,与
        ``record.hands`` 一一对应。可用 :func:`split_actions_by_round` 生成。
    """
    rep = DeadWallReport()
    for hand, acts in zip(record.hands, actions_by_round):
        setup = split_wall(hand.paishan, hand.oya)

        # 宝牌指示牌:开局那张 + 杠后新增,取该局出现过的最长列表
        seen = [tile_to_code(t) for t in hand.doras]
        for _, e in acts:
            d = e.get("doras")
            if d and len(d) > len(seen):
                seen = list(d)
        # setup.dora_indicators 是倒序(供 pop),核对时翻回正序
        expected_dora = list(reversed(setup.dora_indicators))
        for k, got in enumerate(seen):
            if k >= len(expected_dora):
                break
            rep.dora_total += 1
            rep.dora_ok += got == tile_to_code(expected_dora[k])

        # 里宝指示牌:和了时的 li_doras(正序)
        for name, e in acts:
            if name != "RecordHule":
                continue
            for hule in e.get("hules", []):
                for k, got in enumerate(hule.get("li_doras", [])):
                    if k >= len(setup.ura_indicators):
                        break
                    rep.ura_total += 1
                    rep.ura_ok += got == tile_to_code(setup.ura_indicators[k])

        # 岭上牌:杠之后紧跟的那次摸牌
        expected_rinshan = list(reversed(setup.rinshan))
        kan_idx = 0
        after_kan = False
        for name, e in acts:
            if after_kan and name == "RecordDealTile":
                if kan_idx < len(expected_rinshan):
                    rep.rinshan_total += 1
                    rep.rinshan_ok += e.get("tile") == tile_to_code(expected_rinshan[kan_idx])
                kan_idx += 1
            after_kan = name == "RecordAnGangAddGang" or (
                name == "RecordChiPengGang" and e.get("type") == 2
            )
    return rep


def split_actions_by_round(raw: dict) -> list[list[tuple[str, dict]]]:
    """把 ``{mjsrecordtypes, mjslog}`` 按 ``RecordNewRound`` 切成每小局的动作列表。"""
    types = raw.get("mjsrecordtypes") or []
    log = raw.get("mjslog") or []
    if len(types) != len(log):
        types = ["RecordNewRound" if "paishan" in e else "?" for e in log]
    rounds: list[list[tuple[str, dict]]] = []
    cur: list[tuple[str, dict]] | None = None
    for name, e in zip(types, log):
        if name == "RecordNewRound":
            cur = []
            rounds.append(cur)
        elif cur is not None:
            cur.append((name, e))
    return rounds


def infer_convention(record: GameRecord) -> WallConvention | None:
    """拿真牌谱撞出正确的牌山约定。全都撞不上返回 None(说明假设本身有问题)。"""
    for conv in WallConvention:
        if verify_record(record, conv).ok:
            return conv
    return None

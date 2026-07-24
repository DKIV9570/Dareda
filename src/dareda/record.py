"""牌谱数据模型 —— 平台无关的中间表示。

雀魂 / 天凤的解析器都产出这一层,后面的发牌、断言、driver 只认这一层。
"""

from __future__ import annotations

from dataclasses import dataclass, field

CHANG_NAMES = ("东", "南", "西", "北")
JU_NAMES = ("一", "二", "三", "四")


@dataclass(frozen=True)
class Hand:
    """一个小局的开局快照,对应雀魂 ``RecordNewRound``。"""

    chang: int
    """场风:0=东 1=南 2=西"""
    ju: int
    """局数(0-based)。**庄家座次 = ju**,见下方 :attr:`oya`。"""
    ben: int
    """本场数(honba)。按 spec §2,计分用标签值,不由 replay 演化。"""
    liqibang: int
    """开局时场上遗留的立直棒数(仅原局记录;replay 里此值浮动)。"""
    scores: tuple[int, int, int, int]
    """原局各家开局点数(仅供对照;replay 里此值浮动)。"""
    paishan: tuple[int, ...]
    """牌山,tile id 数组,牌山顺序。"""
    haipai: tuple[tuple[int, ...], ...]
    """牌谱里记录的四家起手(``tiles0``..``tiles3``),用于 §5 断言。"""
    doras: tuple[int, ...] = ()
    """开局宝牌指示牌。"""

    @property
    def oya(self) -> int:
        """庄家座次。

        spec §1.2 写的是 ``oya = ju``,并注 "ju: 0..3 = 东一..东四, 4..7 = 南一..南四"。
        后半句是天凤那套连续局号的说法;雀魂里 ``chang`` 与 ``ju`` 是分开的两个字段,
        ``ju`` 恒为 0..3 且直接等于庄家座次。本场数不影响庄位这一条两边一致。
        """
        return self.ju

    @property
    def label(self) -> str:
        """``东一`` / ``南二一本`` 这种人类可读标签。"""
        base = f"{CHANG_NAMES[self.chang]}{JU_NAMES[self.ju]}"
        return f"{base}{self.ben}本" if self.ben else base

    @property
    def key(self) -> tuple[int, int, int]:
        """spec §1.1 的 ``(chang, ju, ben)`` 三元组 —— 序列钉死用的就是它。"""
        return (self.chang, self.ju, self.ben)


@dataclass
class GameRecord:
    """一整场半庄。"""

    hands: list[Hand]
    source: str = "unknown"
    """来源标识,如 ``majsoul:<uuid>``。"""
    final_scores: tuple[int, int, int, int] | None = None
    """原局终局点数(含精算),没有就 None。"""
    player_names: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)

    @property
    def sequence(self) -> list[tuple[int, int, int]]:
        """spec §1.1 的固定序列。replay 严格按此走,不增不减。"""
        return [h.key for h in self.hands]

    @property
    def K(self) -> int:
        return len(self.hands)

    def describe_sequence(self) -> str:
        return " / ".join(h.label for h in self.hands)

"""四象限分解的测试(纯数值,无需 libriichi/权重)。"""

import pytest

from dareda.analysis.diagnose import NEUTRAL, Diagnosis


def d(actual, deal_ev, self_ev):
    return Diagnosis(hero=1, actual=actual, deal_ev=deal_ev, self_ev=self_ev)


# ---------------------------------------------------------------- 闭合性


@pytest.mark.parametrize(
    "actual,deal_ev,self_ev",
    [(1, 2.5, 2.5), (4, 2.0, 1.8), (2, 3.3, 3.0), (3, 2.5, 2.9), (4, 1.5, 3.4)],
)
def test_decomposition_always_closes(actual, deal_ev, self_ev):
    """三项之和必须恒等于 实际名次-2.5,否则这个分解就是编的。"""
    assert d(actual, deal_ev, self_ev).check_closure() < 1e-9


# ---------------------------------------------------------------- 四象限


def test_good_deal_played_well():
    # 牌好(期望 2.0 优于中性),打法再推进到 1.6
    x = d(actual=1, deal_ev=2.0, self_ev=1.6)
    assert x.deal_label == "好牌"
    assert x.skill_label == "打得好"
    assert x.quadrant == "好牌打好了"


def test_good_deal_played_badly():
    # 牌好,但你的打法把期望往回拖
    x = d(actual=3, deal_ev=2.0, self_ev=2.6)
    assert x.quadrant == "好牌打烂了"


def test_bad_deal_played_well():
    x = d(actual=2, deal_ev=3.2, self_ev=2.7)
    assert x.quadrant == "烂牌打好了"


def test_bad_deal_played_badly():
    x = d(actual=4, deal_ev=3.1, self_ev=3.6)
    assert x.quadrant == "烂牌打烂了"


def test_deadband_avoids_overclaiming():
    """牌和打法都在死区内时,不该硬套四象限标签。"""
    x = d(actual=2, deal_ev=2.55, self_ev=2.6)
    assert x.deal_label == "牌一般"
    assert x.skill_label == "打得一般"
    assert "一般" in x.quadrant


# ---------------------------------------------------------------- 运气


def test_luck_sign_follows_placement_direction():
    """名次越小越好 —— 实际好于期望才叫顺。"""
    lucky = d(actual=1, deal_ev=2.5, self_ev=3.0)
    assert lucky.luck_gain == pytest.approx(2.0)
    assert lucky.luck_label == "运气顺"

    unlucky = d(actual=4, deal_ev=2.5, self_ev=2.0)
    assert unlucky.luck_gain == pytest.approx(-2.0)
    assert unlucky.luck_label == "运气背"


def test_neutral_luck_is_not_labelled():
    x = d(actual=2, deal_ev=2.5, self_ev=2.1)
    assert x.luck_label == "运气正常"


# ---------------------------------------------------------------- 真实两局


def test_real_game_unlucky_fourth():
    """吃四那局:self_ev 实测 2.00,实际 4 位 —— 结论必须点出运气背。"""
    x = d(actual=4, deal_ev=2.4, self_ev=2.00)
    assert x.luck_label == "运气背"
    assert "运气还背" in x.verdict()


def test_real_game_lucky_first():
    """吃一那局:self_ev 实测 3.27,实际 1 位 —— 必须点出运气顺。"""
    x = d(actual=1, deal_ev=2.9, self_ev=3.27)
    assert x.luck_label == "运气顺"
    assert "偏顺" in x.verdict()


def test_render_contains_all_three_axes():
    out = d(actual=4, deal_ev=2.4, self_ev=2.0).render(name="测试")
    for kw in ("牌", "打", "运", "名次分解", "座1"):
        assert kw in out

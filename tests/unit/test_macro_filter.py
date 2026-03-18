from alpha.signals.macro_filter import MacroFilter


def test_risk_on_when_conditions_normal():
    f = MacroFilter()
    regime = {"DFF": 5.0, "T10Y2Y": 0.5, "VIXCLS": 18.0, "UNRATE": 4.2}
    assert f.is_risk_on(regime) is True


def test_risk_off_when_vix_spikes():
    f = MacroFilter()
    regime = {"DFF": 5.0, "T10Y2Y": 0.5, "VIXCLS": 40.0, "UNRATE": 4.2}
    assert f.is_risk_on(regime) is False


def test_risk_off_when_yield_curve_inverted():
    f = MacroFilter()
    regime = {"DFF": 5.0, "T10Y2Y": -0.5, "VIXCLS": 18.0, "UNRATE": 4.2}
    assert f.is_risk_on(regime) is False


def test_get_regime_label():
    f = MacroFilter()
    assert f.get_label({"VIXCLS": 40.0, "T10Y2Y": -0.3}) == "risk_off"
    assert f.get_label({"VIXCLS": 15.0, "T10Y2Y": 0.5}) == "risk_on"


def test_regime_score_calm_market():
    f = MacroFilter()
    score = f.get_regime_score({"VIXCLS": 14.0, "T10Y2Y": 1.0})
    assert score > 0.7, "Low VIX + normal yield curve should score high"


def test_regime_score_stressed_market():
    f = MacroFilter()
    score = f.get_regime_score({"VIXCLS": 45.0, "T10Y2Y": -0.5})
    assert score < 0.3, "High VIX + inverted curve should score low"


def test_regime_score_is_continuous():
    f = MacroFilter()
    s1 = f.get_regime_score({"VIXCLS": 20.0, "T10Y2Y": 0.5})
    s2 = f.get_regime_score({"VIXCLS": 25.0, "T10Y2Y": 0.2})
    s3 = f.get_regime_score({"VIXCLS": 32.0, "T10Y2Y": -0.1})
    assert s1 > s2 > s3, "Score should decrease monotonically as conditions worsen"


def test_position_scalar_continuous_in_normal_regime():
    f = MacroFilter()
    scalar = f.get_position_scalar({"VIXCLS": 18.0, "T10Y2Y": 0.8})
    assert 0.1 <= scalar <= 1.0


def test_position_scalar_caps_at_0_25_in_risk_off():
    f = MacroFilter()
    scalar = f.get_position_scalar({"VIXCLS": 40.0, "T10Y2Y": -0.5})
    assert scalar <= 0.25

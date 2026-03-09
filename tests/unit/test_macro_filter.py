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

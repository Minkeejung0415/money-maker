VIX_RISK_OFF_THRESHOLD = 30.0
YIELD_CURVE_INVERSION_THRESHOLD = 0.0


class MacroFilter:
    """
    Gates capital deployment across all verticals based on macro regime.
    When risk_off: all engines reduce position size or pause entirely.
    """

    def __init__(
        self,
        vix_threshold: float = VIX_RISK_OFF_THRESHOLD,
        yield_curve_threshold: float = YIELD_CURVE_INVERSION_THRESHOLD,
    ):
        self.vix_threshold = vix_threshold
        self.yield_curve_threshold = yield_curve_threshold

    def is_risk_on(self, regime: dict[str, float | None]) -> bool:
        vix = regime.get("VIXCLS")
        spread = regime.get("T10Y2Y")
        if vix is not None and vix >= self.vix_threshold:
            return False
        if spread is not None and spread <= self.yield_curve_threshold:
            return False
        return True

    def get_label(self, regime: dict[str, float | None]) -> str:
        return "risk_on" if self.is_risk_on(regime) else "risk_off"

    def get_position_scalar(self, regime: dict[str, float | None]) -> float:
        """Returns a multiplier [0.0, 1.0] to scale position sizes."""
        if not self.is_risk_on(regime):
            return 0.25  # deploy only 25% of normal size in risk-off
        vix = regime.get("VIXCLS", 15.0) or 15.0
        # Linearly reduce from 1.0 at VIX=15 to 0.5 at VIX=30
        scalar = max(0.5, 1.0 - ((vix - 15.0) / 30.0))
        return round(scalar, 2)

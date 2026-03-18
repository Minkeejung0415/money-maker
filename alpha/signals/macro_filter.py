import math

VIX_RISK_OFF_THRESHOLD = 30.0
YIELD_CURVE_INVERSION_THRESHOLD = 0.0


class MacroFilter:
    """
    Gates capital deployment across all verticals based on macro regime.

    Research upgrade (2026-03-17): replaced binary risk-off trigger with
    continuous sigmoid scoring. Per de Longis & Ellis (2022), scaling exposure
    proportionally to a composite regime score outperforms binary on/off rules
    after transaction costs.
    """

    def __init__(
        self,
        vix_threshold: float = VIX_RISK_OFF_THRESHOLD,
        yield_curve_threshold: float = YIELD_CURVE_INVERSION_THRESHOLD,
    ):
        self.vix_threshold = vix_threshold
        self.yield_curve_threshold = yield_curve_threshold

    def is_risk_on(self, regime: dict[str, float | None]) -> bool:
        """Binary risk-on check (preserved for backward compatibility)."""
        vix = regime.get("VIXCLS")
        spread = regime.get("T10Y2Y")
        if vix is not None and vix >= self.vix_threshold:
            return False
        if spread is not None and spread <= self.yield_curve_threshold:
            return False
        return True

    def get_regime_score(self, regime: dict[str, float | None]) -> float:
        """
        Continuous regime score in [0.0, 1.0].
        1.0 = fully risk-on, 0.0 = fully risk-off.

        Combines VIX and yield curve slope via sigmoid smoothing so that
        exposure scales gradually rather than cliff-edging at a threshold.

        VIX component: sigmoid centered at 25 (stressed), scale=6.
        Yield curve component: sigmoid centered at 0, scale=0.5.
        """
        vix = regime.get("VIXCLS") or 15.0
        spread = regime.get("T10Y2Y") or 0.5

        # Higher VIX → lower score (centered at 25, inverted sigmoid)
        vix_score = 1.0 / (1.0 + math.exp((vix - 25.0) / 6.0))

        # Positive spread → higher score; inversion → lower score
        yc_score = 1.0 / (1.0 + math.exp(-spread / 0.5))

        return round(0.5 * vix_score + 0.5 * yc_score, 3)

    def get_label(self, regime: dict[str, float | None]) -> str:
        return "risk_on" if self.is_risk_on(regime) else "risk_off"

    def get_position_scalar(self, regime: dict[str, float | None]) -> float:
        """
        Returns a continuous multiplier [0.1, 1.0] to scale position sizes.
        Uses regime_score rather than a binary on/off cliff.
        Hard cap at 0.25 when binary risk_off fires (extreme stress).
        """
        score = self.get_regime_score(regime)
        scalar = max(0.1, min(1.0, score))
        if not self.is_risk_on(regime):
            scalar = min(scalar, 0.25)
        return round(scalar, 2)

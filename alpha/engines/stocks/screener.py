"""
Multi-factor stock screener.
Ranks a universe of stocks by a composite score:
  - Momentum (return_1d, price vs MA-20)
  - Mean-reversion potential (RSI distance from 50)
  - Liquidity (volume)
"""


class StockScreener:
    def __init__(
        self,
        min_volume: float = 1_000_000,
        max_rsi: float = 100.0,
        min_rsi: float = 0.0,
    ):
        self.min_volume = min_volume
        self.max_rsi = max_rsi
        self.min_rsi = min_rsi

    def _passes_filters(self, row: dict) -> bool:
        volume = row.get("volume", 0) or 0
        rsi = row.get("rsi_14", 50) or 50
        if volume < self.min_volume:
            return False
        if rsi > self.max_rsi or rsi < self.min_rsi:
            return False
        return True

    def _compute_score(self, row: dict) -> float:
        components = []

        # Momentum: daily return clipped to [-5%, +5%] → [-1, 1]
        ret = row.get("return_1d") or 0.0
        components.append(max(-1.0, min(1.0, ret * 20)))

        # Price vs MA-20 trend
        close = row.get("close") or 0.0
        ma20 = row.get("ma_20") or close
        if ma20 > 0:
            spread = (close - ma20) / ma20
            components.append(max(-1.0, min(1.0, spread * 10)))

        # RSI: near 50 = neutral, away from extremes is better for entry
        rsi = row.get("rsi_14") or 50.0
        rsi_score = 1.0 - abs(rsi - 50) / 50  # 1.0 at RSI=50, 0.0 at 0/100
        components.append(rsi_score)

        return round(sum(components) / len(components), 4)

    def rank(self, universe: list[dict]) -> list[dict]:
        """Filter and rank universe descending by composite score."""
        filtered = [r for r in universe if self._passes_filters(r)]
        for row in filtered:
            row["score"] = self._compute_score(row)
        return sorted(filtered, key=lambda r: r["score"], reverse=True)

    def top(self, n: int, universe: list[dict]) -> list[dict]:
        return self.rank(universe)[:n]

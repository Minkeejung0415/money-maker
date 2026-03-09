"""
Dashboard data layer — computes metrics and builds plotly charts.
Streamlit UI wired in Milestone 7.
"""
import plotly.graph_objects as go


class DashboardData:
    def __init__(self, trades: list[dict]):
        self._trades = sorted(trades, key=lambda t: t.get("timestamp", ""))

    def summary_stats(self) -> dict:
        pnls = [t["pnl"] for t in self._trades]
        wins = sum(1 for p in pnls if p > 0)
        return {
            "total_pnl": round(sum(pnls), 4),
            "trade_count": len(pnls),
            "win_rate": round(wins / len(pnls), 4) if pnls else 0.0,
            "best_trade": max(pnls) if pnls else 0.0,
            "worst_trade": min(pnls) if pnls else 0.0,
        }

    def pnl_by_vertical(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for t in self._trades:
            v = t.get("vertical", "unknown")
            result[v] = result.get(v, 0.0) + t["pnl"]
        return {k: round(v, 4) for k, v in result.items()}

    def cumulative_pnl_series(self) -> list[dict]:
        cumulative = 0.0
        series = []
        for t in self._trades:
            cumulative += t["pnl"]
            series.append({
                "timestamp": t.get("timestamp", ""),
                "pnl": t["pnl"],
                "cumulative_pnl": round(cumulative, 4),
            })
        return series

    def build_pnl_chart(self) -> go.Figure:
        """Build a cumulative P&L line chart."""
        series = self.cumulative_pnl_series()
        timestamps = [s["timestamp"] for s in series]
        cum_pnl = [s["cumulative_pnl"] for s in series]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=timestamps, y=cum_pnl,
            mode="lines+markers",
            name="Cumulative P&L",
            line=dict(color="#00d4aa", width=2),
        ))
        fig.update_layout(
            title="Alpha Terminal — Cumulative P&L",
            xaxis_title="Date",
            yaxis_title="P&L ($)",
            template="plotly_dark",
        )
        return fig

    def build_vertical_breakdown_chart(self) -> go.Figure:
        """Build a bar chart of P&L by vertical."""
        by_v = self.pnl_by_vertical()
        fig = go.Figure(go.Bar(
            x=list(by_v.keys()),
            y=list(by_v.values()),
            marker_color=["#00d4aa" if v >= 0 else "#ff4444" for v in by_v.values()],
        ))
        fig.update_layout(
            title="P&L by Vertical",
            template="plotly_dark",
        )
        return fig

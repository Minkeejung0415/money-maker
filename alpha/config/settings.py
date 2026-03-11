from __future__ import annotations
import tomllib
from pathlib import Path
from pydantic_settings import BaseSettings

CONFIG_DIR = Path(__file__).parent


def _load_toml(name: str) -> dict:
    path = CONFIG_DIR / name
    if path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


class RiskConfig:
    def __init__(self):
        data = _load_toml("risk.toml").get("risk", {})
        self.max_drawdown_pct: float = data.get("max_drawdown_pct", 0.15)
        self.kelly_fraction: float = data.get("kelly_fraction", 0.25)
        self.max_cross_asset_exposure_pct: float = data.get("max_cross_asset_exposure_pct", 0.80)
        self.circuit_breaker_daily_loss_pct: float = data.get("circuit_breaker_daily_loss_pct", 0.05)


class SportsConfig:
    def __init__(self):
        data = _load_toml("sports.toml").get("sports", {})
        self.books: list[str] = data.get("books", ["fanduel", "draftkings", "betmgm"])
        self.enabled_sports: list[str] = data.get("sports", ["basketball", "football", "tennis"])
        self.leagues: list[str] = data.get("leagues", ["nba", "nfl", "atp"])
        self.min_ev_threshold: float = data.get("min_ev_threshold", 0.05)


class StocksConfig:
    def __init__(self):
        data = _load_toml("settings.toml").get("stocks", {})
        self.watchlist: list[str] = data.get(
            "watchlist", ["AAPL", "MSFT", "NVDA"]
        )


class CryptoConfig:
    def __init__(self):
        data = _load_toml("settings.toml").get("crypto", {})
        self.pairs: list[str] = data.get(
            "pairs", ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        )


class ExchangeConfig:
    def __init__(self):
        data = _load_toml("exchanges.toml").get("exchanges", {})
        self.default: str = data.get("default", "binance")
        self.sandbox: bool = data.get("sandbox", True)


_terminal_toml = _load_toml("settings.toml").get("terminal", {})


class Settings(BaseSettings):
    paper_mode: bool = _terminal_toml.get("paper_mode", True)
    active_verticals: list[str] = _terminal_toml.get(
        "active_verticals", ["stocks", "crypto", "sports"]
    )

    alpha_vantage_api_key: str = ""
    fred_api_key: str = ""
    odds_api_key: str = ""
    football_api_key: str = ""  # football-data.org (EPL + UCL)
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = "alpha-terminal-data"

    # Alpaca (stocks) — use paper-api.alpaca.markets for paper, api.alpaca.markets for live
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    # Crypto exchange via ccxt
    exchange_name: str = ""
    exchange_api_key: str = ""
    exchange_api_secret: str = ""

    # Execution is opt-in to avoid side effects in tests and local runs.
    execution_enabled: bool = _terminal_toml.get("execution_enabled", False)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

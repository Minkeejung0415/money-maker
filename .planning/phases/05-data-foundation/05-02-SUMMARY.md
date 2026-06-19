---
plan: 05-02
phase: 05-data-foundation
status: complete
requirements_addressed:
  - INGEST-02
  - INGEST-03
commits:
  - 6db6826  # feat(05-02): wc_elo.py + 7 unit tests
  - 195d8b3  # feat(05-02): wc_stats.py + 6 unit tests
---

# Plan 05-02 Summary: WC Reader Modules

## What Was Built

Two new reader modules that give downstream code clean, no-network access to pre-built WC data:

### `alpha/data/ingestion/wc_elo.py`
- `load_wc_elo_ratings() -> dict[str, int]` — reads `data/wc_priors.json`; raises `FileNotFoundError` with build instruction if missing
- `get_elo_rating(team, ratings) -> int` — returns rating or 1500 fallback with warning
- Constants: `_WC_PRIORS_PATH = Path("data/wc_priors.json")`, `_ELO_FALLBACK = 1500`

### `alpha/data/ingestion/wc_stats.py`
- `get_wc_team_stats() -> dict[str, dict]` — reads `data/.wc_cache/wc_stats.pkl`; raises `FileNotFoundError` with build instruction if missing; pops `built_at`; applies `_TEAM_NAME_MAP` normalization
- Constants: `_WC_CACHE_DIR = Path("data/.wc_cache")`, `_WC_STATS_CACHE = _WC_CACHE_DIR / "wc_stats.pkl"`
- `_TEAM_NAME_MAP: dict[str, str] = {}` — empty initially, populated after build script run reveals name mismatches

## Verification

- 7/7 `test_wc_priors_loader.py` tests passing
- 6/6 `test_wc_stats.py` tests passing
- 591/591 full suite passing (0 regressions)
- Cache namespace isolation confirmed: `_WC_CACHE_DIR` contains "wc_cache", not "soccer_cache"
- No network calls in either module (grep confirms)

## Key Contracts Delivered

`get_wc_team_stats()` output shape (per team):
```python
{"avg_goals": float, "avg_xG": float, "avg_shots": float, "defense_score": float}
```

`load_wc_elo_ratings()` output shape:
```python
{"Brazil": 2089, "Germany": 1980, ...}  # dict[str, int]
```

Both modules raise `FileNotFoundError` with "build_wc_priors.py" in message when cache is missing — enables clear error messages for Phase 6.

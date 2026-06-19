---
plan: 05-01
phase: 05-data-foundation
status: complete
requirements_addressed:
  - INGEST-01
commits:
  - 3192fc8  # test(05-01): add failing tests
  - 3bb3edc  # feat(05-01): implementation
---

# Plan 05-01 Summary: FootballDataClient WC Extension

## What Was Built

Extended `alpha/data/ingestion/football_data_client.py` with full WC 2026 fixture support:

- **`"wc": "WC"` in `_COMP_MAP`** — routes WC league key to competition code
- **`_get_with_retry(url, *, headers, params, timeout)`** — module-level helper with 1-retry + 60s backoff on HTTP 429; all other errors propagate immediately
- **`FootballDataClient.fetch_wc_games(date_from, date_to)`** — returns list of game dicts with 9 fields including `stage` (e.g. "GROUP_STAGE", "LAST_16") and `group` (e.g. "Group A", "" in knockout rounds)
- **12 unit tests** in `tests/unit/data/test_football_data_client_wc.py` — all passing

## Verification

- 12/12 WC client tests passing
- 591/591 full suite passing (0 regressions)
- `_COMP_MAP["epl"]` and `_COMP_MAP["ucl"]` unchanged
- `fetch_today_games()` behaviour unchanged (regression test confirms no stage/group in its output)

## Key Contracts Delivered

`FootballDataClient.fetch_wc_games(date_from, date_to) -> list[dict]`:
```python
{
    "home_team": str, "away_team": str,
    "home_odds": -110, "away_odds": -110,
    "league": "wc",
    "event_id": str,
    "commence_time": str,
    "stage": str,   # "GROUP_STAGE" | "LAST_16" | "QUARTER_FINALS" | "SEMI_FINALS" | "THIRD_PLACE" | "FINAL"
    "group": str,   # "Group A" … "Group L" or "" in knockout rounds
}
```

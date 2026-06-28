# Money Maker

Multi-asset prediction and betting research workspace for NBA props, soccer and World Cup markets, MLB moneyline modeling, plus supporting stock and crypto engine experiments.

The repo is organized around versioned milestones. Each milestone documents what changed, what was validated, and which runtime path should be trusted.

## Current Version

**v2.0 - Runtime truth and artifact registry**

Status: complete as of 2026-06-28.

v2.0 makes scanner model routing explicit: no silent fallback, runtime artifact metadata gates, active model labels, and shadow challenger logging. The WC scanner defaults to the conservative Elo model; use `--model hybrid` for the hybrid challenger and `--shadow-model hybrid` to log challenger predictions without changing picks.

## Version Guide

See [docs/VERSIONS.md](docs/VERSIONS.md) for the full version index from v1.0 through v2.0.

Quick labels:

| Version | Label | Status |
| --- | --- | --- |
| v2.0 | Runtime truth and artifact registry | Complete |
| v1.9 | World Cup player-aware win probability | Complete |
| v1.8 | Player-aware MLB moneyline | Complete |
| v1.7 | Tactical calibration and validation | Complete |
| v1.6 | World Cup tactical matchups | Complete |
| v1.5 | World Cup true SGP | Complete |
| v1.4 | Soccer mode upgrade | Complete |
| v1.3 | MLB win probability model | Complete |
| v1.2 | World Cup dynamic draw algorithm | Complete |
| v1.1 | World Cup soccer mode | Complete |
| v1.0 | NBA prop model algorithm upgrade | Complete |

## Useful Commands

Generate World Cup parlay picks:

```powershell
./venv/Scripts/python.exe ./scripts/wc_scanner.py --mode parlay
```

Run the optional v1.9 hybrid World Cup baseline:

```powershell
./venv/Scripts/python.exe ./scripts/wc_scanner.py --mode parlay --model hybrid
```

Log hybrid as a shadow model while keeping Elo active:

```powershell
./venv/Scripts/python.exe ./scripts/wc_scanner.py --mode parlay --model elo --shadow-model hybrid
```

Generate World Cup same-game-parlay style picks:

```powershell
./venv/Scripts/python.exe ./scripts/wc_scanner.py --mode sgp
```

Generate MLB moneyline parlay research for a specific slate:

```powershell
./venv/Scripts/python.exe ./scripts/mlb_scanner.py --mode parlay --date 2026-06-28 --validate
```

Run the test suite:

```powershell
./venv/Scripts/python.exe -m pytest
```

## Project Docs

- [Version index](docs/VERSIONS.md)
- [Planning state](.planning/STATE.md)
- [Milestone summaries](.planning/MILESTONES.md)
- [Project contract](.planning/PROJECT.md)

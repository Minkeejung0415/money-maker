# Money Maker

Multi-asset prediction and betting research workspace for NBA props, soccer and World Cup markets, MLB moneyline modeling, plus supporting stock and crypto engine experiments.

The repo is organized around versioned milestones. Each milestone documents what changed, what was validated, and which runtime path should be trusted.

## Current Version

**v1.9 - World Cup player-aware win probability**

Status: complete as of 2026-06-24.

v1.9 upgrades the World Cup match model from an Elo-only baseline into a stacked system with hybrid team ratings, projected XI features, goalkeeper signals, tournament-state logic, tactical matchup features, context features, and chronological evaluation gates.

## Version Guide

See [docs/VERSIONS.md](docs/VERSIONS.md) for the full version index from v1.0 through v1.9.

Quick labels:

| Version | Label | Status |
| --- | --- | --- |
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

Generate World Cup same-game-parlay style picks:

```powershell
./venv/Scripts/python.exe ./scripts/wc_scanner.py --mode sgp
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

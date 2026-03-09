# Alpha Terminal — System Design
**Date:** 2026-03-08
**Status:** Approved

---

## Vision

A unified, automated command center that removes human emotion from wealth generation. Every opportunity — stock breakout, crypto whale movement, mispriced sports line — is treated as a data-driven probability exercise. Three alpha engines share a single risk layer, data layer, and execution bus.

---

## Cloned Engine Libraries (Dependencies, Not Modified)

| Repo | Role | Vertical |
|---|---|---|
| `qlib` | Microsoft AI/ML quant platform | Stocks |
| `PyPortfolioOpt` | Efficient frontier + risk models | Stocks |
| `ccxt` | Unified exchange connectivity (300+ venues) | Crypto |
| `freqtrade` | Crypto bot + backtesting + ML optimizer | Crypto |
| `hummingbot` | HFT / market-making framework (140+ venues) | Crypto |
| `OddsHarvester` | Sports odds scraper (oddsportal) | Sports |
| `NBA-Machine-Learning-Sports-Betting` | XGBoost/NN models, Kelly sizing, EV calc | Sports |

All cloned repos are **read-only references** installed as local pip dependencies. The terminal's code lives exclusively in `alpha/`.

---

## Folder Structure

```
money-maker/
│
├── alpha/                          ← THE TERMINAL (all our code)
│   ├── config/
│   │   ├── settings.toml           ← Master switches (paper/live, verticals on/off)
│   │   ├── exchanges.toml          ← ccxt credentials & routing
│   │   ├── risk.toml               ← Max drawdown, exposure limits, Kelly fraction
│   │   └── sports.toml             ← Books, sports, leagues to track
│   │
│   ├── engines/
│   │   ├── stocks/
│   │   │   ├── alpha_factory.py    ← qlib factor mining
│   │   │   ├── portfolio.py        ← PyPortfolioOpt strategies
│   │   │   ├── signals.py          ← alpha-vantage, FRED, EDGAR → signals
│   │   │   └── screener.py         ← multi-factor stock screener
│   │   ├── crypto/
│   │   │   ├── exchange.py         ← ccxt unified connector
│   │   │   ├── whale_tracker.py    ← networkx on-chain wallet graph
│   │   │   ├── strategy_runner.py  ← freqtrade strategy executor
│   │   │   └── market_maker.py     ← hummingbot controller
│   │   └── sports/
│   │       ├── odds_feed.py        ← OddsHarvester integration
│   │       ├── nba_model.py        ← NBA-ML XGBoost/NN wrapper
│   │       ├── kelly.py            ← Kelly criterion sizing
│   │       └── ev_calculator.py    ← Expected value across markets
│   │
│   ├── data/
│   │   ├── ingestion/
│   │   │   ├── alpha_vantage.py    ← Stock prices, fundamentals
│   │   │   ├── fred.py             ← Macro indicators
│   │   │   ├── edgar.py            ← SEC filings
│   │   │   └── crypto_feeds.py     ← Order books, liquidations, sentiment
│   │   ├── storage/
│   │   │   ├── sqlite.py           ← Local fast store
│   │   │   ├── s3.py               ← Cloud store
│   │   │   └── schema.py           ← Unified table definitions
│   │   └── transforms/
│   │       ├── features.py         ← polars feature engineering pipelines
│   │       └── normalizers.py      ← dask parallel normalization
│   │
│   ├── signals/
│   │   ├── aggregator.py           ← Combine stock + crypto + sports signals
│   │   ├── sentiment.py            ← NLP sentiment (transformers)
│   │   └── macro_filter.py         ← FRED macro regime gating (risk-off switch)
│   │
│   ├── risk/
│   │   ├── position_sizer.py       ← Kelly + PyPortfolioOpt combined sizing
│   │   ├── drawdown.py             ← Real-time drawdown monitor + circuit breaker
│   │   └── exposure.py             ← Cross-asset exposure limits
│   │
│   ├── execution/
│   │   ├── broker.py               ← Stock broker API (Alpaca/IBKR)
│   │   ├── exchange.py             ← Crypto execution via ccxt
│   │   └── sportsbook.py           ← Sportsbook API layer
│   │
│   ├── reporting/
│   │   ├── dashboard.py            ← Streamlit unified P&L dashboard (plotly)
│   │   ├── pnl_tracker.py          ← Cross-vertical P&L accounting
│   │   └── audit_log.py            ← Immutable trade log
│   │
│   └── orchestrator.py             ← Main loop: schedules engines, routes signals
│
├── strategies/                     ← User-editable, hot-reloadable strategy files
│   ├── stocks/momentum_alpha.py
│   ├── crypto/whale_follow.py
│   └── sports/nba_ev_kelly.py
│
├── notebooks/                      ← Research, backtests, model training
│   ├── stocks/
│   ├── crypto/
│   └── sports/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── backtests/
│
├── docs/plans/                     ← GSD design docs
├── scripts/
│   ├── daily_scan.py               ← Morning cron: refresh all signals
│   ├── backtest_runner.py          ← Run freqtrade/qlib backtests
│   └── retrain_models.py           ← Retrain NBA-ML + qlib models
│
├── pyproject.toml                  ← Single unified env, all deps
├── .env                            ← API keys (gitignored)
└── README.md
```

---

## Skill-to-Workflow Mapping

### Phase 0: Research & Hypothesis
- `scientific-brainstorming`, `hypothesis-generation`, `scientific-critical-thinking`
- Sources: `openalex-database`, `pubmed-database`, `biorxiv-database`, `bgpt-paper-search`

### Phase 1: Data Ingestion
- **Stocks:** `alpha-vantage`, `fred-economic-data`, `edgartools`, `usfiscaldata`, `hedgefundmonitor`
- **Crypto:** `ccxt`, `networkx`, `sentiment-analysis`
- **Sports:** OddsHarvester, NBA-ML
- **Biotech catalysts:** `clinicaltrials-database`, `fda-database`, `opentargets-database`

### Phase 2: Data Processing
- `polars` (primary), `dask` (parallel), `vaex` (out-of-core), `zarr-python` (storage), `statsmodels`

### Phase 3: Signal Generation
- All verticals: `scikit-learn`, `pytorch-lightning`, `timesfm-forecasting`, `statsmodels`, `pymc`, `shap`, `transformers`
- Sports only: `scikit-survival`, `statistical-analysis`

### Phase 4: Portfolio & Risk
- `PyPortfolioOpt`, `pymc`, `pymoo`, `statsmodels`

### Phase 5: Backtesting
- `qlib` (stocks), `freqtrade` (crypto), `statsmodels`, `shap`, `pm-data-analytics:ab-test-analysis`

### Phase 6: Execution
- `ccxt`, `freqtrade`, `hummingbot`, `modal` (cloud scheduling)

### Phase 7: Monitoring & Reporting
- `plotly`, `matplotlib`, `seaborn`, `scientific-visualization`
- `pm-data-analytics:metrics-dashboard`, `pm-data-analytics:cohort-analysis`

### Phase 8: Retraining Loop
- `pytorch-lightning`, `scikit-learn`, `timesfm-forecasting`, `modal`, `lamindb`

### GTM / Productization (parallel track)
- Strategy: `startup-canvas`, `value-proposition`, `north-star-metric`, `market-sizing`
- Revenue: `pricing-strategy`, `monetization-strategy`, `gtm-strategy`
- Growth: `programmatic-seo`, `ai-seo`, `content-strategy`, `social-content`
- Sales: `revops`, `sales-enablement`, `competitive-battlecard`, `cold-email`
- CRO: `signup-flow-cro`, `onboarding-cro`, `paywall-upgrade-cro`, `ab-test-setup`

### Blue Ocean Scientific SaaS (parallel track, post cash-flow)
- Drug discovery: `rdkit`, `deepchem`, `chembl-database`, `drugbank-database`, `torchdrug`
- Clinical: `pydicom`, `histolab`, `pathml`, `pyhealth`, `clinical-reports`
- Genomics: `biopython`, `scanpy`, `scvi-tools`, `cellxgene-census`
- Compliance: `iso-13485-certification`

---

## GSD Execution Framework

Wraps all phases:
- `gsd:new-project` → repo init
- `gsd:plan-phase` → sprint planning before each phase
- `gsd:execute-phase` → atomic commits during execution
- `gsd:add-tests` → test coverage per module
- `gsd:verify-work` → phase goal validation
- `gsd:audit-milestone` → milestone gate before release
- `gsd:debug` → systematic debugging
- `gsd:health` → ongoing project health

---

## Phased Build Timeline

| Month | Focus | Key Skills |
|---|---|---|
| 1–2 | Research + Data Layer | scientific-brainstorming, polars, dask, all data sources |
| 2–3 | Signal Generation + Backtesting | scikit-learn, timesfm, statsmodels, qlib, freqtrade |
| 3–4 | Risk + Execution | PyPortfolioOpt, pymc, ccxt, hummingbot, modal |
| 4+ | Monitoring + GTM | plotly, startup-canvas, gtm-strategy |
| Post cash-flow | Blue Ocean SaaS | rdkit, deepchem, iso-13485-certification |

---

## Key Design Decisions

1. **`alpha/` is the only code we write.** Cloned repos are dependencies, never modified.
2. **`engines/` are thin wrappers** translating each library into a uniform interface.
3. **`signals/aggregator.py` is the crown jewel** — a macro risk-off signal from FRED can pause all three verticals simultaneously.
4. **`risk/`** enforces cross-asset limits — if crypto hits max drawdown, sports bets also pause.
5. **`strategies/`** are hot-reloadable so alpha can be iterated without touching core engine code.
6. **`modal`** handles all cloud scheduling and GPU retraining — no local infrastructure needed.

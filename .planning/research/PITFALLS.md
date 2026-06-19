# Pitfalls Research: MLB Win Probability Model

## Critical Risks

1. **Target leakage:** season aggregates or rolling statistics that include the target game inflate results. Shift all histories before rolling and test train/live parity.
2. **Pitcher leakage:** using a starter announced after the historical prediction cutoff creates unavailable information. Record availability and use explicit fallbacks.
3. **Team-name mismatch:** MLB StatsAPI full names and pybaseball abbreviations can silently produce default features. Establish one canonical team ID map.
4. **Random train/test split:** baseball changes by season and time. Use expanding-window chronological validation only.
5. **Accuracy-only selection:** a 55% classifier can still emit bad probabilities. Select on Brier/log loss and calibration, then report accuracy.
6. **Legacy artifact mismatch:** the existing model loader accepts any recent pickle/json. Require metadata and exact feature-schema compatibility.
7. **Fake market edge:** current games carry `-110/-110` placeholders. Never calculate or display sportsbook edge unless real manual odds are present.
8. **Small-sample confidence:** cap or shrink extreme probabilities until out-of-time evidence supports them.

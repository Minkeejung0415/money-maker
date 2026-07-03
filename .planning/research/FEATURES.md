# Research: Feature Contract for WC Hybrid Route Offset

## Projected XI Inputs

Each team should expose role-strength features for high-leverage football roles:

- GK: shot-stopping, cross claim/sweeper behavior, continuity risk
- CB: aerial defense, box defense, buildup security
- FB: defensive isolation, crossing, overlap/underlap support
- DM: press resistance, ball recovery, central protection
- Winger: isolation threat, crossing/cutback creation, transition threat
- Striker: box presence, aerial threat, finishing pressure

## Coverage and Uncertainty

Every event-level feature payload should include:

- `projected_xi_source`
- `projected_xi_updated_at`
- `role_coverage`
- `missing_roles`
- `uncertainty_band`
- `role_strength_schema`
- `player_runtime_allowed`

Missing roles should shrink offsets toward zero rather than invent confidence. If critical roles are absent, the scanner should show research probabilities but suppress pick eligibility for the route-offset model.

## Tactical Duel Inputs

The first milestone should support only a narrow rule set:

- Wing isolation: winger strength versus opposing fullback/CB side support
- Aerial/set-piece mismatch: striker/CB aerial threat versus opponent aerial defense and GK claiming
- Press-vs-build: forward/wing/DM press pressure versus CB/DM buildup security

## Output Features

For each team:

- Baseline lambda
- Adjusted lambda
- Route deltas for center, wing, set-piece, counterattack
- Active duel IDs
- Cap-hit flags
- Missing-role reasons
- Uncertainty shrink factor

## Decision

Features should explain why xG moved, not just that win probability moved. The contract should make the route-offset layer auditable slate by slate.

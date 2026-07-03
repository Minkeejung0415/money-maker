# Research: Pitfalls for WC Hybrid Route Offset

## Main Risks

- Double counting: Elo, FIFA/SUM, xG strength, and player ratings can encode overlapping quality.
- Overfitting tactics: handcrafted duel rules can look smart on a few matchups and fail broadly.
- False precision: projected XI uncertainty can make small offsets appear more reliable than they are.
- Scoreline distortion: shifting lambdas can improve WDL while degrading BTTS or totals.
- Artifact mismatch: runtime code and promoted artifacts/config can disagree unless schema identity is checked.
- Stale inputs: projected XI and tactical assumptions can become wrong close to kickoff.

## Guardrails

- Treat hybrid as the prior and route offsets as small bounded deltas.
- Cap route and total xG movement.
- Shrink offsets when role coverage is weak.
- Require shadow-mode logs before promotion.
- Validate paired fixture-by-fixture, not as separate model runs on different samples.
- Track BTTS and O/U2.5 explicitly, because this milestone changes goal distribution surfaces.

## Anti-Goals

- Do not add player features directly into WDL classification.
- Do not promote because explanations sound plausible.
- Do not hide fallback to baseline under `player` or `auto`.
- Do not make route-offset picks eligible when projected XI source, age, or coverage is unknown.

## Decision

The most dangerous failure mode is plausible but unvalidated confidence. v2.4 should bias toward transparent shadow output and strict promotion gates.

# Market Mate Scanner Product Thesis

## Primary Thesis

Market Mate Scanner is a **decision-support and validation platform first**.

Its primary job is to:

- ingest fresh market data
- rank time-sensitive setups
- show whether the evidence is trustworthy enough to support action
- leave an auditable paper trail of what the operator saw and did
- prove or disprove whether the strategy has edge before automation expands

The product is **not** currently optimized around normal live trading.
Automation remains a guarded downstream capability that only earns more scope after the research loop and paper-trading loop are trustworthy.

## Primary User

The primary user is:

- a disciplined solo trader, researcher, or very small trading team
- willing to operate from a validation dashboard
- willing to review evidence before acting
- willing to run paper or dry-run workflows before risking capital

This is a narrower and more credible starting point than a mass-market retail trading app.

## Product Promise

The near-term promise is:

- better ranked decisions than raw watchlists
- clearer trust and readiness signals than typical scanner dashboards
- measurable feedback loops through validation, audit history, and journaling
- safer paper-trading support than jumping straight to automation

The product does **not** promise:

- certain profits
- turnkey live-trading alpha
- broker-grade portfolio truth
- regulation-safe consumer trading advice

## What Counts As Progress

Progress means improving one or more of these:

- friction-adjusted out-of-sample expectancy
- scan freshness and operational reliability
- clarity of the action workflow
- operator discipline and decision alignment
- commercial credibility for a paid decision-support product

Progress does **not** mean:

- adding more providers without proof
- adding more screens that do not improve decisions
- making the UI prettier before the workflow is trustworthy
- expanding live trading before paper evidence is mature

## Supported Product Boundary

The supported product boundary remains:

- `apps/web`
- `services/scanner`

The repository root Next.js app is legacy code and should not be treated as part of the primary product until a future product decision explicitly changes that.

## Default Strategic Posture

Until evidence improves materially, default to:

1. one primary strategy contract
2. one primary holding horizon
3. one primary buyer story
4. paper and dry-run workflows over live automation
5. evidence packs and recent-window validation as the main source of truth

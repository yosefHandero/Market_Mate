# Scope Guardrails

## Cut Now

- promoting new providers into the main scoring path without holdout evidence
- implying the scanner is already a proven live-trading engine
- treating the root Next.js app as part of the supported product
- building analytics views that do not improve decisions, validation, trust, or monetization

## Postpone

- broad live-trading rollout
- multi-tenant SaaS complexity before a monetization wedge is fixed
- major UI polish projects that do not improve operator workflow
- feature expansion across many asset classes or many strategy families
- advanced portfolio optimization before portfolio truth is stronger

## Simplify

- one primary strategy contract at a time
- one primary operating horizon at a time
- one primary buyer persona at a time
- one monetization path at a time
- one supported product boundary: `apps/web` plus `services/scanner`

## Keep As-Is For Now

- public and admin API separation
- readiness gating and fail-closed execution posture
- execution audit trail and idempotency
- validation dashboard and threshold sweep surfaces
- journaling as the operator-behavior capture layer

## Decision Rule

If a proposed feature does not clearly improve one of these, it should not outrank evidence work:

- profitability potential
- reliability
- trustworthiness
- operator discipline
- monetization credibility

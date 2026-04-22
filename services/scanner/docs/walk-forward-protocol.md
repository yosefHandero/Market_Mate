# Walk-Forward Protocol

This document defines the default walk-forward protocol for Market Mate Scanner.

## Purpose

The goal is to judge whether a scoring or threshold change survives a clean holdout window without re-tuning on the same evidence window.

## Default Windows

- `WF_TRAIN_DAYS`: earlier observations used for exploratory feature work
- `WF_HOLDOUT_DAYS`: most recent observations reserved for holdout evaluation
- `STRICT_WALKFORWARD=true`: only the holdout portion should be used for final judgment in the report request

## Required Sequence

1. Explore and tune on the train window only.
2. Freeze the threshold / scoring change.
3. Run holdout evaluation with `strict_walkforward=true`.
4. Review cohorts by signal, confidence bucket, age bucket, regime, and data grade.
5. Promote only if the stressed-friction view still holds and sample size is not underpowered.

## Minimum Review Questions

- Did expectancy remain positive after stressed friction?
- Did gated BUY and SELL cohorts keep enough evaluated samples?
- Did any regime or age bucket fail materially worse than the aggregate?
- Did acted-on rows outperform the all-signals baseline?

## Known Limitations

- Historical reconstruction of secondary providers is still incomplete.
- Walk-forward evidence should be treated as decision support, not a claim of durable alpha.

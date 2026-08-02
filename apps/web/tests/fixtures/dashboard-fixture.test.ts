import { describe, expect, it } from 'vitest';
import {
  getDashboardFixture,
  topResultsByAssetType,
} from '@/tests/fixtures/dashboard-fixture';
import {
  classifyReadinessState,
  computeTradeReadiness,
  readinessReasonChips,
} from '@/lib/readiness';

describe('dashboard fixture data', () => {
  it('covers major readiness states and reason-chip examples', () => {
    const fixture = getDashboardFixture();
    const decisionsBySymbol = new Map(
      fixture.decisions.map((decision) => [decision.symbol, decision]),
    );
    const stocks = fixture.latestScan.results.filter((row) => row.asset_type === 'stock');
    const crypto = fixture.latestScan.results.filter((row) => row.asset_type === 'crypto');

    expect(stocks.length).toBeGreaterThanOrEqual(3);
    expect(crypto.length).toBeGreaterThanOrEqual(3);

    const states = new Set(
      fixture.latestScan.results.map((row) => {
        const decision = decisionsBySymbol.get(row.ticker) ?? null;
        const readiness = computeTradeReadiness(row, decision, {
          automation: fixture.automation,
        });
        return classifyReadinessState(row, readiness, decision, {
          automation: fixture.automation,
        });
      }),
    );

    expect(states.has('ready')).toBe(true);
    expect(states.has('watch')).toBe(true);
    expect(states.has('review')).toBe(true);
    expect(states.has('blocked')).toBe(true);
    expect(states.has('system_issue')).toBe(true);
    expect(states.has('no_setup')).toBe(true);
    expect(states.has('sample_size')).toBe(true);

    const chipLabels = fixture.latestScan.results.flatMap((row) => {
      const decision = decisionsBySymbol.get(row.ticker) ?? null;
      const readiness = computeTradeReadiness(row, decision, {
        automation: fixture.automation,
      });
      return readinessReasonChips(row, readiness, decision, {
        automation: fixture.automation,
      }).map((chip) => chip.label);
    });

    expect(chipLabels).toContain('Signal HOLD');
    expect(chipLabels).toContain('Evidence low');
    expect(chipLabels).toContain('Provider critical');
    expect(chipLabels.some((label) => /^Bars \d+m stale$/.test(label))).toBe(true);
    expect(chipLabels).toContain('Sample size only');
  });

  it('exposes top-3 stock and crypto helpers', () => {
    const fixture = getDashboardFixture();
    expect(topResultsByAssetType(fixture.latestScan.results, 'stock')).toHaveLength(3);
    expect(topResultsByAssetType(fixture.latestScan.results, 'crypto')).toHaveLength(3);
  });
});

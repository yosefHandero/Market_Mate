'use client';

import { useCallback, useState } from 'react';
import type { ScanRun } from '@/lib/types';
import type { ConfidenceGrade, ProjectionWeek } from '@/lib/types';
import {
  fetchProjection,
  type RankBuySimulationOutput,
} from '@/lib/rank-buy-simulation';

interface Props {
  latestScan: ScanRun | null;
}

function formatCurrency(value: number) {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const WEEK_LABELS = ['Week 1', 'Week 2', 'Week 3', 'Week 4'];

const GRADE_COLORS: Record<ConfidenceGrade, string> = {
  A: '#22c55e',
  B: '#3b82f6',
  C: '#eab308',
  D: '#ef4444',
};

const GRADE_TOOLTIPS: Record<ConfidenceGrade, string> = {
  A: '30+ in-band samples with regime data',
  B: '15-29 in-band samples',
  C: 'Fell back to all signals of this type (< 15 in-band)',
  D: 'Fewer than 10 total samples — insufficient history',
};

function GradeBadge({ grade }: { grade: ConfidenceGrade }) {
  return (
    <span
      title={GRADE_TOOLTIPS[grade]}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 28,
        height: 28,
        borderRadius: 6,
        fontWeight: 700,
        fontSize: 14,
        color: '#fff',
        backgroundColor: GRADE_COLORS[grade],
        cursor: 'help',
      }}
    >
      {grade}
    </span>
  );
}

function ProjectionRow({
  label,
  weeks,
  accessor,
  colorClass,
}: {
  label: string;
  weeks: ProjectionWeek[];
  accessor: (w: ProjectionWeek) => number;
  colorClass: string;
}) {
  return (
    <tr>
      <td className="small" style={{ fontWeight: 600, paddingRight: 12, whiteSpace: 'nowrap' }}>
        {label}
      </td>
      {weeks.map((w) => {
        const val = accessor(w);
        const pnl = val - 100;
        return (
          <td key={w.week} style={{ textAlign: 'right', padding: '6px 8px' }}>
            <div style={{ fontWeight: 600, fontSize: 15 }}>{formatCurrency(val)}</div>
            <div className={`small ${colorClass}`} style={{ marginTop: 2 }}>
              {pnl >= 0 ? '+' : ''}{formatCurrency(pnl)} ({pnl >= 0 ? '+' : ''}{((pnl / 100) * 100).toFixed(2)}%)
            </div>
          </td>
        );
      })}
    </tr>
  );
}

export function RankBuySimulationPanel({ latestScan }: Props) {
  const [rankInput, setRankInput] = useState('1');
  const [output, setOutput] = useState<RankBuySimulationOutput | null>(null);
  const [loading, setLoading] = useState(false);

  const maxRank = latestScan?.results?.length ?? 0;

  const handleSimulate = useCallback(async () => {
    const parsed = Number(rankInput);
    if (rankInput.trim() === '' || Number.isNaN(parsed)) {
      setOutput({ ok: false, error: 'Enter a valid rank number.' });
      return;
    }
    setLoading(true);
    try {
      const result = await fetchProjection(parsed, latestScan);
      setOutput(result);
    } finally {
      setLoading(false);
    }
  }, [rankInput, latestScan]);

  const projection = output?.ok ? output.result : null;

  return (
    <section className="card">
      <h2 style={{ marginBottom: 4 }}>$100 Buy Simulation</h2>
      <p className="muted small" style={{ marginBottom: 14 }}>
        Evidence-based projection using historical signal outcomes with volatility decay.
      </p>

      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 14 }}>
        <div>
          <label className="form-label" htmlFor="rank-input">
            Rank (1–{maxRank || '?'})
          </label>
          <input
            id="rank-input"
            className="input"
            type="number"
            min={1}
            max={maxRank || undefined}
            step={1}
            value={rankInput}
            onChange={(e) => setRankInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSimulate(); }}
            style={{ width: 90 }}
          />
        </div>
        <button
          type="button"
          className="button"
          onClick={handleSimulate}
          disabled={maxRank === 0 || loading}
          style={{ width: 'auto', padding: '10px 18px' }}
        >
          {loading ? 'Loading…' : 'Simulate'}
        </button>
      </div>

      {output && !output.ok && (
        <p className="negative small" style={{ marginBottom: 8 }}>{output.error}</p>
      )}

      {projection && projection.confidence_grade === 'D' && (
        <div style={{ padding: '16px 14px', borderRadius: 8, background: 'var(--card-bg, #1a1a2e)', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <GradeBadge grade="D" />
            <strong className="small">Insufficient History</strong>
          </div>
          <p className="muted small" style={{ lineHeight: 1.55 }}>
            Not enough signal history yet. Keep scanning to build your evidence base.
          </p>
          {projection.sample_count > 0 && (
            <p className="muted small" style={{ marginTop: 6 }}>
              Only {projection.sample_count} evaluated sample{projection.sample_count !== 1 ? 's' : ''} available.
            </p>
          )}
        </div>
      )}

      {projection && projection.confidence_grade !== 'D' && projection.projections.length > 0 && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <GradeBadge grade={projection.confidence_grade} />
            <span className="small">
              <strong>{projection.ticker}</strong> · {projection.signal} · band {projection.score_band}
            </span>
            {projection.regime_adjusted && projection.regime && (
              <span className="muted small" style={{ marginLeft: 4 }}>
                (regime-adjusted: {projection.regime})
              </span>
            )}
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }} className="small muted" />
                  {projection.projections.map((w, i) => (
                    <th key={w.week} style={{ textAlign: 'right', padding: '6px 8px' }} className="small muted">
                      {WEEK_LABELS[i]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <ProjectionRow
                  label="Optimistic (P75)"
                  weeks={projection.projections}
                  accessor={(w) => w.optimistic_p75}
                  colorClass="positive"
                />
                <ProjectionRow
                  label="Median"
                  weeks={projection.projections}
                  accessor={(w) => w.median}
                  colorClass={projection.projections[0]?.median >= 100 ? 'positive' : 'negative'}
                />
                <ProjectionRow
                  label="Pessimistic (P25)"
                  weeks={projection.projections}
                  accessor={(w) => w.pessimistic_p25}
                  colorClass="negative"
                />
              </tbody>
            </table>
          </div>

          <p className="muted small" style={{ marginTop: 12, lineHeight: 1.55 }}>
            Based on {projection.sample_count} past {projection.signal} signal{projection.sample_count !== 1 ? 's' : ''} scoring {projection.score_band}
            {projection.low_sample_size && ' (broadened to all signal-level samples)'}.
          </p>

          <p className="muted small" style={{ marginTop: 6, lineHeight: 1.55 }}>
            {projection.disclaimer}
          </p>
        </div>
      )}
    </section>
  );
}

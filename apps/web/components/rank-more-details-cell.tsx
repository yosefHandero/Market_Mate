'use client';

import { useId, useRef } from 'react';
import type { ScanResult } from '@/lib/types';
import { newsBadgeClass, signalBadgeClass } from '@/components/rank-table-helpers';

export function RankMoreDetailsCell({ row }: { row: ScanResult }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  return (
    <td>
      <button
        type="button"
        className="rank-more-details-trigger"
        onClick={() => dialogRef.current?.showModal()}
      >
        (more details)
      </button>
      <dialog ref={dialogRef} className="rank-detail-dialog" aria-labelledby={titleId}>
        <div className="rank-detail-dialog-panel">
          <div className="rank-detail-dialog-header">
            <h2 id={titleId} className="rank-detail-dialog-title">
              {row.ticker}
            </h2>
            <button
              type="button"
              className="rank-detail-dialog-close"
              onClick={() => dialogRef.current?.close()}
              aria-label="Close"
            >
              ×
            </button>
          </div>
          <div className="rank-detail-dialog-body">
            <section className="rank-detail-section">
              <h3 className="rank-detail-section-title">Rel Vol</h3>
              <p>{row.relative_volume.toFixed(2)}x</p>
            </section>
            <section className="rank-detail-section">
              <h3 className="rank-detail-section-title">Options</h3>
              <div className="grid">
                <span className={`badge ${row.options_flow_bullish ? 'green' : 'amber'}`}>
                  Flow {row.options_flow_score.toFixed(1)}
                </span>
                <span className="badge">P/C {row.options_call_put_ratio.toFixed(2)}</span>
              </div>
            </section>
            <section className="rank-detail-section">
              <h3 className="rank-detail-section-title">Flags</h3>
              <div className="grid">
                <span className={`badge ${signalBadgeClass(row.signal_label)}`}>
                  {row.signal_label.toUpperCase()}
                </span>
                <span className="badge">Evidence quality: {row.evidence_quality}</span>
                <span
                  className={`badge ${row.execution_eligibility === 'eligible' ? 'green' : row.execution_eligibility === 'review' ? 'amber' : ''}`}
                >
                  Eligibility: {row.execution_eligibility}
                </span>
                <span
                  className={`badge ${row.provider_status === 'ok' ? 'green' : row.provider_status === 'critical' ? 'negative' : 'amber'}`}
                >
                  Provider: {row.provider_status}
                </span>
                <span className={`badge ${newsBadgeClass(row.news_source)}`}>News: {row.news_source}</span>
                {row.breakout_flag && <span className="badge blue">Breakout</span>}
                {row.filing_flag && <span className="badge amber">SEC filing</span>}
                {row.alert_sent && <span className="badge green">Telegram</span>}
              </div>
            </section>
            <section className="rank-detail-section">
              <h3 className="rank-detail-section-title">Why it is interesting</h3>
              <div style={{ display: 'grid', gap: 6 }}>
                <span>{row.explanation}</span>
                <span className="muted">
                  Horizon {row.strategy_primary_horizon} | Entry: {row.strategy_entry_assumption}
                </span>
                <span className="muted">Exit: {row.strategy_exit_assumption}</span>
                {row.news_cache_label && <span className="muted">{row.news_cache_label}</span>}
                <span className="muted">{row.options_flow_summary}</span>
              </div>
            </section>
          </div>
        </div>
      </dialog>
    </td>
  );
}

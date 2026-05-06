'use client';

import { useId, useState, type KeyboardEvent, type MouseEvent, type FocusEvent } from 'react';
import { formatReadiness, type ReadinessProjection, type TradeReadiness } from '@/lib/readiness';

const PROJECTION_COPY: Record<ReadinessProjection, string> = {
  stable: 'Likely stable if data freshness stays OK.',
  improving_possible: 'Likely to improve if review clears or sample size grows.',
  decaying: 'Likely to decay if bars stay stale or provider stays degraded.',
  blocked_until_sample_size:
    'Likely to improve as the sample-size gate accumulates outcomes.',
  kill_switch_or_breaker: 'Will stay 0 while kill switch / breaker is active.',
};

function toneLabel(tone: TradeReadiness['tone']): string {
  if (tone === 'high') return 'High';
  if (tone === 'watch') return 'Watch';
  if (tone === 'low') return 'Low';
  return 'None';
}

function stopEvent(event: MouseEvent | KeyboardEvent | FocusEvent) {
  event.stopPropagation();
}

export function readinessProjectionText(projection: ReadinessProjection): string {
  return PROJECTION_COPY[projection];
}

export function ReadinessPopover({
  readiness,
  focusable = true,
  showLabel = true,
}: {
  readiness: TradeReadiness;
  focusable?: boolean;
  showLabel?: boolean;
}) {
  const panelId = useId();
  const [open, setOpen] = useState(false);

  const close = () => setOpen(false);
  const openPanel = () => setOpen(true);

  return (
    <span
      className="readiness-popover"
      onMouseEnter={openPanel}
      onMouseLeave={close}
      onFocus={openPanel}
      onBlur={close}
      onClick={stopEvent}
      onKeyDown={(event) => {
        stopEvent(event);
        if (event.key === 'Escape') {
          close();
        }
      }}
    >
      <button
        type="button"
        className="readiness-popover-trigger"
        aria-describedby={panelId}
        aria-expanded={open}
        tabIndex={focusable ? 0 : -1}
      >
        {showLabel ? <span className="muted small">Readiness</span> : null}
        <strong className={`readiness-score readiness-score-${readiness.tone}`}>
          {formatReadiness(readiness.score)}
        </strong>
      </button>
      <span
        id={panelId}
        role="tooltip"
        className="readiness-popover-panel"
        data-open={open ? 'true' : 'false'}
      >
        {open ? (
          <>
            <span className="readiness-popover-header">
              <strong>{formatReadiness(readiness.score)}</strong>
              <span className="badge">{toneLabel(readiness.tone)}</span>
            </span>
            <span className="small">{readiness.reason}</span>
            <span className="readiness-factor-list">
              {readiness.factors.map((factor) => (
                <span className="readiness-factor" key={factor.key}>
                  <span className="readiness-factor-top">
                    <span>{factor.label}</span>
                    <span>{Math.round(factor.score)}%</span>
                  </span>
                  <svg
                    aria-hidden="true"
                    className="readiness-factor-bar"
                    focusable="false"
                    viewBox="0 0 100 6"
                  >
                    <rect width="100" height="6" rx="3" className="readiness-factor-track" />
                    <rect
                      width={Math.max(0, Math.min(100, factor.score))}
                      height="6"
                      rx="3"
                      className="readiness-factor-fill"
                    />
                  </svg>
                  <span className="muted">{factor.reason}</span>
                </span>
              ))}
            </span>
            <span className="muted small">{readinessProjectionText(readiness.projection)}</span>
          </>
        ) : null}
      </span>
    </span>
  );
}

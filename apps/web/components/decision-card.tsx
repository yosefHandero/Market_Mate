'use client';

import {
  cardColor,
  cardColorClass,
  confidenceScore,
  dataQualityLabel,
  evidenceGrade,
  formatEstimatedExit,
  formatExpectedGrowthWindow,
  formatInvalidationLevel,
  formatProjectedRange,
  formatUpsideProbability,
  isLiveForwardProven,
  patternName,
  provenanceLabel,
  resolveExitWindow,
  riskLevel,
  topReasons,
} from '@/lib/decision-presentation';
import { formatPaperSizing, recommendedActionLine } from '@/lib/paper-order';
import { SIGNAL_DECISION_SUPPORT_DISCLAIMER } from '@/lib/signal-copy';
import { usePaperOrder } from '@/lib/use-paper-order';
import type { AutomationStatusResponse, DecisionRow, ScanResult } from '@/lib/types';

function formatCurrency(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function DecisionCard({
  result,
  decision,
  automation,
  onPaperOrderPlaced,
}: {
  result: ScanResult;
  decision?: DecisionRow | null;
  automation?: AutomationStatusResponse | null;
  onPaperOrderPlaced?: (auditId: number | null) => void | Promise<void>;
}) {
  const {
    setup,
    preview,
    receipt,
    error,
    busy,
    actionGate,
    canAct,
    previewEnabled,
    placeEnabled,
    recommendedAction,
    runPreview,
    runPlace,
  } = usePaperOrder({ result, decision, automation, onPlaced: onPaperOrderPlaced });

  const blocked = actionGate.blocked;
  const color = cardColor(blocked);
  const reasons = topReasons(result, decision);
  const grade = evidenceGrade(result, decision);
  const risk = riskLevel(result, decision);
  const upside = formatUpsideProbability(result, decision);
  const confidence = confidenceScore(result, decision);
  const dataQuality = dataQualityLabel(result, decision);
  const pattern = patternName(result, decision);
  const exitWindow = resolveExitWindow(result, decision);
  const liveProven = isLiveForwardProven(result, decision);
  const provenance = provenanceLabel(result, decision);
  const sizing = formatPaperSizing(setup);
  const previewDisabledReason = !previewEnabled
    ? actionGate.reason.replace(/^Blocked:\s*/i, '')
    : undefined;

  return (
    <article
      className={cardColorClass(color)}
      aria-label={`${result.ticker} buy candidate card`}
      data-testid={`decision-card-${result.ticker}`}
      data-color={color}
    >
      <header className="decision-card-header">
        <div>
          <h3 className="decision-card-symbol">{result.ticker}</h3>
          <p className="muted small decision-card-asset-type">
            {result.asset_type === 'crypto' ? 'Crypto' : 'Stock'}
          </p>
        </div>
        <span
          className={`badge ${liveProven ? 'green' : ''}`.trim()}
          data-testid="evidence-provenance"
          title="Whether this candidate has live paper-forward evidence or only historical evidence."
        >
          {provenance}
        </span>
      </header>

      <div className="decision-card-metrics">
        <div>
          <span className="muted small">Upside probability</span>
          <strong data-testid="upside-probability">{upside}</strong>
        </div>
        <div>
          <span className="muted small">Confidence</span>
          <strong data-testid="confidence-score">{confidence}</strong>
        </div>
        <div>
          <span className="muted small">Data quality</span>
          <strong data-testid="data-quality">{dataQuality}</strong>
        </div>
        <div>
          <span className="muted small">Price</span>
          <strong data-testid="current-price">{formatCurrency(result.price)}</strong>
        </div>
      </div>

      <p className="muted small decision-card-pattern" data-testid="pattern-name">
        Pattern: {pattern} · Evidence {grade} · Risk {risk}
      </p>

      <div className="decision-card-reasons" data-testid="decision-reasons">
        <p className="muted small" style={{ margin: '0 0 4px' }}>
          Why (historical pattern evidence)
        </p>
        {reasons.length ? (
          <ul className="decision-reason-list">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        ) : (
          <p className="muted small" style={{ margin: 0 }}>
            No short reasons available.
          </p>
        )}
      </div>

      <div className="decision-card-prediction muted small" data-testid="exit-window-block">
        <p className="small" style={{ margin: '0 0 4px', fontWeight: 600 }}>
          When to consider exiting
        </p>
        <p style={{ margin: '0 0 4px' }} data-testid="expected-growth-window">
          {formatExpectedGrowthWindow(exitWindow)}
        </p>
        <p style={{ margin: '0 0 4px' }} data-testid="estimated-exit">
          {formatEstimatedExit(exitWindow)}
        </p>
        <p style={{ margin: '0 0 4px' }} data-testid="projected-range">
          {formatProjectedRange(exitWindow)}
        </p>
        <p style={{ margin: '0 0 4px' }} data-testid="invalidation-level">
          {formatInvalidationLevel(exitWindow)}
        </p>
        {exitWindow?.stop_growing_signal ? (
          <p style={{ margin: '0 0 4px' }} data-testid="stop-growing-signal">
            {exitWindow.stop_growing_signal}
          </p>
        ) : null}
        {exitWindow?.stop_growing_conditions?.length ? (
          <ul className="decision-reason-list" data-testid="stop-growing-conditions">
            {exitWindow.stop_growing_conditions.map((condition) => (
              <li key={condition}>{condition}</li>
            ))}
          </ul>
        ) : null}
        {exitWindow?.risk_warning ? (
          <p className="negative small" style={{ margin: '4px 0 0' }} data-testid="risk-warning">
            {exitWindow.risk_warning}
          </p>
        ) : null}
        {exitWindow?.confidence_change_note ? (
          <p style={{ margin: '4px 0 0' }} data-testid="confidence-change-note">
            {exitWindow.confidence_change_note}
          </p>
        ) : null}
      </div>

      <div className="decision-card-sizing muted small">
        <p style={{ margin: '0 0 4px' }}>
          <span className="muted">Paper size (default):</span> {sizing.notionalLabel}
        </p>
        <p style={{ margin: '0 0 4px' }}>
          <span className="muted">Stop:</span> {sizing.stopLabel}
        </p>
        <p style={{ margin: 0 }}>
          <span className="muted">Exit target:</span> {sizing.targetLabel}
        </p>
      </div>

      <p
        className={`decision-card-blocked small${blocked ? ' negative' : ' muted'}`}
        data-testid="blocked-reason"
      >
        {actionGate.reason}
      </p>

      <p className="muted small decision-card-action-line">
        {recommendedActionLine(recommendedAction, result.decision_signal)}
      </p>

      <div className="decision-card-actions">
        <button
          type="button"
          className="button button-primary"
          onClick={() => void runPreview()}
          disabled={!previewEnabled}
          aria-disabled={!previewEnabled}
          title={previewDisabledReason}
          aria-label={
            previewDisabledReason
              ? `Preview unavailable: ${previewDisabledReason}`
              : 'Preview paper trade'
          }
        >
          {busy === 'preview' ? 'Previewing...' : 'Preview Paper Trade'}
        </button>
        {canAct && preview ? (
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void runPlace()}
            disabled={!placeEnabled}
          >
            {busy === 'place' ? 'Placing...' : 'Place Dry Run'}
          </button>
        ) : null}
      </div>

      {preview ? (
        <details className="ui-disclosure decision-card-preview">
          <summary className="ui-disclosure-summary muted small">Preview details</summary>
          <div className="decision-card-preview-body small">
            <div>
              <span className="muted">Gate:</span> {preview.gate_result ?? 'unknown'}
            </div>
            <div>
              <span className="muted">Freshness:</span> {preview.freshness ?? 'unknown'}
            </div>
            <div>
              <span className="muted">Est. cost:</span> {formatCurrency(preview.notional_estimate)}
            </div>
            {(preview.reject_reasons?.length ?? 0) > 0 ? (
              <div className="negative">
                Reject: {preview.reject_reasons.join(' | ')}
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {receipt ? (
        <details className="ui-disclosure decision-card-receipt" open>
          <summary className="ui-disclosure-summary muted small">Dry-run receipt</summary>
          <div className="decision-card-receipt-body small">
            <div>
              <span className="muted">Status:</span>{' '}
              <span className={receipt.ok ? 'positive' : 'negative'}>
                {receipt.ok ? 'recorded' : 'blocked'}
              </span>
            </div>
            <div>
              <span className="muted">Ledger id:</span> {receipt.ledger_id ?? '--'}
            </div>
            <div>
              <span className="muted">Audit id:</span> {receipt.execution_audit_id ?? '--'}
            </div>
          </div>
        </details>
      ) : null}

      {error ? <p className="negative small">{error}</p> : null}

      <p className="muted small decision-card-disclaimer">
        Paper only. {SIGNAL_DECISION_SUPPORT_DISCLAIMER}
      </p>
    </article>
  );
}

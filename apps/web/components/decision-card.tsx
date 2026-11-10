'use client';

import Link from 'next/link';
import {
  cardColor,
  cardColorClass,
  confidenceScore,
  dataQualityLabel,
  isLiveForwardProven,
  provenanceLabel,
} from '@/lib/decision-presentation';
import { formatPaperSizing, recommendedActionLine } from '@/lib/paper-order';
import { forecastAnchor, formatHoldingDuration, formatPaperTimestamp, formatUnitPrice } from '@/lib/paper-contract';
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

function Metric({
  label,
  value,
  testId,
}: {
  label: string;
  value: string | number;
  testId: string;
}) {
  return (
    <div className="decision-card-metric">
      <span className="muted small decision-card-metric-label">{label}</span>{' '}
      <strong className="decision-card-metric-value" data-testid={testId}>
        {value}
      </strong>
    </div>
  );
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
    placed,
    recommendedAction,
    runPreview,
    runPlace,
  } = usePaperOrder({ result, decision, automation, onPlaced: onPaperOrderPlaced });

  const blocked = actionGate.blocked;
  const color = cardColor(blocked);
  const confidence = confidenceScore(result, decision);
  const dataQuality = dataQualityLabel(result, decision);
  const liveProven = isLiveForwardProven(result, decision);
  const provenance = provenanceLabel(result, decision);
  const sizing = formatPaperSizing(setup);
  const contract = receipt?.paper_contract ?? preview?.paper_contract;
  const blockedReason = actionGate.reason.replace(/^Blocked:\s*/i, '');
  // Only a real gate block is a "reason"; a busy request is not.
  const previewDisabledReason = !canAct ? blockedReason : undefined;

  return (
    <article
      className={cardColorClass(color)}
      aria-label={`${result.ticker} buy candidate`}
      data-testid={`decision-card-${result.ticker}`}
      data-color={color}
    >
      <div className="candidate-row">
        <div className="candidate-summary">
          <strong className="candidate-symbol">{result.ticker}</strong>
          <span data-testid="current-price">{formatUnitPrice(result.price)}</span>
          <span className="candidate-field">
            <span className="muted">Confidence </span>
            <span data-testid="confidence-score">{confidence}/100</span>
          </span>
          <span data-testid="paper-exit-method">
            Time-based paper exit{contract ? `: ${formatHoldingDuration(contract.holding_duration_seconds)}` : ''}
          </span>
          {blocked ? (
            <>
              <span className="badge red" data-testid="actionability-status">
                Blocked
              </span>
              <span className="negative candidate-blocked-reason" data-testid="blocked-reason">
                {blockedReason}
              </span>
            </>
          ) : null}
        </div>
        <details className="candidate-details" data-testid="candidate-details">
          <summary className="candidate-details-summary">Details</summary>
          <div className="candidate-details-body">
      <div className="decision-card-header-badges">
        <span
          className={`badge ${blocked ? 'amber' : 'green'}`}
          data-testid={blocked ? undefined : 'actionability-status'}
        >
          {blocked ? 'Read-only setup' : 'Paper preview eligible'}
        </span>
        <span
          className={`badge ${liveProven ? 'green' : ''}`.trim()}
          data-testid="evidence-provenance"
          title="Whether this candidate has live paper-forward evidence or only historical evidence."
        >
          {provenance}
        </span>
      </div>

      <div className="decision-card-metrics">
        <Metric label="Data quality" value={dataQuality} testId="data-quality" />
      </div>

      <div className="decision-card-prediction muted small" data-testid="exit-window-block">
        <p style={{ margin: '0 0 4px' }}>
          {contract
            ? `Closes after ${formatHoldingDuration(contract.holding_duration_seconds)} from the actual simulated fill, when a valid quote is available.`
            : 'Holding duration is confirmed in preview and frozen when placed. Closure uses a valid quote after the saved deadline.'}
        </p>
        <p style={{ margin: '0 0 4px' }}>
          No active stop or target orders. Weekly probability and ranges are advisory context;
          they do not describe the one-hour paper outcome.
        </p>
        <p style={{ margin: 0 }}>
          <Link href={`/proof#${forecastAnchor(result.ticker)}`} data-testid="forecast-proof-link">
            See signal reasons, confidence inputs and advisory forecasts on Proof
          </Link>
        </p>
      </div>

      <div className="decision-card-sizing muted small">
        <p style={{ margin: '0 0 4px' }}>
          <span className="muted">Paper size:</span>{' '}
          {preview ? `${preview.qty} units; ${formatCurrency(preview.notional_estimate)} estimated notional` : sizing.notionalLabel}
        </p>
      </div>

      <p className="muted small decision-card-action-line">
        {recommendedActionLine(recommendedAction, result.decision_signal)}
      </p>

      {blocked ? (
        <details
          className="ui-disclosure decision-card-setup-details"
          data-testid="setup-details"
        >
          <summary className="ui-disclosure-summary muted small">View setup details</summary>
          <div className="decision-card-setup-details-body small">
            <p>Paper preview is unavailable for this setup.</p>
            <p>
              <span className="muted">Reason:</span> {blockedReason}
            </p>
            <p>
              <span className="muted">Recommended action:</span>{' '}
              {recommendedActionLine(recommendedAction, result.decision_signal)}
            </p>
          </div>
        </details>
      ) : (
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
              aria-disabled={!placeEnabled}
              title={placed ? 'Dry run already recorded. Preview again to place another.' : undefined}
            >
              {busy === 'place' ? 'Placing...' : placed ? 'Dry Run Recorded' : 'Place Dry Run'}
            </button>
          ) : null}
        </div>
      )}

      {!blocked && preview ? (
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
            <div>
              <span className="muted">Agreed exit:</span>{' '}
              {preview.paper_contract ? `Time-based; ${formatHoldingDuration(preview.paper_contract.holding_duration_seconds)} from fill` : 'Contract unavailable; preview again after updating the scanner.'}
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
            {receipt.ok ? (
              <>
                <div><span className="muted">Actual simulated fill:</span> {formatUnitPrice(receipt.fill_price)} at {formatPaperTimestamp(receipt.filled_at)}</div>
                <div><span className="muted">Saved exit deadline:</span> {formatPaperTimestamp(receipt.exit_due_at)}</div>
              </>
            ) : null}
            {receipt.ok ? (
              <div>
                <Link href="/proof#paper-ledger" data-testid="receipt-ledger-link">
                  Track this position in the Proof ledger
                </Link>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {error ? <p className="negative small">{error}</p> : null}

      <p className="muted small decision-card-disclaimer">
        Paper only. {SIGNAL_DECISION_SUPPORT_DISCLAIMER}
      </p>
          </div>
        </details>
      </div>
    </article>
  );
}

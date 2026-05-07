'use client';

import { useEffect, useMemo, useState } from 'react';
import { ReadinessPopover, readinessProjectionText } from '@/components/readiness-popover';
import { createJournalEntry } from '@/lib/api';
import { buildCoinbaseLink } from '@/lib/coinbase-link';
import { computeTradeReadiness } from '@/lib/readiness';
import { placeOrder, previewOrder } from '@/lib/trading-desk';
import type {
  AutomationStatusResponse,
  DecisionRow,
  OrderPlaceResponse,
  OrderPreviewRequest,
  OrderPreviewResponse,
  ScanResult,
} from '@/lib/types';

function formatCurrency(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatQuantity(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return '--';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}

function rounded(value: number) {
  return Math.round(value * 10_000) / 10_000;
}

export function buildDryRunSetup(result: ScanResult): OrderPreviewRequest {
  const side = result.decision_signal === 'SELL' ? 'sell' : 'buy';
  const entry = Math.max(0.01, result.price);
  const qty = Math.max(0.000001, Math.round((100 / entry) * 1_000_000) / 1_000_000);
  const stop = side === 'sell' ? entry * 1.01 : entry * 0.99;
  const target = side === 'sell' ? entry * 0.98 : entry * 1.02;

  return {
    ticker: result.ticker,
    side,
    qty,
    order_type: 'market',
    mode: 'dry_run',
    entry_price: rounded(entry),
    stop_price: rounded(stop),
    target_price: rounded(target),
    recommended_action_snapshot: result.recommended_action ?? null,
  };
}

function selectableAction(action: string | null | undefined) {
  return action === 'preview' || action === 'dry_run';
}

function cleanDetail(value: string | null | undefined) {
  const trimmed = value?.trim();
  if (!trimmed || trimmed.toLowerCase() === 'passed') return null;
  return trimmed;
}

function humanizeKey(value: string) {
  return value.replace(/_/g, ' ');
}

function firstUnique(items: Array<string | null | undefined>) {
  const seen = new Set<string>();
  return items.flatMap((item) => {
    const trimmed = cleanDetail(item);
    if (!trimmed || seen.has(trimmed)) return [];
    seen.add(trimmed);
    return [trimmed];
  });
}

function formatFreshnessFlags(flags: Record<string, string> | null | undefined) {
  const entries = Object.entries(flags ?? {}).filter(([, value]) => cleanDetail(value));
  if (!entries.length) return null;
  return entries.map(([key, value]) => `${humanizeKey(key)}: ${value}`).join(' | ');
}

function disabledPreviewContext({
  action,
  result,
  decision,
}: {
  action: string | null | undefined;
  result: ScanResult;
  decision?: DecisionRow | null;
}) {
  const actionLabel = action ?? 'missing';
  const failedGate = result.gate_checks.find((check) => !check.passed);
  const reasonCandidates = firstUnique([
    result.gate_reason,
    failedGate?.detail,
    result.evidence_quality_reasons[0],
    decision?.evidence_quality_reasons[0],
  ]);
  const details = reasonCandidates.slice(0, 2).map((reason) => `Reason: ${reason}`);

  if (failedGate && !reasonCandidates.includes(failedGate.detail)) {
    details.push(`Gate check: ${humanizeKey(failedGate.name)} - ${failedGate.detail}`);
  }

  const providerStatus = result.provider_status || decision?.provider_status;
  if (providerStatus && providerStatus !== 'ok' && providerStatus !== 'unknown') {
    const warnings = result.provider_warnings.length
      ? ` (${result.provider_warnings.map(humanizeKey).join(', ')})`
      : '';
    details.push(`Provider: ${providerStatus}${warnings}`);
  } else if (result.provider_warnings.length) {
    details.push(`Provider: ${result.provider_warnings.map(humanizeKey).join(', ')}`);
  }

  const freshness = formatFreshnessFlags(result.freshness_flags ?? decision?.freshness_flags);
  if (freshness) {
    details.push(`Freshness: ${freshness}`);
  }

  if (!details.length && action === 'ignore') {
    details.push(`Reason: ${result.decision_signal} signal has no paper-trading action.`);
  }

  return {
    headline: `Preview is disabled because the recommended action is ${actionLabel}.`,
    details,
  };
}

function makeOrderKey(result: ScanResult) {
  return `dashboard-paper-${result.asset_type}-${result.ticker}-${result.decision_signal.toLowerCase()}-${Date.now()}`;
}

export function PaperTradingLoop({
  selectedResult,
  selectedDecision,
  onPaperOrderPlaced,
  automation,
}: {
  selectedResult: ScanResult | null;
  selectedDecision?: DecisionRow | null;
  onPaperOrderPlaced: (auditId: number | null) => void | Promise<void>;
  automation?: AutomationStatusResponse | null;
}) {
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null);
  const [receipt, setReceipt] = useState<OrderPlaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [journalMessage, setJournalMessage] = useState<{
    tone: 'positive' | 'negative';
    message: string;
  } | null>(null);
  const [busy, setBusy] = useState<'preview' | 'place' | null>(null);
  const [orderKey, setOrderKey] = useState<string | null>(null);
  const [takeNote, setTakeNote] = useState('');

  const setup = useMemo(
    () => (selectedResult ? buildDryRunSetup(selectedResult) : null),
    [selectedResult],
  );
  const recommendedAction =
    selectedDecision?.recommended_action ?? selectedResult?.recommended_action ?? null;
  const tradeReadiness = selectedResult
    ? computeTradeReadiness(selectedResult, selectedDecision ?? null, { automation })
    : null;
  const coinbaseLink = selectedResult
    ? buildCoinbaseLink(selectedResult.ticker, selectedResult.asset_type)
    : null;
  const previewEnabled = Boolean(setup && selectableAction(recommendedAction) && busy == null);
  const placeEnabled = Boolean(
    preview && setup && orderKey && preview.gate_result !== 'blocked' && busy == null,
  );
  const disabledContext = selectedResult
    ? disabledPreviewContext({
        action: recommendedAction,
        result: selectedResult,
        decision: selectedDecision,
      })
    : null;

  useEffect(() => {
    setPreview(null);
    setReceipt(null);
    setError(null);
    setJournalMessage(null);
    setOrderKey(null);
    setTakeNote('');
  }, [selectedResult?.asset_type, selectedResult?.decision_signal, selectedResult?.ticker]);

  const runPreview = async () => {
    if (!setup || !previewEnabled) return;
    setBusy('preview');
    setError(null);
    setJournalMessage(null);
    setReceipt(null);
    setPreview(null);
    setOrderKey(null);

    try {
      const result = await previewOrder({
        ...setup,
        recommended_action_snapshot: recommendedAction,
      });
      setPreview(result);
      if (selectedResult) {
        setOrderKey(makeOrderKey(selectedResult));
      }
    } catch (caught) {
      setPreview(null);
      setOrderKey(null);
      setError(caught instanceof Error ? caught.message : 'Preview failed.');
    } finally {
      setBusy(null);
    }
  };

  const runPlace = async () => {
    if (!setup || !preview || !orderKey || !placeEnabled) return;
    setBusy('place');
    setError(null);
    setJournalMessage(null);

    try {
      const result = await placeOrder({
        ...setup,
        qty: preview.qty,
        preview_audit_id: preview.execution_audit_id,
        idempotency_key: orderKey,
        dry_run: true,
        recommended_action_snapshot: recommendedAction,
      });
      const duplicateReceipt =
        receipt != null &&
        receipt.execution_audit_id === result.execution_audit_id &&
        receipt.ledger_id === result.ledger_id &&
        receipt.idempotency_key === result.idempotency_key;
      setReceipt(result);
      if (!duplicateReceipt) {
        await onPaperOrderPlaced(result.execution_audit_id ?? null);
        const note = takeNote.trim();
        if (note && selectedResult) {
          try {
            await createJournalEntry({
              ticker: selectedResult.ticker,
              run_id: null,
              decision: 'took',
              entry_price: result.fill_price ?? setup.entry_price ?? preview.entry_price,
              exit_price: null,
              pnl_pct: null,
              notes: note,
              signal_label: selectedResult.signal_label || null,
              score: Number.isFinite(selectedResult.score) ? selectedResult.score : null,
              news_source: selectedResult.news_source || null,
              override_reason: note,
              action_state: 'took',
            });
            setJournalMessage({ tone: 'positive', message: 'Journal note saved.' });
          } catch {
            setJournalMessage({ tone: 'negative', message: 'Journal note was not saved.' });
          }
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Dry-run placement failed.');
    } finally {
      setBusy(null);
    }
  };

  const scrollToLedger = () => {
    document.getElementById('paper-ledger')?.scrollIntoView({ behavior: 'smooth' });
  };

  if (!selectedResult || !setup) {
    return (
      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Paper Trading Loop</h2>
        <p className="muted" style={{ margin: 0 }}>
          Select a ranked opportunity to begin.
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 style={{ marginBottom: 8 }}>Paper Trading Loop</h2>
      {tradeReadiness ? (
        <div
          className="desk-readiness-hero"
          style={{
            marginBottom: 16,
            padding: '14px 16px',
            borderRadius: 8,
            border: '1px solid var(--border, rgba(255,255,255,0.12))',
            background: 'var(--surface-elevated, rgba(0,0,0,0.2))',
          }}
        >
          <div className="muted small" style={{ marginBottom: 4 }}>
            Readiness
          </div>
          <div style={{ marginTop: 4 }}>
            <ReadinessPopover readiness={tradeReadiness} showLabel={false} />
          </div>
          <div className="muted small" style={{ marginTop: 10 }}>
            <span className="muted">Action:</span> <strong>{recommendedAction ?? 'none'}</strong>
          </div>
          <div className="muted small" style={{ marginTop: 6 }}>
            <span className="muted">Reason:</span> {tradeReadiness.reason}
          </div>
          <div className="muted small" style={{ marginTop: 6 }}>
            <span className="muted">Projection:</span>{' '}
            {readinessProjectionText(tradeReadiness.projection)}
          </div>
        </div>
      ) : null}
      <div className="desk-summary-grid">
        <div className="desk-kpi desk-kpi-primary">
          <div className="kpi-label">Decision</div>
          <div className="kpi-value">{selectedResult.ticker}</div>
          <div className="muted small">
            {selectedResult.decision_signal} | {recommendedAction ?? 'no action'}
          </div>
        </div>
        <div className="desk-kpi">
          <div className="kpi-label">Entry</div>
          <div className="kpi-value">{formatCurrency(setup.entry_price ?? null)}</div>
          <div className="muted small">Qty {formatQuantity(setup.qty)}</div>
        </div>
        <div className="desk-kpi">
          <div className="kpi-label">Stop / Target</div>
          <div className="kpi-value">{formatCurrency(setup.stop_price ?? null)}</div>
          <div className="muted small">Target {formatCurrency(setup.target_price ?? null)}</div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 16 }}>
        <button type="button" className="button" onClick={runPreview} disabled={!previewEnabled}>
          {busy === 'preview' ? 'Previewing...' : 'Preview'}
        </button>
        <button type="button" className="button" onClick={runPlace} disabled={!placeEnabled}>
          {busy === 'place' ? 'Placing...' : 'Place dry run'}
        </button>
        {coinbaseLink?.available && coinbaseLink.href ? (
          <a className="button" href={coinbaseLink.href} target="_blank" rel="noopener noreferrer">
            {coinbaseLink.label}
          </a>
        ) : (
          <span className="muted small" style={{ alignSelf: 'center' }}>
            {coinbaseLink?.reason ?? 'Coinbase link unavailable.'}
          </span>
        )}
      </div>
      <p className="muted small" style={{ marginTop: 8, marginBottom: 0 }}>
        Manual navigation only. The app does not place orders on Coinbase.
      </p>

      {selectableAction(recommendedAction) ? (
        <div style={{ marginTop: 16 }}>
          <label className="form-label" htmlFor="paper-take-note">
            Why I took this (optional)
          </label>
          <textarea
            id="paper-take-note"
            className="textarea"
            rows={3}
            value={takeNote}
            onChange={(event) => setTakeNote(event.target.value)}
            placeholder="Quick note for the journal..."
            maxLength={2000}
          />
        </div>
      ) : null}

      {!selectableAction(recommendedAction) ? (
        <div className="detail-panel small" style={{ marginTop: 16 }}>
          <div className="negative">{disabledContext?.headline}</div>
          {disabledContext?.details.map((detail) => (
            <div key={detail} className="muted">
              {detail}
            </div>
          ))}
        </div>
      ) : null}
      {error ? <p className="negative small">{error}</p> : null}
      {journalMessage ? (
        <p className={`${journalMessage.tone} small`}>{journalMessage.message}</p>
      ) : null}

      {preview ? (
        <div className="opportunity-item-metrics" style={{ marginTop: 16 }}>
          <div>
            <span className="muted">Gate:</span> {preview.gate_result ?? 'unknown'}
          </div>
          <div>
            <span className="muted">Freshness:</span> {preview.freshness ?? 'unknown'}
          </div>
          <div>
            <span className="muted">Est. P/L:</span> {formatCurrency(preview.estimated_pnl_usd)}
          </div>
          <div>
            <span className="muted">Audit:</span> {preview.execution_audit_id ?? '--'}
          </div>
          {preview.reject_reasons.length ? (
            <div className="negative">Reject reasons: {preview.reject_reasons.join(' | ')}</div>
          ) : null}
        </div>
      ) : null}

      {receipt ? (
        <div className="detail-panel small" style={{ marginTop: 16 }}>
          <div>
            <span className="muted">Audit receipt:</span>{' '}
            <span className={receipt.ok ? 'positive' : 'negative'}>
              {receipt.ok ? 'recorded' : 'blocked'}
            </span>
          </div>
          <div>
            <span className="muted">Ledger id:</span> {receipt.ledger_id ?? '--'}
          </div>
          <div>
            <span className="muted">Fill:</span> {formatQuantity(receipt.filled_qty)} @{' '}
            {formatCurrency(receipt.fill_price)}
          </div>
          <div>
            <span className="muted">Slippage assumption:</span>{' '}
            {receipt.slippage_assumption_bps ?? 0} bps
          </div>
          <div>
            <span className="muted">Action snapshot:</span>{' '}
            {receipt.recommended_action_snapshot ?? '--'}
          </div>
          <button type="button" className="button" onClick={scrollToLedger}>
            View in ledger
          </button>
        </div>
      ) : null}
    </section>
  );
}

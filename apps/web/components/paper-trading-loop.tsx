'use client';

import { useEffect, useMemo, useState } from 'react';
import { placeOrder, previewOrder } from '@/lib/trading-desk';
import type {
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

function makeOrderKey(result: ScanResult) {
  return `dashboard-paper-${result.asset_type}-${result.ticker}-${result.decision_signal.toLowerCase()}-${Date.now()}`;
}

export function PaperTradingLoop({
  selectedResult,
  selectedDecision,
  onPaperOrderPlaced,
}: {
  selectedResult: ScanResult | null;
  selectedDecision?: DecisionRow | null;
  onPaperOrderPlaced: (auditId: number | null) => void | Promise<void>;
}) {
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null);
  const [receipt, setReceipt] = useState<OrderPlaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'preview' | 'place' | null>(null);
  const [orderKey, setOrderKey] = useState<string | null>(null);

  const setup = useMemo(
    () => (selectedResult ? buildDryRunSetup(selectedResult) : null),
    [selectedResult],
  );
  const recommendedAction =
    selectedDecision?.recommended_action ?? selectedResult?.recommended_action ?? null;
  const previewEnabled = Boolean(setup && selectableAction(recommendedAction) && busy == null);
  const placeEnabled = Boolean(
    preview && setup && orderKey && preview.gate_result !== 'blocked' && busy == null,
  );

  useEffect(() => {
    setPreview(null);
    setReceipt(null);
    setError(null);
    setOrderKey(null);
  }, [selectedResult?.asset_type, selectedResult?.decision_signal, selectedResult?.ticker]);

  const runPreview = async () => {
    if (!setup || !previewEnabled) return;
    setBusy('preview');
    setError(null);
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
        <p className="muted" style={{ margin: 0 }}>Select a ranked opportunity to begin.</p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 style={{ marginBottom: 8 }}>Paper Trading Loop</h2>
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
      </div>

      {!selectableAction(recommendedAction) ? (
        <p className="negative small" style={{ marginTop: 12 }}>
          Preview is disabled because the recommended action is {recommendedAction ?? 'missing'}.
        </p>
      ) : null}
      {error ? <p className="negative small">{error}</p> : null}

      {preview ? (
        <div className="opportunity-item-metrics" style={{ marginTop: 16 }}>
          <div>
            <span className="muted">Gate:</span> {preview.gate_result ?? 'unknown'}
          </div>
          <div>
            <span className="muted">Freshness:</span> {preview.freshness ?? 'unknown'}
          </div>
          <div>
            <span className="muted">Est. P/L:</span>{' '}
            {formatCurrency(preview.estimated_pnl_usd)}
          </div>
          <div>
            <span className="muted">Audit:</span> {preview.execution_audit_id ?? '--'}
          </div>
          {preview.reject_reasons.length ? (
            <div className="negative">
              Reject reasons: {preview.reject_reasons.join(' | ')}
            </div>
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

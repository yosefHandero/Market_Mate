'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  buildDryRunSetup,
  evaluatePaperActionGate,
  makeOrderKey,
} from '@/lib/paper-order';
import { placeOrder, previewOrder } from '@/lib/trading-desk';
import type {
  AutomationStatusResponse,
  DecisionRow,
  OrderPlaceResponse,
  OrderPreviewResponse,
  ScanResult,
} from '@/lib/types';

function selectableAction(action: string | null | undefined): boolean {
  return action === 'preview' || action === 'dry_run';
}

export function usePaperOrder({
  result,
  decision,
  automation,
  onPlaced,
}: {
  result: ScanResult;
  decision?: DecisionRow | null;
  automation?: AutomationStatusResponse | null;
  onPlaced?: (auditId: number | null) => void | Promise<void>;
}) {
  const [preview, setPreview] = useState<OrderPreviewResponse | null>(null);
  const [receipt, setReceipt] = useState<OrderPlaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'preview' | 'place' | null>(null);
  const [orderKey, setOrderKey] = useState<string | null>(null);

  const setup = useMemo(() => buildDryRunSetup(result), [result]);
  const recommendedAction = decision?.recommended_action ?? result.recommended_action ?? null;
  const actionGate = useMemo(
    () => evaluatePaperActionGate({ result, decision, automation }),
    [automation, decision, result],
  );
  const canAct = actionGate.allowed;

  const previewEnabled = Boolean(setup && canAct && busy == null);
  const placeEnabled = Boolean(
    preview &&
      setup &&
      orderKey &&
      preview.gate_result !== 'blocked' &&
      selectableAction(recommendedAction) &&
      canAct &&
      busy == null,
  );

  useEffect(() => {
    setPreview(null);
    setReceipt(null);
    setError(null);
    setOrderKey(null);
  }, [result.asset_type, result.decision_signal, result.ticker]);

  const runPreview = useCallback(async () => {
    if (!setup || !previewEnabled) return;
    setBusy('preview');
    setError(null);
    setReceipt(null);
    setPreview(null);
    setOrderKey(null);

    try {
      const nextPreview = await previewOrder({
        ...setup,
        recommended_action_snapshot: recommendedAction,
      });
      setPreview(nextPreview);
      setOrderKey(makeOrderKey(result));
    } catch (caught) {
      setPreview(null);
      setOrderKey(null);
      setError(caught instanceof Error ? caught.message : 'Preview failed.');
    } finally {
      setBusy(null);
    }
  }, [previewEnabled, recommendedAction, result, setup]);

  const runPlace = useCallback(async () => {
    if (!setup || !preview || !orderKey || !placeEnabled) return;
    setBusy('place');
    setError(null);

    try {
      const nextReceipt = await placeOrder({
        ...setup,
        qty: preview.qty,
        preview_audit_id: preview.execution_audit_id,
        idempotency_key: orderKey,
        dry_run: true,
        recommended_action_snapshot: recommendedAction,
      });
      const duplicateReceipt =
        receipt != null &&
        receipt.execution_audit_id === nextReceipt.execution_audit_id &&
        receipt.ledger_id === nextReceipt.ledger_id &&
        receipt.idempotency_key === nextReceipt.idempotency_key;
      setReceipt(nextReceipt);
      if (!duplicateReceipt) {
        await onPlaced?.(nextReceipt.execution_audit_id ?? null);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Dry-run placement failed.');
    } finally {
      setBusy(null);
    }
  }, [
    onPlaced,
    orderKey,
    placeEnabled,
    preview,
    receipt,
    recommendedAction,
    setup,
  ]);

  return {
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
  };
}

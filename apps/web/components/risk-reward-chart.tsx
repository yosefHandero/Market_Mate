'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { DecisionSignal } from '@/lib/types';
import type { PricePoint, RiskOverlayState } from '@/lib/trading-desk';

type OverlayField = 'entryPrice' | 'stopLoss' | 'takeProfit';

interface RiskRewardChartProps {
  points: PricePoint[];
  overlay: RiskOverlayState;
  signal: DecisionSignal;
  triggerPrice: number;
  onOverlayChange: (field: OverlayField, value: number) => void;
  onReset: () => void;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function roundPrice(value: number) {
  return Math.round(value * 100) / 100;
}

export function RiskRewardChart({
  points,
  overlay,
  signal,
  triggerPrice,
  onOverlayChange,
  onReset,
}: RiskRewardChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const activeHandleRef = useRef<OverlayField | null>(null);
  const onOverlayChangeRef = useRef(onOverlayChange);

  const chart = useMemo(() => {
    const values = [
      ...points.map((point) => point.price),
      overlay.entryPrice,
      overlay.stopLoss,
      overlay.takeProfit,
      triggerPrice,
    ];
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const span = Math.max(maxValue - minValue, triggerPrice * 0.03, 0.5);
    const padding = span * 0.22;
    const floor = Math.max(0.01, minValue - padding);
    const ceiling = maxValue + padding;

    return {
      min: floor,
      max: ceiling,
      span: ceiling - floor,
    };
  }, [overlay.entryPrice, overlay.stopLoss, overlay.takeProfit, points, triggerPrice]);

  const priceToY = (price: number) => {
    const ratio = (chart.max - price) / chart.span;
    return 20 + ratio * 300;
  };

  const seriesPath = points.length
    ? points
        .map((point, index) => {
          const x = 24 + (index / Math.max(points.length - 1, 1)) * 632;
          const y = priceToY(point.price);
          return `${index === 0 ? 'M' : 'L'} ${x} ${y}`;
        })
        .join(' ')
    : '';

  const rewardTop = signal === 'SELL' ? priceToY(overlay.entryPrice) : priceToY(overlay.takeProfit);
  const rewardHeight = Math.abs(priceToY(overlay.takeProfit) - priceToY(overlay.entryPrice));
  const riskTop = signal === 'SELL' ? priceToY(overlay.stopLoss) : priceToY(overlay.entryPrice);
  const riskHeight = Math.abs(priceToY(overlay.stopLoss) - priceToY(overlay.entryPrice));
  const overlayLines: Array<{
    field: OverlayField;
    label: string;
    colorClass: string;
    price: number;
  }> = [
    {
      field: 'entryPrice',
      label: 'Entry',
      colorClass: 'risk-line-entry',
      price: overlay.entryPrice,
    },
    {
      field: 'stopLoss',
      label: 'Stop Loss',
      colorClass: 'risk-line-stop',
      price: overlay.stopLoss,
    },
    {
      field: 'takeProfit',
      label: 'Take Profit',
      colorClass: 'risk-line-target',
      price: overlay.takeProfit,
    },
  ];

  useEffect(() => {
    onOverlayChangeRef.current = onOverlayChange;
  }, [onOverlayChange]);

  const updateFromClientY = useCallback(
    (clientY: number) => {
      const activeHandle = activeHandleRef.current;
      const bounds = svgRef.current?.getBoundingClientRect();
      if (!activeHandle || !bounds) {
        return;
      }

      const localY = clamp(clientY - bounds.top, 20, 320);
      const ratio = clamp((localY - 20) / 300, 0, 1);
      onOverlayChangeRef.current(activeHandle, roundPrice(chart.max - ratio * chart.span));
    },
    [chart.max, chart.span],
  );

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      if (!activeHandleRef.current) {
        return;
      }
      event.preventDefault();
      updateFromClientY(event.clientY);
    };

    const handlePointerUp = () => {
      activeHandleRef.current = null;
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', handlePointerUp);

    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [updateFromClientY]);

  const beginDrag = (field: OverlayField, clientY: number) => {
    activeHandleRef.current = field;
    updateFromClientY(clientY);
  };

  return (
    <div className="risk-chart-card">
      <div className="risk-chart-header">
        <div>
          <h2 style={{ margin: 0 }}>Risk/Reward Chart</h2>
          <p className="muted small" style={{ marginTop: 6 }}>
            Drag the lines to adjust entry, stop loss, and target on the active setup.
          </p>
        </div>
        <button type="button" className="button desk-ghost-button" onClick={onReset}>
          Reset setup
        </button>
      </div>

      <div className="risk-chart-shell">
        <svg
          ref={svgRef}
          viewBox="0 0 680 340"
          className="risk-chart"
          role="img"
          aria-label="Interactive price chart with risk and reward overlays"
        >
          <defs>
            <linearGradient id="riskChartFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="rgba(94,160,255,0.28)" />
              <stop offset="100%" stopColor="rgba(94,160,255,0.02)" />
            </linearGradient>
          </defs>

          {[0, 1, 2, 3].map((step) => {
            const y = 20 + step * 100;
            const label = roundPrice(chart.max - (chart.span * step) / 3);

            return (
              <g key={step}>
                <line x1="24" x2="656" y1={y} y2={y} className="risk-grid-line" />
                <text x="666" y={y + 4} className="risk-grid-label">
                  {label.toFixed(2)}
                </text>
              </g>
            );
          })}

          <rect
            x="24"
            y={rewardTop}
            width="632"
            height={rewardHeight}
            className="risk-zone-positive"
          />
          <rect x="24" y={riskTop} width="632" height={riskHeight} className="risk-zone-negative" />

          {seriesPath ? (
            <>
              <path d={`${seriesPath} L 656 320 L 24 320 Z`} fill="url(#riskChartFill)" />
              <path d={seriesPath} className="risk-price-path" />
            </>
          ) : null}

          <line
            x1="24"
            x2="656"
            y1={priceToY(triggerPrice)}
            y2={priceToY(triggerPrice)}
            className="risk-trigger-line"
          />
          <text x="32" y={priceToY(triggerPrice) - 8} className="risk-line-label">
            Trigger {triggerPrice.toFixed(2)}
          </text>

          {overlayLines.map((line) => {
            const y = priceToY(line.price);

            return (
              <g key={line.field}>
                <line x1="24" x2="656" y1={y} y2={y} className={line.colorClass} />
                <text x="32" y={y - 8} className="risk-line-label">
                  {line.label} {line.price.toFixed(2)}
                </text>
                <circle
                  cx="644"
                  cy={y}
                  r="9"
                  className={`risk-line-handle ${line.colorClass}`}
                  onPointerDown={(event) => beginDrag(line.field, event.clientY)}
                />
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

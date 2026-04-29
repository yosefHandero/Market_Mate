'use client';

import type { DecisionSignal, ScanResult } from '@/lib/types';

function signalBadge(signal: DecisionSignal) {
  if (signal === 'BUY') return <span className="badge green">Buy</span>;
  if (signal === 'SELL') return <span className="badge red">Sell</span>;
  return <span className="badge">Hold</span>;
}

type RankTableProps = {
  results: ScanResult[];
  topN?: number;
  activeTicker?: string;
  onSelectTicker?: (ticker: string) => void;
};

const CRYPTO_EMPTY_MESSAGE = 'Crypto opportunities will appear here when crypto data is connected.';

function formatCurrency(value: number) {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatPercent(value: number) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatReason(reason: string) {
  const trimmed = reason.trim();
  if (!trimmed) {
    return 'No summary is available yet.';
  }

  if (trimmed.length <= 140) {
    return trimmed;
  }

  return `${trimmed.slice(0, 137).trimEnd()}...`;
}

function OpportunityItem({
  row,
  rank,
  activeTicker,
  onSelectTicker,
}: {
  row: ScanResult;
  rank: number;
  activeTicker?: string;
  onSelectTicker?: (ticker: string) => void;
}) {
  const isActive = row.ticker === activeTicker;
  const className = [
    'opportunity-item',
    onSelectTicker ? 'is-button' : '',
    isActive ? 'is-active' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const content = (
    <>
      <div className="opportunity-item-top">
        <div className="opportunity-item-symbol">
          <span className="opportunity-rank">#{rank}</span>
          <div>
            <strong>{row.ticker}</strong>
            <div className="muted small">
              {row.strategy_primary_horizon} setup
              {row.evidence_quality ? ` | ${row.evidence_quality} evidence` : ''}
            </div>
          </div>
        </div>
        {signalBadge(row.decision_signal)}
      </div>

      <div className="opportunity-item-metrics">
        <div className="opportunity-metric">
          <span className="muted small">Trigger Price</span>
          <strong>{formatCurrency(row.price)}</strong>
        </div>
        <div className="opportunity-metric">
          <span className="muted small">Confidence</span>
          <strong>{row.calibrated_confidence.toFixed(1)}</strong>
        </div>
        <div className="opportunity-metric">
          <span className="muted small">Day Move</span>
          <strong
            className={
              row.price_change_pct > 0
                ? 'positive'
                : row.price_change_pct < 0
                  ? 'negative'
                  : 'neutral'
            }
          >
            {formatPercent(row.price_change_pct)}
          </strong>
        </div>
      </div>

      <p className="opportunity-reason">{formatReason(row.explanation)}</p>
    </>
  );

  if (onSelectTicker) {
    return (
      <button type="button" className={className} onClick={() => onSelectTicker(row.ticker)}>
        {content}
      </button>
    );
  }

  return (
    <article className={className}>{content}</article>
  );
}

function RankSection({
  title,
  description,
  results,
  targetCount,
  emptyMessage,
  activeTicker,
  onSelectTicker,
}: {
  title: string;
  description: string;
  results: ScanResult[];
  targetCount: number | null;
  emptyMessage: string;
  activeTicker?: string;
  onSelectTicker?: (ticker: string) => void;
}) {
  const needsMoreMessage =
    targetCount != null && results.length > 0 && results.length < targetCount;

  return (
    <section className="opportunity-group">
      <div className="opportunity-group-header">
        <div className="opportunity-group-copy">
          <h3 style={{ margin: 0 }}>{title}</h3>
          <p className="muted small" style={{ margin: 0 }}>
            {description}
          </p>
        </div>
        <span className="badge">
          {results.length}
          {targetCount != null ? `/${targetCount}` : ''}
        </span>
      </div>

      {results.length ? (
        <div className="opportunity-items">
          {results.map((row, index) => (
            <OpportunityItem
              key={`${row.ticker}-${row.created_at}`}
              row={row}
              rank={index + 1}
              activeTicker={activeTicker}
              onSelectTicker={onSelectTicker}
            />
          ))}
        </div>
      ) : (
        <p className="muted opportunity-empty">{emptyMessage}</p>
      )}

      {needsMoreMessage ? (
        <p className="muted small opportunity-footnote" style={{ margin: 0 }}>
          Showing {results.length} of {targetCount}. More opportunities will appear here as new
          scan results qualify.
        </p>
      ) : null}
    </section>
  );
}

export function RankTable({
  results,
  topN,
  activeTicker,
  onSelectTicker,
}: RankTableProps) {
  const limitedCount = topN != null && topN > 0 ? topN : null;
  const stockResults = results.filter((result) => result.asset_type === 'stock');
  const cryptoResults = results.filter((result) => result.asset_type === 'crypto');
  const stocks = limitedCount != null ? stockResults.slice(0, limitedCount) : stockResults;
  const crypto = limitedCount != null ? cryptoResults.slice(0, limitedCount) : cryptoResults;

  return (
    <div className="opportunity-groups">
      <RankSection
        title={limitedCount != null ? `Top ${limitedCount} Stocks` : 'Stocks'}
        description="Highest-ranked stock setups from the latest scan."
        results={stocks}
        targetCount={limitedCount}
        emptyMessage="Stock opportunities will appear here after the next completed scan."
        activeTicker={activeTicker}
        onSelectTicker={onSelectTicker}
      />
      <RankSection
        title={limitedCount != null ? `Top ${limitedCount} Crypto` : 'Crypto'}
        description="Highest-ranked crypto setups from the latest scan."
        results={crypto}
        targetCount={limitedCount}
        emptyMessage={CRYPTO_EMPTY_MESSAGE}
        activeTicker={activeTicker}
        onSelectTicker={onSelectTicker}
      />
    </div>
  );
}

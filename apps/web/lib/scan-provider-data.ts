import type { ProviderAttemptDiagnostic, ScanAssetCoverage, ScanProviderDiagnostics, ScanResult } from '@/lib/types';

// Keep provider request records on the server. React serializes every prop of
// a client component, including fields it never renders.
export function withoutProviderDiagnostics(rows: ScanResult[]): ScanResult[] {
  return rows.map((row) => row.layer_details?.provider_health ? {
    ...row,
    news_cache_label: row.layer_details.provider_health.directional_news ? null : row.news_cache_label,
    layer_details: { ...row.layer_details, provider_health: undefined },
  } : row);
}

function safeProvider(code: string | null | undefined): string {
  return code && providerNames.has(code) ? code : '';
}

function safeStatus(code: string | null | undefined): string {
  return code && statusLabels.has(code) ? code : '';
}

function safeHttpStatus(code: number | null | undefined): number | null {
  return typeof code === 'number' && Number.isInteger(code) && code >= 100 && code <= 599 ? code : null;
}

function sanitizeAttempt(attempt: ProviderAttemptDiagnostic): ProviderAttemptDiagnostic {
  return {
    provider: safeProvider(attempt.provider), endpoint: safeEndpoint(attempt.endpoint),
    status: safeStatus(attempt.status), http_status: safeHttpStatus(attempt.http_status),
    lookback_start: knownTimestamp(attempt.lookback_start), latest_article_at: knownTimestamp(attempt.latest_article_at),
  };
}

function sanitizeDirectionalNews(news: NonNullable<ScanProviderDiagnostics['directional_news']>) {
  return {
    status: ['available', 'unavailable', 'successful_empty', 'not_requested'].includes(news.status)
      ? news.status : 'unavailable' as const,
    source: (news.source ?? '').split('+').map(safeProvider).filter(Boolean).join('+'),
    providers: (news.providers ?? []).map(sanitizeAttempt),
  };
}

export function sanitizeCoverageProviderDiagnostics(coverage: ScanAssetCoverage[] | null | undefined) {
  return coverage?.map((asset) => ({
    ...asset,
    missing_symbols: asset.missing_symbols.map((symbol) => symbol.directional_news ? {
      ...symbol, directional_news: sanitizeDirectionalNews(symbol.directional_news),
    } : symbol),
  }));
}

// Development SSR also serializes server-component props for React diagnostics.
export function sanitizeProviderDiagnostics(row: ScanResult): ScanResult {
  const health = row.layer_details?.provider_health;
  if (!health) return row;

  const bars = health.market_bars;
  const news = health.directional_news;
  const benchmark = health.benchmark;
  const providerHealth: ScanProviderDiagnostics = {
    benchmark: benchmark ? {
      status: safeStatus(benchmark.status),
      symbols: benchmark.symbols.filter(({ symbol }) => ['SPY', 'QQQ', 'BTC/USD'].includes(symbol)).map((item) => ({
        ...sanitizeAttempt(item),
        symbol: item.symbol,
        as_of: knownTimestamp(item.as_of),
        age_minutes: Number.isFinite(item.age_minutes) ? item.age_minutes : null,
        primary_status: safeStatus(item.primary_status), primary_http_status: safeHttpStatus(item.primary_http_status),
        fallback_status: safeStatus(item.fallback_status), fallback_http_status: safeHttpStatus(item.fallback_http_status),
        polygon_status: safeStatus(item.polygon_status), polygon_http_status: safeHttpStatus(item.polygon_http_status),
      })),
    } : undefined,
    directional_news: news ? sanitizeDirectionalNews(news) : undefined,
    market_bars: bars ? {
      ...sanitizeAttempt(bars),
      as_of: knownTimestamp(bars.as_of), max_age_minutes: Number.isFinite(bars.max_age_minutes) ? bars.max_age_minutes : null,
      coinbase_price_as_of: knownTimestamp(bars.coinbase_price_as_of),
      primary_status: safeStatus(bars.primary_status), primary_http_status: safeHttpStatus(bars.primary_http_status),
      fallback_status: safeStatus(bars.fallback_status), fallback_http_status: safeHttpStatus(bars.fallback_http_status),
      fallback_provider: safeProvider(bars.fallback_provider),
      polygon_status: safeStatus(bars.polygon_status), polygon_http_status: safeHttpStatus(bars.polygon_http_status),
    } : undefined,
  };
  return {
    ...row, news_cache_label: news ? null : row.news_cache_label,
    layer_details: { ...row.layer_details, provider_health: providerHealth },
  };
}

export const providerNames = new Map([
  ['alpaca', 'Alpaca'], ['alpaca_iex', 'Alpaca IEX'], ['alpaca_sip', 'Alpaca delayed SIP'], ['polygon', 'Polygon'], ['finnhub', 'Finnhub'],
  ['marketaux', 'Marketaux'], ['coinbase_ws', 'Coinbase WebSocket'],
  ['cache', 'News cache'], ['stale_cache', 'Stale cache'],
]);

const endpointPaths = new Set([
  '/v1/news/all', '/api/v1/news-sentiment', '/api/v1/company-news',
  '/v2/stocks/bars', '/v1beta3/crypto/us/bars',
]);
const polygonBarsPath = '/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from}/{to}';

const statusLabels = new Map([
  ['ok', 'Available'], ['available', 'Available'], ['fresh', 'Fresh'],
  ['fallback', 'Compatible fallback'], ['ws_override', 'WebSocket price override'],
  ['successful_empty', 'Successful empty'], ['empty', 'Successful empty'], ['no_relevant_articles', 'Successful empty'],
  ['company_sentiment_only', 'Company sentiment available'],
  ['not_requested', 'Not requested'], ['skipped', 'Not requested'],
  ['disabled', 'Intentionally disabled'], ['disabled_missing_credentials', 'Disabled (no credentials)'],
  ['disabled_local_budget', 'Disabled (local request budget is zero)'],
  ['configured_daily_attempt_budget_reached', 'Local daily request budget reached'],
  ['operational_attempt_ceiling_reached', 'Persisted attempt ceiling reached'],
  ['quota_exhausted_reset_unknown', 'Account quota exhausted, reset unconfirmed'],
  ['quota_exhausted_waiting_verified_reset', 'Account quota exhausted, awaiting verified reset'],
  ['rate_limited', 'Rate limited'], ['rate_limit_cooldown', 'Rate cooldown active'],
  ['authentication_failed', 'Authentication failed'], ['access_denied', 'Access denied'],
  ['timeout', 'Timed out'], ['provider_error', 'Provider request failed'],
  ['transport_error', 'Connection failed'], ['provider_server_error', 'Provider server error'],
  ['equivalent_request_recently_failed', 'Equivalent request recently failed'],
  ['equivalent_request_wait_timeout', 'Waiting for an equivalent request timed out'],
  ['request_ownership_lost', 'Coordinated request ownership lost'],
  ['invalid_response', 'Response missing usable fields'], ['coverage_unavailable', 'Coverage unavailable'],
  ['missing_sentiment', 'Matching articles lack usable sentiment'],
  ['invalid_publication_time', 'Matching articles lack a valid publication time'],
  ['unavailable', 'Unavailable'], ['missing', 'Unavailable'], ['unusable', 'Required fields unusable'],
  ['stale', 'Stale'], ['stale_cache', 'Stale cache'], ['market_closed', 'Market closed'],
  ['stale_news', 'Articles are outside the allowed lookback'],
  ['feed_delay', 'Feed delay'],
]);

export function safeEndpoint(value: string | null | undefined): string | null {
  const path = value?.replace(/^https?:\/\/[^/?#]+/i, '').split(/[?#]/, 1)[0];
  if (!path) return null;
  if (endpointPaths.has(path)) return path;
  return /^\/v2\/aggs\/ticker\/[^/]+\/range\//.test(path) ? polygonBarsPath : null;
}

export function statusLabel(code: string | null | undefined): string {
  return (code ? statusLabels.get(code) : null) ?? 'Status unrecorded';
}

export function displayHttp(code: number | null | undefined): string {
  return safeHttpStatus(code) == null ? '' : ` (HTTP ${code})`;
}

export function knownTimestamp(value: string | null | undefined): string | null {
  return value && /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?)?$/i.test(value)
    ? value
    : null;
}


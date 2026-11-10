import { displayHttp, knownTimestamp, providerNames, safeEndpoint, statusLabel } from '@/lib/scan-provider-data';
import type { MarketauxQuotaSummary, ProviderAttemptDiagnostic, ScanAssetCoverage, ScanResult } from '@/lib/types';

function savedNewsStatus(row: ScanResult): string {
  const source = row.news_source;
  if (source === 'skipped' || source === 'unavailable') return source;
  if (row.news_checked) return 'available';
  return row.freshness_flags?.directional_news ?? '';
}

function NewsAttempts({ attempts }: { attempts?: ProviderAttemptDiagnostic[] }) {
  if (!attempts?.length) return null;
  return (
    <ul>
      {attempts.map((attempt, index) => {
        const provider = providerNames.get(attempt.provider) ?? 'Provider';
        const endpoint = safeEndpoint(attempt.endpoint);
        const lookback = knownTimestamp(attempt.lookback_start);
        const articleAt = knownTimestamp(attempt.latest_article_at);
        return (
          <li key={index}>
            {provider}{endpoint ? ` ${endpoint}` : ''} · {statusLabel(attempt.status)}{displayHttp(attempt.http_status)}
            {lookback ? ` · Lookback since ${lookback}` : ''}
            {articleAt ? ` · Latest article ${articleAt}` : ''}
          </li>
        );
      })}
    </ul>
  );
}

export function ScanInputDiagnostics({
  results,
  coverage,
  marketauxQuota,
}: {
  results: ScanResult[];
  coverage?: ScanAssetCoverage[] | null;
  marketauxQuota?: MarketauxQuotaSummary | null;
}) {
  const rows = results.filter((row) => row.decision_role !== 'shadow');
  const missingInputs = (coverage ?? []).flatMap((asset) => asset.missing_symbols)
    .filter((symbol) => symbol.directional_news || symbol.required_input === 'volume_reference');
  const verifiedReset = knownTimestamp(marketauxQuota?.verified_reset_at);
  const rateRetry = knownTimestamp(marketauxQuota?.rate_retry_at);

  return (
    <details aria-label="Required data diagnostics" className="ui-disclosure small">
      <summary className="ui-disclosure-summary">Required data diagnostics</summary>
      <p className="muted">
        <strong>Marketaux shared quota now</strong>
        {marketauxQuota ? (
          <>
            {' · '}{marketauxQuota.utc_day_attempts}
            {marketauxQuota.configured_daily_attempt_budget == null ? '' : ` of ${marketauxQuota.configured_daily_attempt_budget}`}
            {' local UTC-day attempts, including retries'}
            {marketauxQuota.configured_daily_attempt_budget == null ? ' · No configured daily limit' : ''}
            {marketauxQuota.operational_attempts_remaining == null
              ? ' · No persisted ceiling'
              : ` · ${marketauxQuota.operational_attempts_remaining} remaining under the persisted ceiling`}
            {marketauxQuota.block_state === 'reset_unknown' ? ' · Account quota exhausted, reset unconfirmed' : ''}
            {verifiedReset ? ` · Verified account reset ${verifiedReset}` : ''}
            {rateRetry ? ` · Rate cooldown until ${rateRetry}` : ''}
          </>
        ) : ' · Unavailable. Check the configured credential and local quota store.'}
      </p>
      {rows.length || missingInputs.length ? <p className="muted">Provider attempts and freshness recorded at scan time.</p> : null}
      {missingInputs.map(({ ticker, directional_news: news, detail }) => (
        <details key={ticker} className="ui-disclosure">
          <summary className="ui-disclosure-summary">
            {ticker} · {news ? 'Required directional news unavailable' : 'Reference volume unavailable'}
          </summary>
          {news ? <NewsAttempts attempts={news.providers} /> : <p>{detail}</p>}
        </details>
      ))}
      {rows.map((row) => {
        const health = row.layer_details?.provider_health;
        const benchmark = health?.benchmark;
        const bars = health?.market_bars;
        const news = health?.directional_news;
        const barEndpoint = safeEndpoint(bars?.endpoint);
        const barProvider = providerNames.get(bars?.provider ?? row.price_source ?? '');
        const fallbackProvider = providerNames.get(bars?.fallback_provider ?? '');
        const barAsOf = knownTimestamp(bars?.as_of) ?? knownTimestamp(row.bar_as_of);
        const coinbaseAsOf = knownTimestamp(bars?.coinbase_price_as_of);
        const newsSources = (news?.source ?? row.news_source ?? '').split('+')
          .map((source) => providerNames.get(source)).filter(Boolean);
        const otherInputs = Object.entries(row.freshness_flags ?? {}).filter(([name, status]) =>
          ['options_flow', 'sec', 'fear_greed', 'coingecko_context', 'binance', 'deribit', 'fred', 'breadth', 'defillama'].includes(name)
          && status !== 'ok',
        );
        return (
          <details key={`${row.asset_type}:${row.ticker}`} className="ui-disclosure">
            <summary className="ui-disclosure-summary">{row.ticker}</summary>
            <ul className="decision-reason-list">
              {!Number.isFinite(row.price) || row.price <= 0 ? (
                <li><strong>Saved scan price</strong> · Unavailable in this saved row</li>
              ) : null}
              <li>
                <strong>Market bars</strong> · {statusLabel(bars?.status ?? row.freshness_flags?.market_bars)}
                {barProvider ? ` · ${barProvider}` : ''}{barEndpoint ? ` ${barEndpoint}` : ''}
                {displayHttp(bars?.http_status)}
                {row.fallback_used ? ' · Fallback used' : ''}
                {barAsOf ? ` · As of ${barAsOf}` : ''}
                {Number.isFinite(row.bar_age_minutes) ? ` · Age at scan ${row.bar_age_minutes}m` : ''}
                {Number.isFinite(bars?.max_age_minutes) ? ` · Limit ${bars?.max_age_minutes}m` : ''}
                {coinbaseAsOf ? ` · Coinbase price as of ${coinbaseAsOf}` : ''}
                {bars?.primary_status ? ` · Primary ${statusLabel(bars.primary_status)}${displayHttp(bars.primary_http_status)}` : ''}
                {bars?.fallback_status ? ` · Fallback ${fallbackProvider ? `${fallbackProvider} ` : ''}${statusLabel(bars.fallback_status)}${displayHttp(bars.fallback_http_status)}` : ''}
                {bars?.polygon_status ? ` · Polygon ${statusLabel(bars.polygon_status)}${displayHttp(bars.polygon_http_status)}` : ''}
              </li>
              {benchmark ? (
                <li>
                  <strong>Relative-strength benchmark</strong> · {statusLabel(benchmark.status)}
                  <ul>
                    {benchmark.symbols.map((item) => (
                      <li key={item.symbol}>
                        {item.symbol} · {statusLabel(item.status)}
                        {item.provider ? ` · ${providerNames.get(item.provider) ?? 'Provider'}` : ''}
                        {item.as_of ? ` · As of ${item.as_of}` : ''}
                        {Number.isFinite(item.age_minutes) ? ` · Age at scan ${item.age_minutes}m` : ''}
                        {item.primary_status ? ` · Primary ${statusLabel(item.primary_status)}${displayHttp(item.primary_http_status)}` : ''}
                        {item.fallback_status ? ` · Fallback ${statusLabel(item.fallback_status)}${displayHttp(item.fallback_http_status)}` : ''}
                        {item.polygon_status ? ` · Polygon ${statusLabel(item.polygon_status)}${displayHttp(item.polygon_http_status)}` : ''}
                      </li>
                    ))}
                  </ul>
                </li>
              ) : null}
              <li>
                <strong>Directional news</strong> · {statusLabel(news?.status ?? savedNewsStatus(row))}
                {newsSources.length ? ` · Source ${newsSources.join(' + ')}` : ''}
                {row.freshness_flags?.directional_news === 'fallback' ? ' · Compatible fallback' : ''}
                <NewsAttempts attempts={news?.providers} />
              </li>
              {otherInputs.length > 0 ? (
                <li>
                  <strong>Optional context</strong>
                  <ul>
                    {otherInputs.map(([name, status]) => (
                      <li key={name}>{name === 'sec' ? 'SEC enhanced' : name[0].toUpperCase() + name.slice(1).replaceAll('_', ' ')} · {statusLabel(status)}</li>
                    ))}
                  </ul>
                </li>
              ) : null}
            </ul>
          </details>
        );
      })}
    </details>
  );
}

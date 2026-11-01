# Marketaux quota operations

Run commands from `services/scanner` with the same environment/cache directory as
the API and worker. These commands never call a provider or touch evidence rows.

```powershell
.venv\Scripts\python.exe -m app.marketaux_quota status
.venv\Scripts\python.exe -m app.marketaux_quota ceiling 0 --reason "Quota availability unverified; keep HTTP blocked"
```

`provider_coordination.sqlite3` in the configured cache directory is shared by
the API/worker and survives restarts. Keep that file: deleting it discards quota
blocks and request accounting. `total_attempts` counts conservative reservations
made immediately before HTTP sends, including retries and transport failures. A
crash between reservation and sending can overcount; it cannot undercount a send.
Counts cover this application since coordination was introduced, not external
account usage or requests made by older processes.

The remaining-attempt ceiling is persistent and global to this Marketaux token.
`ceiling 3` permits at most three *additional* HTTP attempts total across all
tickers, processes and retries. It does not establish account availability or
remove an exhaustion block. `ceiling 0` permits none. A cached response does not
consume an HTTP attempt and does not establish that a new scan completed.

The optional `MARKETAUX_DAILY_ATTEMPT_BUDGET` setting is a local UTC-day cap.
It has no default account allowance: the actual subscription allowance and
remaining usage must be verified with Marketaux. UTC rollover resets only this
local counter, never an unknown provider exhaustion block. Reactive protection
cannot promise account quota will never be exhausted, especially if another
application uses the same token.

## Exhaustion versus throttling

[Marketaux's official error documentation](https://www.marketaux.com/documentation#errors)
distinguishes `usage_limit_reached` with HTTP 402 (plan exhaustion) from
`rate_limit_reached` with HTTP 429 (the rolling rate window). Only the confirmed
usage error sets the persistent quota block. An unexplained 402 fails the request
without claiming the account quota is exhausted. HTTP 429 honors `Retry-After`
or the documented 60-second rate window and stores a temporary shared cooldown.

The documentation does not establish a reliable daily-reset timestamp/header.
A confirmed exhaustion therefore persists as `reset_unknown`; restarting or
reaching midnight does not clear it. `Retry-After` is not treated as evidence of a
daily reset. No account plan, reset time, or paid upgrade is inferred.

After manually verifying quota availability with Marketaux:

```powershell
.venv\Scripts\python.exe -m app.marketaux_quota recover --reason "Verified available on Marketaux account dashboard at <time>"
```

If Marketaux instead provides an exact future reset time, record that verified
timestamp (ISO 8601 including timezone):

```powershell
.venv\Scripts\python.exe -m app.marketaux_quota recover --verified-reset-at <verified-timestamp> --reason "Reset confirmed by <provider source> at <time>"
```

This stores `reset_known` and blocks until that timestamp. Recovery records its
reason and time in `quota_audit`; it does not zero counters, discard evidence, or
raise an existing attempt ceiling. Only after availability is established and a
controlled verification scan is authorized, set its total budget:

```powershell
.venv\Scripts\python.exe -m app.marketaux_quota ceiling 3 --reason "One controlled verification scan; quota verified at <time>"
```

After verification, keep automatic scans paused and restore `ceiling 0`. Resuming
normal operation is separate; `clear-ceiling --reason "..."` explicitly removes
only the operational ceiling, preserving quota blocks and any configured cap.

## Cache and unavailable inputs

Request keys cover endpoint, method, token identity and all request parameters.
Equivalent requests share an expiring, renewed owner with bounded waiting. Each
response/cache write is fenced to its owner; an expired owner's late response
cannot replace a newer result or alter quota state. All SQLite transactions are
short and close before any HTTP operation or wait.

Provider failures return unavailable, never successful `0.0`. Actual neutral
sentiment remains valid. Finnhub remains independent; its valid result can be
used while Marketaux is unavailable, with the source and warning recorded.
Only fully successful provider pairs populate the combined news cache. The
established directional averaging calculation is unchanged for identical valid
inputs. Legacy `news_cache.json` is preserved but ignored because it cannot
distinguish cached failures from neutral results. New atomic per-key SQLite
writes preserve concurrent cache updates. No learned-artifact payload changes.

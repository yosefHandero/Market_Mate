import { describe, expect, it } from 'vitest';
import { journalEntryCreateSchema, journalEntryUpdateSchema } from '@/lib/journal';

describe('journal payload validation', () => {
  it('rejects blank tickers after trimming', () => {
    const result = journalEntryCreateSchema.safeParse({
      ticker: '   ',
      run_id: null,
      decision: 'watching',
      entry_price: null,
      exit_price: null,
      pnl_pct: null,
      notes: '',
      signal_label: null,
      score: null,
      news_source: null,
    });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toBe('Ticker is required.');
  });

  it('rejects exit prices without an entry price on create', () => {
    const result = journalEntryCreateSchema.safeParse({
      ticker: 'AAPL',
      run_id: null,
      decision: 'watching',
      entry_price: null,
      exit_price: 210,
      pnl_pct: null,
      notes: '',
      signal_label: null,
      score: null,
      news_source: null,
    });

    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toBe('Exit price requires an entry price.');
  });

  it('normalizes create payloads for the proxy layer', () => {
    const result = journalEntryCreateSchema.parse({
      ticker: ' aapl ',
      run_id: ' run-1 ',
      decision: 'watching',
      entry_price: 180,
      exit_price: null,
      pnl_pct: null,
      notes: '  thesis  ',
      signal_label: ' strong ',
      score: 77.5,
      news_source: ' marketaux ',
    });

    expect(result).toEqual({
      ticker: 'AAPL',
      run_id: 'run-1',
      decision: 'watching',
      entry_price: 180,
      exit_price: null,
      pnl_pct: null,
      notes: 'thesis',
      signal_label: 'strong',
      score: 77.5,
      news_source: 'marketaux',
      override_reason: null,
    });
  });

  it('allows partial journal updates while trimming nullable notes', () => {
    const result = journalEntryUpdateSchema.parse({
      notes: '  updated note  ',
    });

    expect(result).toEqual({
      notes: 'updated note',
    });
  });
});

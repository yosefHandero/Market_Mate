import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatPaperTimestamp } from '@/lib/paper-contract';

afterEach(() => vi.restoreAllMocks());

describe('saved paper timestamps', () => {
  it('interprets SQLite offset-free timestamps as UTC, including the fall-back date', () => {
    vi.spyOn(Date.prototype, 'toLocaleString').mockImplementation(function (this: Date) {
      return new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', dateStyle: 'short', timeStyle: 'long' }).format(this);
    });
    expect(formatPaperTimestamp('2026-11-01T13:07:26.06239')).toBe(formatPaperTimestamp('2026-11-01T13:07:26.06239Z'));
    expect(formatPaperTimestamp('2026-11-01T13:07:26.06239')).toContain('7:07:26 AM CST');
    expect(formatPaperTimestamp('2026-11-01T06:30:00')).toContain('1:30:00 AM CDT');
    expect(formatPaperTimestamp('2026-11-01T07:30:00')).toContain('1:30:00 AM CST');
  });

  it('preserves explicit offsets and renders missing or invalid values honestly', () => {
    expect(formatPaperTimestamp('2026-11-01T07:07:26-06:00')).toBe(formatPaperTimestamp('2026-11-01T13:07:26Z'));
    expect(formatPaperTimestamp(undefined)).toBe('--');
    expect(formatPaperTimestamp(null)).toBe('--');
    expect(formatPaperTimestamp('not-a-date')).toBe('--');
  });
});

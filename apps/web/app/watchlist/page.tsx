import { WatchlistView } from '@/components/watchlist-view';
import { getJournalEntries, getLatestScan } from '@/lib/api';

export default async function WatchlistPage() {
  const [latestScanResult, journalEntriesResult] = await Promise.all([
    getLatestScan(),
    getJournalEntries(500),
  ]);

  return (
    <main>
      <WatchlistView
        latestScan={latestScanResult.data}
        journalEntries={journalEntriesResult.data ?? []}
        scanError={latestScanResult.error}
        journalError={journalEntriesResult.error}
      />
    </main>
  );
}

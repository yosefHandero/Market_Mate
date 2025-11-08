import Link from "next/link";

import TradingViewWidget from "@/components/TradingViewWidget";
import WatchlistButton from "@/components/WatchlistButton";
import { connectToDatabase } from "@/database/mongoose";
import { Watchlist } from "@/database/models/watchlist.model";
import { getCurrentUser } from "@/lib/auth/session";
import { CANDLE_CHART_WIDGET_CONFIG } from "@/lib/constants";

const TRADINGVIEW_SCRIPT = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

export default async function WatchlistPage() {
  const user = await getCurrentUser();

  if (!user) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold text-white">My Watchlist</h1>
        <div className="rounded-lg border border-yellow-500/40 bg-yellow-500/10 p-6 text-yellow-100">
          <p className="font-medium">You need to be signed in to view your watchlist.</p>
          <Link href="/sign-in" className="mt-4 inline-flex items-center text-sm font-semibold underline">
            Go to sign in
          </Link>
        </div>
      </div>
    );
  }

  await connectToDatabase();

  const watchlistItems = await Watchlist.find({ userId: user.id })
    .sort({ createdAt: -1 })
    .lean();

  if (!watchlistItems.length) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold text-white">My Watchlist</h1>
        <div className="rounded-lg border border-dashed border-gray-700 bg-[#101010] p-10 text-center">
          <h2 className="text-xl font-semibold text-gray-100">Your watchlist is empty</h2>
          <p className="mt-3 text-sm text-gray-400">
            Start tracking stocks you love by adding them from the dashboard or stock detail pages.
          </p>
          <Link href="/" className="mt-6 inline-flex items-center justify-center rounded-md bg-yellow-500 px-4 py-2 text-sm font-semibold text-black transition hover:bg-yellow-400">
            Browse stocks
          </Link>
        </div>
      </div>
    );
  }

  return (
    <section className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-semibold text-white">My Watchlist</h1>
        <p className="text-sm text-gray-400">
          Keep track of symbols you care about and monitor their performance at a glance.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {watchlistItems.map((item) => {
          const symbol = String(item.symbol).toUpperCase();
          const company = item.company ? String(item.company) : symbol;
          const id = String(item._id ?? symbol);

          return (
            <div key={id} className="flex flex-col gap-4 rounded-xl border border-gray-800 bg-[#101010] p-4 shadow-lg">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-gray-100">{symbol}</h2>
                  <p className="text-sm text-gray-400">{company}</p>
                </div>
                <WatchlistButton symbol={symbol} company={company} isInWatchlist />
              </div>

              <TradingViewWidget
                scriptUrl={TRADINGVIEW_SCRIPT}
                config={CANDLE_CHART_WIDGET_CONFIG(symbol)}
                height={260}
                className="overflow-hidden rounded-lg"
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

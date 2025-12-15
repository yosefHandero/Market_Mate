import TradingViewWidget from "@/components/TradingViewWidget";
import MarketOverviewWrapper from "@/components/MarketOverviewWrapper";
import StockHeatmapWrapper from "@/components/StockHeatmapWrapper";
import {
  HEATMAP_WIDGET_CONFIG,
  MARKET_DATA_WIDGET_CONFIG,
  MARKET_OVERVIEW_WIDGET_CONFIG,
  TOP_STORIES_WIDGET_CONFIG,
} from "@/lib/constants";
import { getCurrentUser } from "@/lib/auth/session";
import { connectToDatabase } from "@/database/mongoose";
import { Watchlist } from "@/database/models/watchlist.model";

const Home = async () => {
  const scriptUrl = `https://s3.tradingview.com/external-embedding/embed-widget-`;

  // Fetch user's watchlist symbols
  const user = await getCurrentUser();
  let watchlistSymbols: string[] = [];

  if (user) {
    await connectToDatabase();
    const watchlistItems = await Watchlist.find({ userId: user.id })
      .select("symbol")
      .lean();
    watchlistSymbols = watchlistItems.map((item) => item.symbol.toUpperCase());
  }

  return (
    <div className="flex min-h-screen home-wrapper">
      <section className="grid w-full gap-8 home-section">
        <div className="md:col-span-1 xl:col-span-1">
          <MarketOverviewWrapper
            scriptUrl={`${scriptUrl}market-overview.js`}
            className="custom-chart"
            height={600}
            initialWatchlistSymbols={watchlistSymbols}
          />
        </div>
        <div className="md-col-span xl:col-span-2">
          <StockHeatmapWrapper
            scriptUrl={`${scriptUrl}stock-heatmap.js`}
            height={600}
            initialWatchlistSymbols={watchlistSymbols}
          />
        </div>
      </section>
      <section className="grid w-full gap-8 home-section">
        <div className="h-full md:col-span-1 xl:col-span-1">
          <TradingViewWidget
            scriptUrl={`${scriptUrl}timeline.js`}
            config={TOP_STORIES_WIDGET_CONFIG}
            height={600}
          />
        </div>
        <div className="h-full md:col-span-1 xl:col-span-2">
          <TradingViewWidget
            scriptUrl={`${scriptUrl}market-quotes.js`}
            config={MARKET_DATA_WIDGET_CONFIG}
            height={600}
          />
        </div>
      </section>
    </div>
  );
};

export default Home;

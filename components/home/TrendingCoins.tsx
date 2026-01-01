import { fetcher } from '@/lib/coingecko.actions';
import TrendingCoinsTable from './TrendingCoinsTable';
import { TrendingCoinsFallback } from './fallback';
import type { TrendingCoin } from '@/type';

const TrendingCoins = async () => {
  let trendingCoins: { coins: TrendingCoin[] } | undefined;

  try {
    trendingCoins = await fetcher<{ coins: TrendingCoin[] }>('/search/trending', undefined);
  } catch {
    return <TrendingCoinsFallback />;
  }

  return (
    <div id="trending-coins">
      <h4>Trending Coins</h4>
      <TrendingCoinsTable coins={trendingCoins.coins} />
    </div>
  );
};

export default TrendingCoins;

import { fetcher } from '@/lib/coingecko.actions';
import CoinsTable from '@/components/CoinsTable';
import CoinsPagination from '@/components/CoinsPagination';
import CoinComparison from '@/components/CoinComparison';
import type { NextPageProps, CoinMarketData } from '@/type';

const Coins = async ({ searchParams }: NextPageProps) => {
  const { page } = await searchParams;

  const currentPage = Number(page) || 1;
  const perPage = 10;

  const coinsData = await fetcher<CoinMarketData[]>('/coins/markets', {
    vs_currency: 'usd',
    order: 'market_cap_desc',
    per_page: perPage,
    page: currentPage,
    sparkline: 'false',
    price_change_percentage: '24h',
  });

  const hasMorePages = coinsData.length === perPage;

  const estimatedTotalPages = currentPage >= 100 ? Math.ceil(currentPage / 100) * 100 + 100 : 100;

  return (
    <main id="coins-page">
      <div className="content">
        <h4>All Coins</h4>

        <CoinComparison availableCoins={coinsData} maxSelection={3} className="mb-6" />

        <CoinsTable coins={coinsData} />

        <CoinsPagination
          currentPage={currentPage}
          totalPages={estimatedTotalPages}
          hasMorePages={hasMorePages}
        />
      </div>
    </main>
  );
};

export default Coins;

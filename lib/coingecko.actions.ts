'use server';

import qs from 'query-string';

const BASE_URL = process.env.COINGECKO_BASE_URL;
const API_KEY = process.env.COINGECKO_API_KEY;

if (!BASE_URL) throw new Error('Could not get base url');
if (!API_KEY) throw new Error('Could not get api key');

// Determine which API key header to use based on the base URL
const isProAPI = BASE_URL.includes('pro-api.coingecko.com');
const API_KEY_HEADER = isProAPI ? 'x-cg-pro-api-key' : 'x-cg-demo-api-key';

export async function fetcher<T>(
  endpoint: string,
  params?: QueryParams,
  revalidate = 60,
): Promise<T> {
  const url = qs.stringifyUrl(
    {
      url: `${BASE_URL}/${endpoint}`,
      query: params,
    },
    { skipEmptyString: true, skipNull: true },
  );

  // Remove cache option entirely for Node.js 22 compatibility
  // The cache option causes transformAlgorithm error in Node.js 22's fetch implementation
  const response = await fetch(url, {
    headers: {
      [API_KEY_HEADER]: API_KEY,
      'Content-Type': 'application/json',
    } as Record<string, string>,
  });

  if (!response.ok) {
    let errorMessage = response.statusText;
    try {
      const errorBody: CoinGeckoErrorBody = await response.json();
      errorMessage = errorBody.error || errorMessage;
      // If error is an object, stringify it
      if (typeof errorMessage === 'object') {
        errorMessage = JSON.stringify(errorMessage);
      }
    } catch {
      // If JSON parsing fails, use status text
    }

    throw new Error(`API Error: ${response.status}: ${errorMessage}`);
  }

  return response.json();
}

export async function searchCoins(query: string): Promise<SearchCoin[]> {
  try {
    const data = await fetcher<{ coins: SearchCoin[] }>('/search', { query });
    return data.coins.slice(0, 10);
  } catch (error) {
    console.error('Search error:', error);
    return [];
  }
}

export async function getPools(
  id: string,
  network?: string | null,
  contractAddress?: string | null,
): Promise<PoolData> {
  const fallback: PoolData = {
    id: '',
    address: '',
    name: '',
    network: '',
  };

  if (network && contractAddress) {
    try {
      const poolData = await fetcher<{ data: PoolData[] }>(
        `/onchain/networks/${network}/tokens/${contractAddress}/pools`,
      );

      return poolData.data?.[0] ?? fallback;
    } catch (error) {
      console.log(error);
      return fallback;
    }
  }

  try {
    const poolData = await fetcher<{ data: PoolData[] }>('/onchain/search/pools', { query: id });

    return poolData.data?.[0] ?? fallback;
  } catch {
    return fallback;
  }
}

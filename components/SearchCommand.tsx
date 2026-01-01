'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Search, Loader2 } from 'lucide-react';
import Image from 'next/image';
import Link from 'next/link';
import { Dialog, DialogContent, DialogTrigger, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useDebounce } from '@/hooks/useDebounce';
import { searchCoins } from '@/lib/coingecko.actions';
import { cn } from '@/lib/utils';
import type { SearchCoin } from '@/type';

const SearchCommand = () => {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [results, setResults] = useState<SearchCoin[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const router = useRouter();
  const buttonRef = useRef<HTMLButtonElement>(null);

  const debouncedQuery = useDebounce(searchQuery, 300);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    if (!open) {
      setSelectedIndex(0);
      setSearchQuery('');
      setResults([]);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [results.length]);

  useEffect(() => {
    if (!debouncedQuery || debouncedQuery.length < 2) {
      setResults([]);
      return;
    }

    const performSearch = async () => {
      setLoading(true);
      try {
        const coins = await searchCoins(debouncedQuery);
        setResults(coins);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    };

    performSearch();
  }, [debouncedQuery]);

  const handleSelect = (coinId: string) => {
    setOpen(false);
    setSearchQuery('');
    setResults([]);
    router.push(`/coins/${coinId}`);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev < results.length - 1 ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev > 0 ? prev - 1 : 0));
    } else if (e.key === 'Enter' && results[selectedIndex]) {
      e.preventDefault();
      handleSelect(results[selectedIndex].id);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          ref={buttonRef}
          id="search-modal"
          className="trigger px-6 hover:bg-transparent! font-medium transition-all h-full cursor-pointer text-base text-purple-100 flex items-center gap-2"
        >
          <Search className="h-4 w-4" />
          <span>Search</span>
          <kbd className="kbd pointer-events-none hidden sm:inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium opacity-100">
            ⌘K
          </kbd>
        </button>
      </DialogTrigger>
      <DialogContent className="dialog bg-dark-400! max-w-sm sm:max-w-md md:max-w-2xl mx-auto">
        <DialogTitle className="absolute w-px h-px p-0 -m-px overflow-hidden whitespace-nowrap border-0">
          Search for cryptocurrencies
        </DialogTitle>
        <div className="cmd-input bg-dark-500!">
          <div className="flex items-center gap-2 px-3">
            <Search className="h-4 w-4 text-purple-100" />
            <Input
              placeholder="Search coins..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setSelectedIndex(0);
              }}
              onKeyDown={handleKeyDown}
              className="placeholder:text-purple-100! border-0 bg-transparent focus-visible:ring-0"
              autoFocus
            />
            {loading && <Loader2 className="h-4 w-4 animate-spin text-purple-100" />}
          </div>
        </div>

        {results.length > 0 && (
          <div className="list bg-dark-500 max-h-100 overflow-y-auto">
            {results.map((coin, index) => (
              <Link
                key={coin.id}
                href={`/coins/${coin.id}`}
                onClick={() => handleSelect(coin.id)}
                className={cn(
                  'search-item grid grid-cols-4 gap-4 items-center justify-between transition-all cursor-pointer! hover:bg-dark-400 py-3 px-4',
                  {
                    'bg-dark-400': index === selectedIndex,
                  },
                )}
              >
                <div className="coin-info flex gap-4 items-center col-span-2">
                  <Image
                    src={coin.thumb}
                    alt={coin.name}
                    width={36}
                    height={36}
                    className="size-9 rounded-full"
                  />
                  <div>
                    <p className="font-medium">{coin.name}</p>
                    <p className="text-sm text-gray-400 uppercase">{coin.symbol}</p>
                  </div>
                </div>
                {coin.market_cap_rank && (
                  <div className="text-right text-sm text-gray-400">#{coin.market_cap_rank}</div>
                )}
              </Link>
            ))}
          </div>
        )}

        {debouncedQuery && debouncedQuery.length >= 2 && !loading && results.length === 0 && (
          <div className="empty py-6 text-center text-sm text-gray-400">No coins found</div>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default SearchCommand;

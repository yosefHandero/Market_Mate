'use client';

import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import SearchCommand from '@/components/SearchCommand';

const Header = () => {
  const pathname = usePathname();

  return (
    <header>
      <div className="main-container inner">
        <Link href="/" className="flex items-center gap-3">
          <Image
            src="/coin.jpg"
            alt="MarketMate logo"
            width={40}
            height={40}
            className="rounded-full object-cover"
          />
          <span className="text-xl font-bold text-purple-200">MarketMate</span>
        </Link>

        <nav>
          <Link
            href="/"
            className={cn('nav-link', {
              'is-active': pathname === '/',
              'is-home': true,
            })}
          >
            Home
          </Link>

          <Link
            href="/coins"
            className={cn('nav-link', {
              'is-active': pathname === '/coins',
            })}
          >
            All Coins
          </Link>

          <Link
            href="/top-movers"
            className={cn('nav-link', {
              'is-active': pathname === '/top-movers',
            })}
          >
            Top Movers
          </Link>

          <Link
            href="/volume-spikes"
            className={cn('nav-link', {
              'is-active': pathname === '/volume-spikes',
            })}
          >
            Volume Spikes
          </Link>

          <Link
            href="/near-high"
            className={cn('nav-link', {
              'is-active': pathname === '/near-high',
            })}
          >
            Near High
          </Link>

          <Link
            href="/accumulation"
            className={cn('nav-link', {
              'is-active': pathname === '/accumulation',
            })}
          >
            Accumulation
          </Link>

          <Link
            href="/market-summary"
            className={cn('nav-link', {
              'is-active': pathname === '/market-summary',
            })}
          >
            Market Summary
          </Link>

          <SearchCommand />
        </nav>
      </div>
    </header>
  );
};

export default Header;

import './globals.css';
import type { Metadata } from 'next';
import Link from 'next/link';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Market Mate Scanner',
  description: 'Decision-support and validation dashboard for evidence-backed market scanning.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <header className="top-nav">
          <div className="top-nav-inner">
            <Link href="/" className="brand">
              Market Mate Scanner
            </Link>
            <nav className="nav-links">
              <Link href="/">Actions</Link>
              <Link href="/history">History</Link>
            </nav>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}

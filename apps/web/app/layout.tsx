import './globals.css';
import type { Metadata } from 'next';
import Link from 'next/link';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Market Mate Scanner',
  description: 'Paper-only BUY candidate decisions and proof evidence from fresh scan data.',
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
            <span className="badge amber paper-mode-badge" data-testid="paper-mode-badge">
              PAPER MODE - DRY RUN ONLY
            </span>
            <nav className="nav-links">
              <Link href="/">Decision</Link>
              <Link href="/proof">Proof</Link>
            </nav>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}

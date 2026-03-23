import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Market Mate Scanner",
  description: "Personal stock scanner dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}

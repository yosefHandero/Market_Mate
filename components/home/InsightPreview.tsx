'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';

interface InsightPreviewProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  href: string;
  children: React.ReactNode;
  className?: string;
}

export default function InsightPreview({
  title,
  description,
  icon,
  href,
  children,
  className,
}: InsightPreviewProps) {
  return (
    <motion.div
      className={cn(
        'rounded-lg border border-purple-100/10 bg-gradient-to-br from-dark-400/80 to-dark-500/60 p-6 backdrop-blur-sm',
        className,
      )}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      whileHover={{ y: -2, transition: { duration: 0.2 } }}
    >
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-purple-600/20 p-2">{icon}</div>
          <div>
            <h3 className="text-lg font-semibold text-purple-100">{title}</h3>
            <p className="text-xs text-gray-400">{description}</p>
          </div>
        </div>
        <Link
          href={href}
          className="flex items-center gap-1 rounded-md bg-purple-600/20 px-3 py-1.5 text-sm text-purple-200 transition-colors hover:bg-purple-600/30"
        >
          View All
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>

      {children}
    </motion.div>
  );
}


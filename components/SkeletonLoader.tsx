'use client';

import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';

interface SkeletonLoaderProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
  animate?: boolean;
}

/**
 * Skeleton loader component to prevent layout shift
 */
export default function SkeletonLoader({
  className,
  variant = 'rectangular',
  width,
  height,
  animate = true,
}: SkeletonLoaderProps) {
  const baseClasses = 'bg-dark-500 rounded';

  const variantClasses = {
    text: 'h-4',
    circular: 'rounded-full',
    rectangular: 'rounded-md',
  };

  const style: React.CSSProperties = {
    width: width || (variant === 'circular' ? height || '40px' : '100%'),
    height:
      height || (variant === 'text' ? '1rem' : variant === 'circular' ? width || '40px' : '200px'),
  };

  if (animate) {
    return (
      <motion.div
        className={cn(baseClasses, variantClasses[variant], className)}
        style={style}
        animate={{
          opacity: [0.5, 1, 0.5],
        }}
        transition={{
          duration: 1.5,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />
    );
  }

  return (
    <div
      className={cn(baseClasses, variantClasses[variant], 'opacity-50', className)}
      style={style}
    />
  );
}

/**
 * Skeleton for table rows
 */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonLoader key={i} variant="rectangular" height="60px" />
      ))}
    </div>
  );
}

/**
 * Skeleton for cards
 */
export function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonLoader key={i} variant="rectangular" height="200px" />
      ))}
    </div>
  );
}

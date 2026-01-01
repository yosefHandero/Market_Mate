'use client';

import { useEffect, useRef } from 'react';
import { motion, useSpring, useMotionValue } from 'framer-motion';
import { formatCurrency } from '@/lib/utils';
import { cn } from '@/lib/utils';

interface AnimatedPriceProps {
  price: number;
  previousPrice?: number;
  className?: string;
  digits?: number;
  showChange?: boolean;
}

export default function AnimatedPrice({
  price,
  previousPrice,
  className,
  digits = 2,
  showChange = false,
}: AnimatedPriceProps) {
  const priceSpring = useSpring(price, {
    stiffness: 300,
    damping: 30,
    mass: 0.5,
  });

  const scale = useMotionValue(1);
  const color = useMotionValue('rgb(163, 163, 163)');
  const prevPriceRef = useRef(price);

  useEffect(() => {
    if (previousPrice !== undefined && previousPrice !== price) {
      const isIncrease = price > previousPrice;

      color.set(isIncrease ? 'rgb(74, 222, 128)' : 'rgb(248, 113, 113)');

      scale.set(1.1);
      setTimeout(() => {
        scale.set(1);
      }, 300);

      priceSpring.set(price);

      setTimeout(() => {
        color.set('rgb(163, 163, 163)');
      }, 1000);
    } else if (prevPriceRef.current !== price) {
      priceSpring.set(price);
      prevPriceRef.current = price;
    }
  }, [price, previousPrice, priceSpring, scale, color]);

  return (
    <motion.div
      className={cn('inline-block', className)}
      style={{
        scale,
        color,
      }}
      transition={{
        type: 'spring',
        stiffness: 300,
        damping: 30,
      }}
    >
      <motion.span>{formatCurrency(priceSpring.get(), digits)}</motion.span>
      {showChange && previousPrice !== undefined && previousPrice !== price && (
        <motion.span
          className={cn('ml-2 text-sm', price > previousPrice ? 'text-green-400' : 'text-red-400')}
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
        >
          {price > previousPrice ? '↑' : '↓'}
        </motion.span>
      )}
    </motion.div>
  );
}

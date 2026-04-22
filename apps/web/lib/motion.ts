'use client';

import type { Transition, Variants } from 'framer-motion';

export const motionTiming = {
  fast: 0.16,
  base: 0.22,
  slow: 0.3,
};

export const motionEase = [0.22, 1, 0.36, 1] as const;

export const transitions = {
  base: {
    duration: motionTiming.base,
    ease: motionEase,
  } satisfies Transition,
  fast: {
    duration: motionTiming.fast,
    ease: motionEase,
  } satisfies Transition,
};

export const pageVariants: Variants = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: transitions.base,
  },
};

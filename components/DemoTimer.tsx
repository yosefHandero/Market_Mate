"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface DemoTimerProps {
  isDemoMode: boolean;
}

const DemoTimer = ({ isDemoMode }: DemoTimerProps) => {
  const router = useRouter();
  const [elapsed, setElapsed] = useState(0);
  const totalDuration = 45; // 45 seconds total

  useEffect(() => {
    if (!isDemoMode) return;

    // Navigate to sign-in after 45 seconds (matching the visual timer)
    const redirectTimer = setTimeout(() => {
      router.push("/sign-in");
    }, totalDuration * 1000); // 45 seconds

    // Track elapsed time for visual progress
    const progressInterval = setInterval(() => {
      setElapsed((prev) => {
        if (prev >= totalDuration) {
          clearInterval(progressInterval);
          return totalDuration;
        }
        return prev + 1;
      });
    }, 1000);

    return () => {
      clearTimeout(redirectTimer);
      clearInterval(progressInterval);
    };
  }, [isDemoMode, router, totalDuration]);

  if (!isDemoMode) return null;

  const progress = (elapsed / totalDuration) * 100;
  const circumference = 2 * Math.PI * 18; // radius of 18
  const strokeDashoffset = circumference - (progress / 100) * circumference;

  return (
    <div className="fixed top-4 right-4 z-50">
      <div className="relative w-12 h-12">
        <svg className="transform -rotate-90 w-12 h-12">
          <circle
            cx="24"
            cy="24"
            r="18"
            stroke="currentColor"
            strokeWidth="4"
            fill="none"
            className="text-gray-700"
          />
          <circle
            cx="24"
            cy="24"
            r="18"
            stroke="currentColor"
            strokeWidth="4"
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className="text-yellow-500 transition-all duration-1000 ease-linear"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-semibold text-yellow-500">45</span>
        </div>
      </div>
    </div>
  );
};

export default DemoTimer;

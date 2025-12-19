import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: false, // Enable ESLint during builds to catch errors
  },
  typescript: {
    ignoreBuildErrors: false, // Enable TypeScript checking during builds
  },
};

export default nextConfig;

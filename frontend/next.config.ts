import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The chat route proxies an SSE stream; keep it on the Node runtime so the
  // response body is piped through rather than buffered.
  experimental: {
    proxyTimeout: 180_000,
  },
};

export default nextConfig;

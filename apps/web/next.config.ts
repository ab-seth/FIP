import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@fip/contracts"],
};

export default nextConfig;

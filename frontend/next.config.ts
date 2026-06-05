import type { NextConfig } from "next";
import path from "path";

// SHC_KEY must match APPLE_WEBHOOK_KEY (or SHC_ADMIN_KEY) in backend/.env.
// This is a single-user local app — hardcoding the key here is acceptable.
// If you rotate the key, update it in backend/.env AND here.
const SHC_KEY = process.env.NEXT_PUBLIC_SHC_KEY ?? "krEb3C7gzhcg9PiohX5hlvKLPpxuqyrV6Bz-MsMgokY";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
  env: {
    NEXT_PUBLIC_SHC_KEY: SHC_KEY,
  },
};

export default nextConfig;

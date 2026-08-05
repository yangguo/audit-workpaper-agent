/** @type {import('next').NextConfig} */
const nextConfig = {
  serverExternalPackages: [],
  // Disable webpack's persistent filesystem cache. On memory-constrained
  // machines (and under Node 24's V8) the PackFileCacheStrategy allocates
  // large ArrayBuffers that trigger "young object promotion failed" OOMs
  // during GC. The dev server recompiles fast enough without it.
  webpack: (config, { dev }) => {
    if (dev) {
      config.cache = false;
    }
    return config;
  },
};

export default nextConfig;

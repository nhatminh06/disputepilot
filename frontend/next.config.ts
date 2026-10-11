import type { NextConfig } from 'next';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// Keep the existing development credential in the repository's server-only environment.
const envFile = resolve(process.cwd(), '../.env');
if (existsSync(envFile)) process.loadEnvFile(envFile);

const config: NextConfig = {
  output: 'standalone',
  agentRules: false,
  poweredByHeader: false,
  devIndicators: false,
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Referrer-Policy', value: 'no-referrer' },
    ] }];
  },
};
export default config;

import type { NextConfig } from 'next';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// Public mode must be selected before startup, not enabled by loading local credentials.
process.env.DISPUTEPILOT_PUBLIC_DEMO ??= 'false';
const envFile = resolve(process.cwd(), '../.env');
if (process.env.DISPUTEPILOT_PUBLIC_DEMO !== 'true' && existsSync(envFile)) process.loadEnvFile(envFile);

const config: NextConfig = {
  output: process.env.DISPUTEPILOT_PUBLIC_DEMO === 'true' ? undefined : 'standalone',
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

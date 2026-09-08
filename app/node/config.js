// Configuration read from environment variables.
// Defaults match the no-Docker fallback (SQLite + local ERP). Docker Compose
// overrides these to point at the `postgres` and `erp` services.

import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// <repo>/data, resolved from this file so the default works from any cwd.
const DEFAULT_DATA_DIR = path.resolve(__dirname, '../../data');

export function loadConfig() {
  return {
    databaseUrl: process.env.DATABASE_URL ?? 'sqlite:///./app.sqlite',
    erpBaseUrl: process.env.ERP_BASE_URL ?? 'http://localhost:9000',
    dataDir: process.env.DATA_DIR ?? DEFAULT_DATA_DIR,
  };
}

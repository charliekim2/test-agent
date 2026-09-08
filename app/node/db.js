// Database connection helper (a STUB — wire it up however you like).
// Branches on the DATABASE_URL scheme:
//   sqlite:///./app.sqlite        -> built-in node:sqlite (fallback default)
//   postgresql://user:pw@host/db  -> pg (Docker default)
//
// No schema or migrations are created for you: modeling the documents and their
// relationships is part of the task. You may also ignore this entirely and work
// in memory from the seed documents (see seed.js).

import { loadConfig } from './config.js';

export async function getConnection() {
  const url = loadConfig().databaseUrl;

  if (url.startsWith('sqlite:')) {
    const { DatabaseSync } = await import('node:sqlite'); // built-in, no native dep
    const file = url.replace('sqlite:///', '') || ':memory:';
    return new DatabaseSync(file);
  }

  if (url.startsWith('postgres')) {
    const { Client } = await import('pg'); // pure JS
    const client = new Client({ connectionString: url });
    await client.connect();
    return client;
  }

  throw new Error(`Unsupported DATABASE_URL scheme: ${url}`);
}

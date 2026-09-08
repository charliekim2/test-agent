// Load the seed documents from DATA_DIR.
// Each document is one JSON file under data/purchase_orders/ and data/invoices/.
// Files are loaded independently: a file that fails to parse is reported in the
// returned `errors` array rather than crashing the whole load (one seed file is
// deliberately corrupt — detecting and handling bad uploads is part of the task).

import fs from 'node:fs';
import path from 'node:path';
import { loadConfig } from './config.js';

function loadDir(dir, errors) {
  const docs = [];
  if (!fs.existsSync(dir)) {
    errors.push({ file: dir, error: 'directory not found' });
    return docs;
  }
  for (const name of fs.readdirSync(dir).sort()) {
    if (!name.endsWith('.json')) continue;
    const full = path.join(dir, name);
    try {
      docs.push(JSON.parse(fs.readFileSync(full, 'utf-8')));
    } catch (err) {
      errors.push({ file: full, error: String(err.message ?? err) });
    }
  }
  return docs;
}

export function loadDocuments() {
  const { dataDir } = loadConfig();
  const errors = [];
  const purchaseOrders = loadDir(path.join(dataDir, 'purchase_orders'), errors);
  const invoices = loadDir(path.join(dataDir, 'invoices'), errors);
  return { purchaseOrders, invoices, errors };
}

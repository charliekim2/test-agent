// Entrypoint for the Node solution.
// The scaffold below just proves the wiring works: it loads config, reads the
// seed documents, and pings the ERP. Replace the TODO block with your solution.

import { loadConfig } from './config.js';
import { ErpClient } from './erpClient.js';
import { loadDocuments } from './seed.js';

async function main() {
  const cfg = loadConfig();
  console.log(`[scaffold] DATABASE_URL = ${cfg.databaseUrl}`);
  console.log(`[scaffold] ERP_BASE_URL = ${cfg.erpBaseUrl}`);
  console.log(`[scaffold] DATA_DIR     = ${cfg.dataDir}`);

  const docs = loadDocuments();
  console.log(`[scaffold] loaded ${docs.purchaseOrders.length} POs, ${docs.invoices.length} invoices`);
  if (docs.errors.length) {
    console.log(`[scaffold] ${docs.errors.length} document(s) failed to load:`);
    for (const e of docs.errors) console.log(`             - ${e.file}: ${e.error}`);
  }

  const erp = new ErpClient();
  try {
    console.log('[scaffold] ERP health:', await erp.health());
    console.log('[scaffold] ERP vendors:', (await erp.vendors()).length);
  } catch (err) {
    console.log(`[scaffold] ERP not reachable (${err}). Is the ERP running?`);
  }

  // =======================================================================
  // TODO(candidate): implement the solution here.
  //
  // Part 1 — matching:
  //   - Match each invoice to its purchase order; surface exceptions
  //     (amount/vendor/quantity mismatches, orphans, ...).
  //   - Score similarity and auto-link above some threshold.
  //
  // Part 2 — ERP readiness & posting:
  //   - Define a drift tolerance to decide if a doc set is ready to post.
  //   - Resolve each document's vendor to a vendor_id via erp.vendors().
  //   - Transform ready invoices into a bill and erp.postBill(...) it.
  //
  // Storage is your choice: use getConnection() from db.js, or work in memory.
  // =======================================================================
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

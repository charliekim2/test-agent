// Thin client for the fake ERP API (base URL from ERP_BASE_URL).
// Endpoints:
//   GET  /vendors  -> resolve a document's vendor to a vendor_id
//   POST /bills    -> post a bill (the final correctness check)

import { loadConfig } from './config.js';

export class ErpClient {
  constructor(baseUrl) {
    this.base = (baseUrl ?? loadConfig().erpBaseUrl).replace(/\/$/, '');
  }

  async health() {
    const res = await fetch(`${this.base}/health`);
    return res.json();
  }

  async vendors() {
    const res = await fetch(`${this.base}/vendors`);
    return res.json();
  }

  // POST a bill. Returns { status, body } so you can inspect the HTTP status
  // (201 success, 404/422 validation failure) and the parsed JSON body.
  async postBill(bill) {
    const res = await fetch(`${this.base}/bills`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(bill),
    });
    return { status: res.status, body: await res.json() };
  }
}

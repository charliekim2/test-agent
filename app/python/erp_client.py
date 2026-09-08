"""Thin client for the fake ERP API (base URL from ERP_BASE_URL).

Endpoints:
  GET  /vendors  -> resolve a document's vendor to a vendor_id
  POST /bills    -> post a bill (the final correctness check)
"""

from __future__ import annotations

import requests

from config import load_config


class ErpClient:
    def __init__(self, base_url: str | None = None, timeout: float = 5.0):
        self.base = (base_url or load_config().erp_base_url).rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        return requests.get(f"{self.base}/health", timeout=self.timeout).json()

    def vendors(self) -> list[dict]:
        return requests.get(f"{self.base}/vendors", timeout=self.timeout).json()

    def post_bill(self, bill: dict) -> requests.Response:
        """POST a bill. Returns the raw Response so you can inspect the status
        code (201 success, 404/422 validation failure) and the JSON body."""
        return requests.post(f"{self.base}/bills", json=bill, timeout=self.timeout)

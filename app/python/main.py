"""Entrypoint for the Python solution.

The scaffold below just proves the wiring works: it loads config, reads the
seed documents, and pings the ERP. Replace the TODO block with your solution.
"""

from __future__ import annotations

from config import load_config
from erp_client import ErpClient
from seed import load_documents


def main() -> None:
    cfg = load_config()
    print(f"[scaffold] DATABASE_URL = {cfg.database_url}")
    print(f"[scaffold] ERP_BASE_URL = {cfg.erp_base_url}")
    print(f"[scaffold] DATA_DIR     = {cfg.data_dir}")

    docs = load_documents()
    print(f"[scaffold] loaded {len(docs.purchase_orders)} POs, {len(docs.invoices)} invoices")
    if docs.errors:
        print(f"[scaffold] {len(docs.errors)} document(s) failed to load:")
        for e in docs.errors:
            print(f"             - {e['file']}: {e['error']}")

    erp = ErpClient()
    try:
        print(f"[scaffold] ERP health: {erp.health()}")
        print(f"[scaffold] ERP vendors: {len(erp.vendors())}")
    except Exception as exc:  # noqa: BLE001
        print(f"[scaffold] ERP not reachable ({exc}). Is the ERP running?")

    # =====================================================================
    # TODO(candidate): implement the solution here.
    #
    # Part 1 — matching:
    #   - Match each invoice to its purchase order; surface exceptions
    #     (amount/vendor/quantity mismatches, orphans, ...).
    #   - Score similarity and auto-link above some threshold.
    #
    # Part 2 — ERP readiness & posting:
    #   - Define a drift tolerance to decide if a doc set is ready to post.
    #   - Resolve each document's vendor to a vendor_id via erp.vendors().
    #   - Transform ready invoices into a bill and erp.post_bill(...) it.
    #
    # Storage is your choice: use db.get_connection(), or work in memory.
    # =====================================================================


if __name__ == "__main__":
    main()

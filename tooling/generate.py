"""Generate every candidate-facing artifact from the SSOT (ground_truth.py).

⚠️  MAINTAINER ONLY. Run via ``make generate`` (uses the ERP venv so the
    OpenAPI export can import the FastAPI app).

Emits:
  data/purchase_orders/*.json , data/invoices/*.json   seed documents
  erp/vendors.json                                      GET /vendors payload
  erp/relationships.json                                salted hashes only
  erp/openapi.json (+ erp/openapi.yaml if PyYAML present)

Deterministic: same input -> byte-identical output (no timestamps/randomness),
so re-running is idempotent.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

sys.path.insert(0, str(HERE))
import ground_truth as gt  # noqa: E402

PO_DIR = ROOT / "data" / "purchase_orders"
INV_DIR = ROOT / "data" / "invoices"
ERP_DIR = ROOT / "erp"

# Hidden generalization set lives under tooling/ (excluded from `make bundle`).
HIDDEN_PO_DIR = HERE / "hidden_data" / "purchase_orders"
HIDDEN_INV_DIR = HERE / "hidden_data" / "invoices"


def _vendor_block(doc: dict) -> dict:
    """Build the document-side vendor object, applying per-doc omissions."""
    v = gt.VENDORS_BY_ID[doc["vendor"]]
    omit = set(doc.get("omit_vendor", []))
    block: dict = {"name": v["doc_name"]}
    if "address" not in omit:
        block["address"] = dict(v["address"])
    if "contact" not in omit:
        block["contact"] = dict(v["contact"])
    if doc.get("show_tax_id") and "tax_id" not in omit and v.get("tax_id"):
        block["tax_id"] = v["tax_id"]
    return block


def _line_obj(t: tuple) -> dict:
    obj = {"description": t[0], "quantity": t[1], "unit_price": t[2], "line_total": t[3]}
    if len(t) >= 5 and t[4]:
        obj["sku"] = t[4]
    return obj


def build_document(doc: dict) -> dict:
    """Turn an SSOT doc spec into the JSON document the candidate receives."""
    out: dict = {}
    if doc["kind"] == "po":
        out["document_type"] = "purchase_order"
        out["po_number"] = doc["number"]
    else:
        out["document_type"] = "invoice"
        out["invoice_number"] = doc["number"]
        if doc.get("references_po") is not None:
            out["references_po"] = doc["references_po"]
    out["vendor"] = _vendor_block(doc)
    out["currency"] = doc.get("currency", "USD")
    if "issue_date" in doc:
        out["issue_date"] = doc["issue_date"]
    out["line_items"] = [_line_obj(t) for t in doc["lines"]]
    for k in ("subtotal", "shipping", "tax", "discount"):
        if k in doc:
            out[k] = doc[k]
    out["total"] = doc["total"]
    for k, val in doc.get("extra", {}).items():
        out[k] = val
    return out


def _write_json(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_documents() -> dict:
    for d in (PO_DIR, INV_DIR, HIDDEN_PO_DIR, HIDDEN_INV_DIR):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.json"):
            f.unlink()  # clean rebuild so removed fixtures don't linger

    counts = {"pos": 0, "invoices": 0, "hidden_pos": 0, "hidden_invoices": 0}
    for doc in gt.DOCS:
        payload = build_document(doc)
        hidden = doc.get("hidden", False)
        if doc["kind"] == "po":
            target = HIDDEN_PO_DIR if hidden else PO_DIR
            _write_json(target / f"{doc['number']}.json", payload)
            counts["hidden_pos" if hidden else "pos"] += 1
        else:
            target = HIDDEN_INV_DIR if hidden else INV_DIR
            _write_json(target / f"{doc['number']}.json", payload)
            counts["hidden_invoices" if hidden else "invoices"] += 1

    # Malformed fixtures (visible set only).
    _write_json(INV_DIR / f"{gt.MALFORMED_INVOICE['invoice_number']}.json", gt.MALFORMED_INVOICE)
    counts["invoices"] += 1
    (PO_DIR / f"{gt.CORRUPT_PO_NUMBER}.json").write_text(gt.CORRUPT_PO_TEXT, encoding="utf-8")
    counts["pos"] += 1
    return counts


def write_vendors() -> None:
    vendors = [
        {
            "vendor_id": v["vendor_id"],
            "canonical_name": v["canonical_name"],
            "address": v["address"],
            "contact": v["contact"],
            "tax_id": v["tax_id"],
        }
        for v in gt.VENDORS
    ]
    _write_json(ERP_DIR / "vendors.json", vendors)


def write_relationships() -> None:
    vorders = gt.vendor_orders()
    oinvs = gt.order_invoices()

    vendor_order_hashes = sorted(
        gt.hash_pair(vendor_id, order)
        for vendor_id, orders in vorders.items()
        for order in orders
    )
    order_invoice_hashes = sorted(
        gt.hash_pair(order, inv)
        for order, invs in oinvs.items()
        for inv in invs
    )
    _write_json(
        ERP_DIR / "relationships.json",
        {
            "_comment": "Salted SHA-256 hashes of valid (vendor_id|order) and "
                        "(order|invoice) pairs. No plaintext mapping is shipped.",
            "salt": gt.SALT,
            "vendor_order_hashes": vendor_order_hashes,
            "order_invoice_hashes": order_invoice_hashes,
        },
    )


def write_openapi() -> None:
    """Export a static OpenAPI spec by importing the FastAPI app.

    Resilient: if FastAPI isn't importable, skip with a warning (the live
    service still serves /openapi.json and /docs).
    """
    try:
        spec = importlib.util.spec_from_file_location("erp_app", ERP_DIR / "app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        schema = module.app.openapi()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! skipped openapi export ({exc})")
        return

    _write_json(ERP_DIR / "openapi.json", schema)
    try:
        import yaml  # type: ignore

        (ERP_DIR / "openapi.yaml").write_text(
            yaml.safe_dump(schema, sort_keys=False), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        print("  ! PyYAML not available; wrote openapi.json only")


def main() -> None:
    counts = write_documents()
    write_vendors()
    write_relationships()   # must precede write_openapi (app.py reads this file)
    write_openapi()
    print(f"visible: {counts['pos']} PO files, {counts['invoices']} invoice files -> data/")
    print(f"hidden:  {counts['hidden_pos']} PO files, {counts['hidden_invoices']} invoice files -> tooling/hidden_data/")
    print(f"  -> {PO_DIR}")
    print(f"  -> {INV_DIR}")
    print(f"  -> {HIDDEN_PO_DIR}")
    print(f"  -> {HIDDEN_INV_DIR}")
    print(f"  -> {ERP_DIR / 'vendors.json'}")
    print(f"  -> {ERP_DIR / 'relationships.json'}")


if __name__ == "__main__":
    main()

"""Maintainer guardrail: assert the SSOT, seed docs, and ERP relationship
hashes stay internally consistent. Run with ``pytest tooling/`` or directly
(``python tooling/test_consistency.py``).

This catches arithmetic typos and linkage drift *before* an interview, where a
"correct" bill silently failing to post would derail the session.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ground_truth as gt  # noqa: E402
from generate import build_document  # noqa: E402

TOL = 0.005

PO_NUMBERS = {d["number"] for d in gt.DOCS if d["kind"] == "po"}
INV_NUMBERS = {d["number"] for d in gt.DOCS if d["kind"] == "invoice"}


def test_vendor_ids_are_unique_and_referenced_exist():
    ids = [v["vendor_id"] for v in gt.VENDORS]
    assert len(ids) == len(set(ids)), "duplicate vendor_id"
    for d in gt.DOCS:
        assert d["vendor"] in gt.VENDORS_BY_ID, f"{d['number']} references unknown vendor {d['vendor']}"


def test_document_numbers_unique():
    nums = [d["number"] for d in gt.DOCS]
    assert len(nums) == len(set(nums)), "duplicate document number"


def test_clean_documents_reconcile_internally():
    """Every authored (non-malformed) doc must be internally consistent."""
    for d in gt.DOCS:
        line_sum = round(sum(t[3] for t in d["lines"]), 2)
        if "subtotal" in d:
            assert abs(d["subtotal"] - line_sum) < TOL, f"{d['number']}: subtotal != sum(line_total)"
        base = d["subtotal"] if "subtotal" in d else line_sum
        expected_total = base + d.get("shipping", 0.0) + d.get("tax", 0.0) - d.get("discount", 0.0)
        assert abs(d["total"] - expected_total) < TOL, f"{d['number']}: total does not reconcile"


def test_line_math_is_consistent():
    for d in gt.DOCS:
        for desc, qty, unit, line_total, *_ in d["lines"]:
            assert abs(qty * unit - line_total) < TOL, f"{d['number']}: {desc} qty*unit != line_total"


def test_invoice_links_point_to_real_pos_or_orphan():
    for d in gt.DOCS:
        if d["kind"] != "invoice":
            continue
        bt = d.get("belongs_to")
        assert bt is None or bt in PO_NUMBERS, f"{d['number']} belongs_to unknown PO {bt}"


def test_every_invoice_in_at_most_one_order():
    oinvs = gt.order_invoices()
    seen: dict[str, str] = {}
    for order, invs in oinvs.items():
        for inv in invs:
            assert inv not in seen, f"{inv} claimed by both {seen[inv]} and {order}"
            seen[inv] = order


def test_orphans_are_actually_orphaned():
    oinvs = gt.order_invoices()
    all_linked = {inv for invs in oinvs.values() for inv in invs}
    # Orphan invoices (visible: INV-2007; hidden: INV-3006) belong to no order.
    for orphan_inv in ("INV-2007", "INV-3006"):
        assert orphan_inv not in all_linked, f"{orphan_inv} leaked into a relationship"
    # Orphan POs (visible: PO-1006; hidden: PO-2005) have no invoices.
    for orphan_po in ("PO-1006", "PO-2005"):
        assert oinvs[orphan_po] == [], f"orphan PO {orphan_po} unexpectedly has invoices"


def test_built_documents_have_required_core_fields():
    for d in gt.DOCS:
        doc = build_document(d)
        assert "document_type" in doc and "total" in doc
        assert doc["vendor"].get("name")
        assert doc["line_items"], f"{d['number']} has no line items"
        if d["kind"] == "po":
            assert doc["po_number"].startswith("PO-")
        else:
            assert doc["invoice_number"].startswith("INV-")


def test_hashing_round_trips():
    """A known-valid pair hashes into the set; a known-invalid pair does not."""
    vorders = gt.vendor_orders()
    oinvs = gt.order_invoices()
    valid_vo = {gt.hash_pair(v, o) for v, os in vorders.items() for o in os}
    valid_oi = {gt.hash_pair(o, i) for o, iv in oinvs.items() for i in iv}

    # VEND-001 owns PO-1001; VEND-002 does not.
    assert gt.hash_pair("VEND-001", "PO-1001") in valid_vo
    assert gt.hash_pair("VEND-002", "PO-1001") not in valid_vo
    # PO-1002 owns INV-2002; the orphan INV-2007 belongs to nothing.
    assert gt.hash_pair("PO-1002", "INV-2002") in valid_oi
    assert gt.hash_pair("PO-1005", "INV-2007") not in valid_oi


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\nAll {len(fns)} consistency checks passed.")

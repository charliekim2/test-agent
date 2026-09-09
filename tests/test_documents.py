"""Visible tests for app/python/documents.py (WO-0001 / FEAT-001).

Covers money/vendor normalisation, recursive loading with fault isolation,
classification, structural validation (records, never discards), sorting and
determinism.  Uses tmp_path only - never the repository's data/ directory.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app", "python"))

from documents import (  # noqa: E402
    load_documents,
    normalize_money,
    normalize_vendor_name,
    to_cents,
)

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def test_normalize_money():
    assert normalize_money(3240.0) == 3240.0
    assert normalize_money("3,240.00") == 3240.0
    assert normalize_money("$1,234.50") == 1234.5
    assert normalize_money(" 1500 ") == 1500.0
    assert normalize_money("20") == 20.0
    assert normalize_money(None) is None
    assert normalize_money("") is None
    assert normalize_money("abc") is None
    assert normalize_money("  ") is None


def test_to_cents():
    assert to_cents(0.145) == 15  # ROUND_HALF_UP via Decimal(str(v))
    assert to_cents(49.6) == 4960
    assert to_cents(79.04) == 7904
    assert to_cents(1117.04) == 111704
    assert to_cents("3,240.00") == 324000
    assert to_cents(0) == 0
    assert to_cents(None) is None
    assert to_cents("abc") is None
    assert to_cents("$1,234.50") == 123450
    assert to_cents("") is None


def test_normalize_vendor_name():
    assert normalize_vendor_name("Globex Corporation") == normalize_vendor_name("Globex Corp")
    assert normalize_vendor_name("Globex Corp.") == normalize_vendor_name("Globex Corporation")
    assert normalize_vendor_name("Globex Ltd") == normalize_vendor_name("Globex Limited")
    assert normalize_vendor_name("Globex Co") == normalize_vendor_name("Globex Company")
    assert normalize_vendor_name("Globex LLC") == normalize_vendor_name("Globex L.L.C.")
    assert normalize_vendor_name("Smith & Sons") == normalize_vendor_name("Smith and Sons")
    # Unrelated vendors must stay apart.
    assert normalize_vendor_name("Acme Office Supplies") != normalize_vendor_name(
        "Acme Industrial Coatings"
    )
    assert normalize_vendor_name("Umbrella Industries") != normalize_vendor_name("Stark Industrial")
    assert normalize_vendor_name("Wayne Ent.") != normalize_vendor_name("Wayne Holdings")
    # Combining marks collapse (Cafe Ltee forms).
    assert normalize_vendor_name("Café Ltée") == normalize_vendor_name("Cafe Ltee")
    assert normalize_vendor_name(None) == ""


# ---------------------------------------------------------------------------
# load_documents
# ---------------------------------------------------------------------------


def _po(**over):
    doc = {
        "document_type": "purchase_order",
        "po_number": "PO-1002",
        "vendor": {"name": "Globex Corporation"},
        "currency": "USD",
        "issue_date": "2026-05-04",
        "line_items": [
            {
                "sku": "BRK-01",
                "description": "Bracket, steel",
                "quantity": 100,
                "unit_price": 4.00,
                "line_total": 400.00,
            }
        ],
        "subtotal": 400.00,
        "tax": 32.00,
        "total": 432.00,
    }
    doc.update(over)
    return doc


def _inv(**over):
    doc = {
        "document_type": "invoice",
        "invoice_number": "INV-2010",
        "references_po": "PO-1002",
        "vendor": {"name": "Globex Corp"},
        "currency": "USD",
        "issue_date": "2026-05-21",
        "line_items": [
            {
                "description": "Consulting services, hrs",
                "quantity": "20",
                "unit_price": 150.00,
                "line_total": 3000.00,
            }
        ],
        "total": "$1,234.50",
    }
    doc.update(over)
    return doc


def test_flat_layout_worked_example(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_po()), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(_inv()), encoding="utf-8")
    broken = (
        '{"document_type": "purchase_order", "po_number": "PO-1009",'
        ' "vendor": { "name": "Initech LLC", },'
        ' "line_items": [{"description": "Server rack, 42U", "quantity": 2'
    )
    (tmp_path / "broken.json").write_text(broken, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.json").write_text(
        json.dumps(
            {
                "document_type": "invoice",
                "invoice_number": "INV-2001",
                "vendor": {"name": "X Corp"},
                "currency": "USD",
                "issue_date": "2026-01-01",
                "line_items": [],
                "total": 0,
            }
        ),
        encoding="utf-8",
    )

    result = load_documents(str(tmp_path))

    assert len(result["purchase_orders"]) == 1
    po = result["purchase_orders"][0]
    assert po["document_number"] == "PO-1002"
    assert po["path"] == "a.json"  # relative, POSIX
    assert po["total_cents"] == 43200
    assert po["total"] == 432.0
    assert po["shipping"] == 0  # absent -> 0
    assert po["discount"] == 0
    assert po["vendor_name"] == "Globex Corporation"  # raw, unmutated
    assert po["document_type"] == "purchase_order"
    assert po["vendor"] == {"name": "Globex Corporation"}
    assert po["vendor_name_normalized"] == "globex"

    invs = {d["document_number"]: d for d in result["invoices"]}
    assert set(invs) == {"INV-2010", "INV-2001"}
    inv = invs["INV-2010"]
    assert inv["total"] == 1234.5
    assert inv["total_cents"] == 123450
    assert inv["references_po"] == "PO-1002"  # a hint, not truth
    assert inv["path"] == "b.json"
    assert inv["vendor_name"] == "Globex Corp"
    assert inv["vendor_name_normalized"] == "globex"

    # Fault isolation: broken.json is malformed, not a PO, not counted.
    assert len(result["malformed"]) == 1
    assert result["malformed"][0]["path"] == "broken.json"
    assert "purchase_order" not in [po2["document_number"] for po2 in result["purchase_orders"]]

    # INV-2010 is retained AND flagged (quantity "20", total "$1,234.50").
    paths = {v["path"] for v in result["schema_violations"]}
    assert "b.json" in paths
    b_entry = next(v for v in result["schema_violations"] if v["path"] == "b.json")
    assert b_entry["document_number"] == "INV-2010"
    assert b_entry["problems"]
    assert any("quantity" in p for p in b_entry["problems"])
    assert any("total" in p for p in b_entry["problems"])

    # The whole result must be json.dumps-able.
    json.dumps(result)


def test_nested_layout(tmp_path):
    po_dir = tmp_path / "purchase_orders"
    inv_dir = tmp_path / "invoices"
    po_dir.mkdir()
    inv_dir.mkdir()
    (po_dir / "PO-2001.json").write_text(
        json.dumps(_po(po_number="PO-2001", total=100.0)), encoding="utf-8"
    )
    (po_dir / "PO-1001.json").write_text(
        json.dumps(_po(po_number="PO-1001", total=50.0)), encoding="utf-8"
    )
    (inv_dir / "INV-3001.json").write_text(
        json.dumps(_inv(invoice_number="INV-3001", total=100.0)), encoding="utf-8"
    )

    result = load_documents(str(tmp_path))
    # Sorted ascending by document_number.
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1001", "PO-2001"]
    assert [i["document_number"] for i in result["invoices"]] == ["INV-3001"]
    assert result["purchase_orders"][0]["path"] == "purchase_orders/PO-1001.json"
    assert result["invoices"][0]["path"] == "invoices/INV-3001.json"


def test_classification_fallback_no_document_type(tmp_path):
    # No document_type at all: classified from the number fields.
    (tmp_path / "x.json").write_text(
        json.dumps({"po_number": "PO-7", "total": 1.0}), encoding="utf-8"
    )
    (tmp_path / "y.json").write_text(
        json.dumps({"invoice_number": "INV-8", "total": 1.0}), encoding="utf-8"
    )
    result = load_documents(str(tmp_path))
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-7"]
    assert [i["document_number"] for i in result["invoices"]] == ["INV-8"]
    # Missing required fields are recorded, documents are retained.
    assert len(result["schema_violations"]) == 2


def test_empty_and_non_json(tmp_path):
    assert load_documents(str(tmp_path)) == {
        "purchase_orders": [],
        "invoices": [],
        "malformed": [],
        "schema_violations": [],
    }
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b", encoding="utf-8")
    assert load_documents(str(tmp_path))["purchase_orders"] == []


def test_raises_valueerror_for_bad_data_dir(tmp_path):
    with pytest.raises(ValueError):
        load_documents(str(tmp_path / "does_not_exist"))
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        load_documents(str(f))


def test_schema_violations_record_not_discard(tmp_path):
    doc = {
        "document_type": "purchase_order",
        "po_number": "PO-5",
        "vendor": {"name": "Umbrella Industries", "address": "1 Main St"},
        "currency": "USD",
        "issue_date": "2026-02-02",
        "line_items": "not a list",
        "total": 0,
    }
    (tmp_path / "po5.json").write_text(json.dumps(doc), encoding="utf-8")
    result = load_documents(str(tmp_path))
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-5"]
    assert result["purchase_orders"][0]["line_items"] == []
    assert result["purchase_orders"][0]["total_cents"] == 0
    (violation,) = result["schema_violations"]
    assert violation["document_number"] == "PO-5"
    assert violation["path"] == "po5.json"
    assert any("line_items" in p for p in violation["problems"])


def test_document_without_number_sorts_last(tmp_path):
    for name in ("PO-2", "PO-1"):
        (tmp_path / ("%s.json" % name)).write_text(
            json.dumps(_po(po_number=name)), encoding="utf-8"
        )
    (tmp_path / "nonum.json").write_text(
        json.dumps(
            {
                "document_type": "purchase_order",
                "vendor": {"name": "Zed Corp"},
                "currency": "EUR",
                "issue_date": "2026-03-03",
                "line_items": [],
                "total": 1.0,
            }
        ),
        encoding="utf-8",
    )
    result = load_documents(str(tmp_path))
    nums = [p["document_number"] for p in result["purchase_orders"]]
    assert nums[:2] == ["PO-1", "PO-2"]
    assert nums[2] is None
    assert result["purchase_orders"][2]["path"] == "nonum.json"
    assert any(v["document_number"] is None for v in result["schema_violations"])


def test_malformed_and_violations_sorted_by_path(tmp_path):
    (tmp_path / "z.json").write_text("{", encoding="utf-8")
    (tmp_path / "a.json").write_text("{", encoding="utf-8")
    (tmp_path / "m.json").write_text(
        json.dumps(_po(po_number="PO-1", line_items=None)), encoding="utf-8"
    )
    result = load_documents(str(tmp_path))
    assert [m["path"] for m in result["malformed"]] == ["a.json", "z.json"]
    assert [v["path"] for v in result["schema_violations"]] == ["m.json"]


def test_deterministic_and_documented_keys(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.json").write_text(json.dumps(_po()), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(_inv()), encoding="utf-8")
    r1 = load_documents(str(tmp_path))
    r2 = load_documents(str(tmp_path))
    assert r1 == r2
    for bucket in ("purchase_orders", "invoices"):
        for doc in r1[bucket]:
            for key in (
                "document_number",
                "document_type",
                "path",
                "vendor",
                "vendor_name",
                "vendor_name_normalized",
                "currency",
                "issue_date",
                "line_items",
                "total",
                "total_cents",
                "subtotal",
                "shipping",
                "tax",
                "discount",
                "references_po",
                "raw",
            ):
                assert key in doc
            json.dumps(doc)


def test_one_bad_file_does_not_abort_load(tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(_po()), encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"document_type": "invoice", ', encoding="utf-8")
    (tmp_path / "empty.json").write_text("", encoding="utf-8")
    (tmp_path / "notjson.json").write_text("<html></html>", encoding="utf-8")
    result = load_documents(str(tmp_path))
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    assert {m["path"] for m in result["malformed"]} == {"bad.json", "empty.json", "notjson.json"}

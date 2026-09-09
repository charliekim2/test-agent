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


# ---------------------------------------------------------------------------
# Regression: normalisation errors never abort the load (WO-0004)
# ---------------------------------------------------------------------------


def test_uncoercible_number_does_not_abort_the_whole_load(tmp_path):
    # A JSON integer far outside float range: float() raises OverflowError.
    huge = "1" + "0" * 400
    (tmp_path / "huge.json").write_text(
        '{"document_type": "invoice", "invoice_number": "INV-9",'
        ' "vendor": {"name": "Globex"}, "currency": "USD",'
        ' "issue_date": "2026-05-04", "line_items": [], "total": %s,'
        ' "tax": %s}' % (huge, huge),
        encoding="utf-8",
    )
    (tmp_path / "good.json").write_text(json.dumps(_po()), encoding="utf-8")

    result = load_documents(str(tmp_path))

    # The good document survives - the whole point of per-file isolation.
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    # The pathological one is retained (or at worst recorded), never raised.
    numbers = [i["document_number"] for i in result["invoices"]]
    paths = {m["path"] for m in result["malformed"]}
    assert "INV-9" in numbers or "huge.json" in paths
    json.dumps(result)


def test_helpers_never_raise_on_out_of_range_numbers():
    huge = 10 ** 400
    assert normalize_money(huge) is None
    assert to_cents(huge) is None
    assert to_cents(float("inf")) is None
    assert to_cents(float("nan")) is None


def test_unexpected_normalisation_error_is_isolated(tmp_path, monkeypatch):
    import documents as documents_module

    (tmp_path / "boom.json").write_text(json.dumps(_inv()), encoding="utf-8")
    (tmp_path / "good.json").write_text(json.dumps(_po()), encoding="utf-8")

    original = documents_module._process_document

    def exploding(raw, rel_path, document_type, number_key):
        if rel_path == "boom.json":
            raise RuntimeError("kaboom")
        return original(raw, rel_path, document_type, number_key)

    monkeypatch.setattr(documents_module, "_process_document", exploding)

    result = documents_module.load_documents(str(tmp_path))

    # One exploding document must not lose the others, and must not escape.
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    assert result["invoices"] == []
    assert [m["path"] for m in result["malformed"]] == ["boom.json"]
    assert "kaboom" in result["malformed"][0]["error"]
    json.dumps(result)


# ---------------------------------------------------------------------------
# Regression: punctuation is stripped BEFORE legal suffixes (WO-0004)
# ---------------------------------------------------------------------------


def test_punctuation_stripped_before_legal_suffix_removal():
    base = normalize_vendor_name("Globex")
    # Punctuation that trails the legal form used to block suffix removal.
    assert normalize_vendor_name("Globex (LLC)") == base
    assert normalize_vendor_name("Globex, Inc.") == base
    assert normalize_vendor_name("Globex Corp.,") == base
    assert normalize_vendor_name("Globex [Ltd.]") == base
    assert normalize_vendor_name("Globex L.L.C.") == base
    assert normalize_vendor_name("Globex Corp Ltd") == base
    # And the ampersand form survives punctuation stripping without gluing
    # tokens together.
    assert normalize_vendor_name("Smith&Sons") == normalize_vendor_name("Smith and Sons")
    assert normalize_vendor_name("Smith & Sons, Inc.") == normalize_vendor_name("Smith and Sons")
    # Distinguishing words are still never removed.
    assert normalize_vendor_name("Acme Office Supplies, Inc.") != normalize_vendor_name(
        "Acme Industrial Coatings Inc"
    )
    # A vendor literally named after a legal form is not reduced to nothing.
    assert normalize_vendor_name("LLC") != ""


# ---------------------------------------------------------------------------
# Regression: wrong field types are reported (WO-0004)
# ---------------------------------------------------------------------------


def test_non_string_issue_date_is_reported(tmp_path):
    (tmp_path / "p.json").write_text(json.dumps(_po(issue_date=20260504)), encoding="utf-8")
    (tmp_path / "q.json").write_text(
        json.dumps(_po(po_number="PO-1003", issue_date="not a date")), encoding="utf-8"
    )
    result = load_documents(str(tmp_path))
    assert len(result["purchase_orders"]) == 2
    by_path = {v["path"]: v for v in result["schema_violations"]}
    assert any("issue_date" in p for p in by_path["p.json"]["problems"])
    assert any("issue_date" in p for p in by_path["q.json"]["problems"])


def test_non_numeric_total_shapes_are_reported(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_po(total={"amount": 10})), encoding="utf-8")
    (tmp_path / "b.json").write_text(
        json.dumps(_po(po_number="PO-2", total=[432.0])), encoding="utf-8"
    )
    (tmp_path / "c.json").write_text(
        json.dumps(_po(po_number="PO-3", total=True)), encoding="utf-8"
    )
    result = load_documents(str(tmp_path))
    assert len(result["purchase_orders"]) == 3
    by_path = {v["path"]: v for v in result["schema_violations"]}
    for name in ("a.json", "b.json", "c.json"):
        assert any("total" in p for p in by_path[name]["problems"]), name
    for doc in result["purchase_orders"]:
        assert doc["total"] is None
        assert doc["total_cents"] is None


def test_non_string_line_description_is_reported(tmp_path):
    line = {
        "sku": 12345,
        "description": 42,
        "quantity": 2,
        "unit_price": 3.0,
        "line_total": 6.0,
    }
    (tmp_path / "p.json").write_text(json.dumps(_po(line_items=[line])), encoding="utf-8")
    result = load_documents(str(tmp_path))
    (violation,) = result["schema_violations"]
    assert any("description" in p for p in violation["problems"])
    assert any("sku" in p for p in violation["problems"])
    # Retained and coerced to a usable string form for downstream matching.
    stored = result["purchase_orders"][0]["line_items"][0]
    assert stored["description"] == "42"
    assert stored["sku"] == "12345"


def test_valid_numeric_line_values_are_not_mangled(tmp_path):
    (tmp_path / "p.json").write_text(json.dumps(_po()), encoding="utf-8")
    line = load_documents(str(tmp_path))["purchase_orders"][0]["line_items"][0]
    assert line["quantity"] == 100
    assert line["unit_price"] == 4.00
    assert line["line_total"] == 400.00


# ---------------------------------------------------------------------------
# Regression: document_type is a required field and must be validated (WO-0004)
# ---------------------------------------------------------------------------


def test_missing_document_type_is_reported(tmp_path):
    doc = _po()
    del doc["document_type"]
    (tmp_path / "p.json").write_text(json.dumps(doc), encoding="utf-8")
    result = load_documents(str(tmp_path))
    # Still classified from po_number and still retained ...
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    # ... but the missing required field IS reported.
    (violation,) = result["schema_violations"]
    assert any("document_type" in p for p in violation["problems"])


def test_non_string_document_type_is_reported(tmp_path):
    (tmp_path / "p.json").write_text(json.dumps(_po(document_type=7)), encoding="utf-8")
    (tmp_path / "q.json").write_text(
        json.dumps(_inv(invoice_number="INV-2011", document_type=None)), encoding="utf-8"
    )
    result = load_documents(str(tmp_path))
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    assert [i["document_number"] for i in result["invoices"]] == ["INV-2011"]
    by_path = {v["path"]: v for v in result["schema_violations"]}
    assert any("document_type" in p for p in by_path["p.json"]["problems"])
    assert any("document_type" in p for p in by_path["q.json"]["problems"])


def test_unexpected_document_type_value_is_reported(tmp_path):
    (tmp_path / "p.json").write_text(json.dumps(_po(document_type="PO")), encoding="utf-8")
    result = load_documents(str(tmp_path))
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    (violation,) = result["schema_violations"]
    assert any("document_type" in p for p in violation["problems"])


def test_well_formed_document_has_no_violations(tmp_path):
    (tmp_path / "p.json").write_text(json.dumps(_po()), encoding="utf-8")
    assert load_documents(str(tmp_path))["schema_violations"] == []


def test_one_bad_file_does_not_abort_load(tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(_po()), encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"document_type": "invoice", ', encoding="utf-8")
    (tmp_path / "empty.json").write_text("", encoding="utf-8")
    (tmp_path / "notjson.json").write_text("<html></html>", encoding="utf-8")
    result = load_documents(str(tmp_path))
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    assert {m["path"] for m in result["malformed"]} == {"bad.json", "empty.json", "notjson.json"}


# ---------------------------------------------------------------------------
# Regression: readable dates are NOT schema violations (WO-0007)
#
# The issue_date check is a field TYPE check plus a sanity check that the
# string denotes a real calendar date.  It is NOT enforcement of one house
# date format: a document written with a spelled-out month, a slashed or
# dotted date, or an ISO timestamp is perfectly readable and must load
# clean.  Only strings that denote no date at all are reported.
# ---------------------------------------------------------------------------


READABLE_DATES = [
    "2026-05-04",
    "2026/05/04",
    "2026-5-4",
    "04/05/2026",
    "05/04/2026",
    "04.05.2026",
    "20260504",
    "4-May-2026",
    "4 May 2026",
    "May 4 2026",
    "May 4, 2026",
    "September 1, 2026",
    "Sept 1, 2026",
    "1st September 2026",
    "2026-May-04",
    "JULY 04 2026",
    "2026-05-04T10:00:00",
    "2026-05-04T10:00:00Z",
    "2026-05-04T10:00:00+02:00",
    "2026-05-04 10:00",
    "  2026-05-04  ",
]


@pytest.mark.parametrize("value", READABLE_DATES)
def test_readable_issue_dates_are_not_violations(tmp_path, value):
    (tmp_path / "p.json").write_text(json.dumps(_po(issue_date=value)), encoding="utf-8")
    result = load_documents(str(tmp_path))
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    assert result["schema_violations"] == [], value
    # The value is carried through verbatim; the loader does not rewrite it.
    assert result["purchase_orders"][0]["issue_date"] == value


def test_readable_issue_dates_do_not_crowd_out_real_violations(tmp_path):
    # A readable-but-unusual date next to a genuinely missing field: exactly
    # one problem is reported, and it is not about the date.
    doc = _po(issue_date="May 4, 2026")
    del doc["currency"]
    (tmp_path / "p.json").write_text(json.dumps(doc), encoding="utf-8")
    (violation,) = load_documents(str(tmp_path))["schema_violations"]
    assert not any("issue_date" in p for p in violation["problems"])
    assert any("currency" in p for p in violation["problems"])


NON_DATES = ["not a date", "", "   ", "pending", "TBD", "n/a", "2026", "2026-13-45", "2026-02-30"]


@pytest.mark.parametrize("value", NON_DATES)
def test_non_dates_are_still_reported(tmp_path, value):
    (tmp_path / "p.json").write_text(json.dumps(_po(issue_date=value)), encoding="utf-8")
    result = load_documents(str(tmp_path))
    # Never discarded, whatever the date says.
    assert [p["document_number"] for p in result["purchase_orders"]] == ["PO-1002"]
    (violation,) = result["schema_violations"]
    assert any("issue_date" in p for p in violation["problems"]), value

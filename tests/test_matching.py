"""Visible integration tests for app/python/matching.py (FEAT-001, WO-0003).

Every corpus is built with pytest's ``tmp_path``; the repository's own data
directory is never read, because acceptance judges this module against a
different, held-back document set.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app", "python"))

import matching  # noqa: E402


# ------------------------------------------------------------------ helpers


def line(sku, description, quantity, unit_price):
    return {
        "sku": sku,
        "description": description,
        "quantity": quantity,
        "unit_price": unit_price,
        "line_total": round(quantity * unit_price, 2),
    }


def document(kind, number, vendor, date, total, lines, **extra):
    number_key = "po_number" if kind == "purchase_order" else "invoice_number"
    payload = {
        "document_type": kind,
        number_key: number,
        "vendor": {"name": vendor},
        "currency": "USD",
        "issue_date": date,
        "line_items": list(lines),
        "total": total,
    }
    payload.update(extra)
    return payload


def po(number, vendor, date, total, lines, **extra):
    return document("purchase_order", number, vendor, date, total, lines, **extra)


def inv(number, vendor, date, total, lines, **extra):
    return document("invoice", number, vendor, date, total, lines, **extra)


def write(directory, name, payload):
    directory = str(directory)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def exception_types(result, invoice_number=None, po_number=None):
    out = set()
    for exception in result["exceptions"]:
        if invoice_number is not None and exception["invoice_number"] != invoice_number:
            continue
        if po_number is not None and exception["po_number"] != po_number:
            continue
        out.add(exception["type"])
    return out


def link_for(result, po_number):
    for link in result["links"]:
        if link["po_number"] == po_number:
            return link
    raise AssertionError("no link for %s: %r" % (po_number, result["links"]))


@pytest.fixture()
def flat_corpus(tmp_path):
    """The worked example, laid out FLAT - all *.json in one directory."""
    write(tmp_path, "PO-1002.json", po(
        "PO-1002", "Globex Corp", "2026-05-04", 2592.00,
        [line("WID-A", "Widget A", 200, 10.00), line("BRK-01", "Bracket", 100, 4.00)]))
    write(tmp_path, "INV-2002.json", inv(
        "INV-2002", "Globex Corp", "2026-05-12", 2160.00,
        [line("WID-A", "Widget A", 200, 10.00)]))
    write(tmp_path, "INV-2003.json", inv(
        "INV-2003", "Globex Corp", "2026-05-18", 432.00,
        [line("BRK-01", "Bracket", 100, 4.00)]))
    write(tmp_path, "PO-1005.json", po(
        "PO-1005", "Stark Industrial", "2026-05-07", 20000.00,
        [line("ARC-01", "Arc reactor", 2, 10000.00)]))
    write(tmp_path, "INV-2006.json", inv(
        "INV-2006", "Stark Industrial", "2026-05-16", 28000.00,
        [line("ARC-01", "Arc reactor", 2, 10000.00),
         line(None, "Expedited handling fee", 1, 8000.00)],
        references_po="PO-1005"))
    write(tmp_path, "PO-1006.json", po(
        "PO-1006", "Wayne Ent.", "2026-05-08", 9000.00,
        [line(None, "Security audit, engagement", 1, 9000.00)]))
    with open(os.path.join(str(tmp_path), "broken.json"), "w", encoding="utf-8") as fh:
        fh.write('{"document_type": "purchase_order", "po_number": "PO-1009", '
                 '"vendor": {"name": "Initech LLC", }, "line_items": [')
    with open(os.path.join(str(tmp_path), "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("ignored entirely")
    return tmp_path


# ------------------------------------------------------- degenerate inputs


def test_missing_directory_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        matching.match_documents(str(tmp_path / "does-not-exist"))


def test_file_instead_of_directory_raises_value_error(tmp_path):
    target = tmp_path / "a-file.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        matching.match_documents(str(target))


def test_empty_directory_is_valid(tmp_path):
    result = matching.match_documents(str(tmp_path))
    assert result["documents"]["purchase_orders_loaded"] == 0
    assert result["documents"]["invoices_loaded"] == 0
    assert result["documents"]["malformed"] == []
    assert result["exceptions"] == []
    assert result["links"] == []
    assert result["candidates"] == []
    assert result["unmatched_purchase_orders"] == []
    assert result["unmatched_invoices"] == []
    json.dumps(result)


def test_directory_of_non_json_files(tmp_path):
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "a.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    result = matching.match_documents(str(tmp_path))
    assert result["documents"]["invoices_loaded"] == 0
    assert result["documents"]["purchase_orders_loaded"] == 0
    assert result["exceptions"] == []


# ------------------------------------------------------- the worked example


def test_one_to_many_set_promotion_on_content_alone(flat_corpus):
    result = matching.match_documents(str(flat_corpus))
    link = link_for(result, "PO-1002")
    assert link["invoice_numbers"] == ["INV-2002", "INV-2003"]
    assert link["status"] == "auto_linked"
    assert link["po_total"] == 2592.0
    assert link["invoiced_total"] == 2592.0
    assert link["amount_delta"] == 0.0
    assert link["fulfilment"] == "complete"
    assert link["exception_types"] == []
    assert link["score"] == min(link["scores"].values())
    assert link["score"] >= 0.80
    # exactly ONE entry per PO, never one per pair
    assert [l["po_number"] for l in result["links"]].count("PO-1002") == 1
    assert exception_types(result, po_number="PO-1002") == set()


def test_over_billing_is_reported_not_hidden(flat_corpus):
    result = matching.match_documents(str(flat_corpus))
    over = link_for(result, "PO-1005")
    assert over["invoice_numbers"] == ["INV-2006"]
    assert over["fulfilment"] == "over"
    assert over["amount_delta"] == 8000.0
    types = exception_types(result, invoice_number="INV-2006")
    assert "OVER_BILLING" in types
    assert "EXTRA_LINE_ITEM" in types
    assert "AMOUNT_MISMATCH" not in types
    assert "PARTIAL_FULFILMENT" not in types
    for exception in result["exceptions"]:
        if exception["type"] == "OVER_BILLING":
            assert exception["severity"] == "error"


def test_malformed_file_is_isolated_not_fatal(flat_corpus):
    result = matching.match_documents(str(flat_corpus))
    malformed = result["documents"]["malformed"]
    assert [entry["path"] for entry in malformed] == ["broken.json"]
    assert malformed[0]["error"]
    assert not os.path.isabs(malformed[0]["path"])
    assert result["documents"]["purchase_orders_loaded"] == 3
    assert result["documents"]["invoices_loaded"] == 3
    assert any(e["type"] == "MALFORMED_DOCUMENT" for e in result["exceptions"])
    assert "PO-1009" not in result["unmatched_purchase_orders"]
    assert "PO-1009" not in result["unmatched_invoices"]


def test_unrelated_po_is_not_attached_on_vendor_and_date_alone(flat_corpus):
    result = matching.match_documents(str(flat_corpus))
    assert "PO-1006" in result["unmatched_purchase_orders"]
    assert any(
        e["type"] == "PO_WITHOUT_INVOICE" and e["po_number"] == "PO-1006"
        for e in result["exceptions"]
    )


def test_result_shape_thresholds_and_invariants(flat_corpus):
    result = matching.match_documents(str(flat_corpus))
    assert result["thresholds"] == {
        "auto_link": 0.80, "review": 0.55, "tolerance_pct": 0.005}
    json.dumps(result)

    linked_pos = [link["po_number"] for link in result["links"]]
    linked_invoices = [n for link in result["links"] for n in link["invoice_numbers"]]
    assert len(set(linked_pos)) == len(linked_pos)
    assert len(set(linked_invoices)) == len(linked_invoices)
    assert not set(linked_pos) & set(result["unmatched_purchase_orders"])
    assert not set(linked_invoices) & set(result["unmatched_invoices"])
    assert len(linked_pos) + len(result["unmatched_purchase_orders"]) == \
        result["documents"]["purchase_orders_loaded"]
    assert len(linked_invoices) + len(result["unmatched_invoices"]) == \
        result["documents"]["invoices_loaded"]

    assert linked_pos == sorted(linked_pos)
    assert result["unmatched_purchase_orders"] == sorted(
        result["unmatched_purchase_orders"])
    assert result["unmatched_invoices"] == sorted(result["unmatched_invoices"])
    assert [
        (-c["score"], c["po_number"], c["invoice_number"]) for c in result["candidates"]
    ] == sorted(
        (-c["score"], c["po_number"], c["invoice_number"]) for c in result["candidates"]
    )
    assert [
        (e["po_number"] or "", e["invoice_number"] or "", e["type"])
        for e in result["exceptions"]
    ] == sorted(
        (e["po_number"] or "", e["invoice_number"] or "", e["type"])
        for e in result["exceptions"]
    )

    for link in result["links"]:
        assert 0.0 <= link["score"] <= 1.0
        assert link["invoice_numbers"] == sorted(link["invoice_numbers"])
        assert link["status"] in ("auto_linked", "review")
    for candidate in result["candidates"]:
        assert 0.0 <= candidate["score"] <= 1.0
        assert round(candidate["score"], 4) == candidate["score"]
        for value in candidate["components"].values():
            assert 0.0 <= value <= 1.0
    for exception in result["exceptions"]:
        assert exception["severity"] in ("error", "warning", "info")
        assert set(exception) == {
            "type", "severity", "po_number", "invoice_number", "detail", "fields"}


def test_nested_layout_produces_the_same_links(flat_corpus, tmp_path):
    nested = tmp_path / "nested"
    write(nested / "purchase_orders", "one.json", po(
        "PO-1002", "Globex Corp", "2026-05-04", 2592.00,
        [line("WID-A", "Widget A", 200, 10.00), line("BRK-01", "Bracket", 100, 4.00)]))
    write(nested / "invoices" / "may", "two.json", inv(
        "INV-2002", "Globex Corp", "2026-05-12", 2160.00,
        [line("WID-A", "Widget A", 200, 10.00)]))
    write(nested / "invoices" / "may", "three.json", inv(
        "INV-2003", "Globex Corp", "2026-05-18", 432.00,
        [line("BRK-01", "Bracket", 100, 4.00)]))
    result = matching.match_documents(str(nested))
    assert result["documents"]["purchase_orders_loaded"] == 1
    assert result["documents"]["invoices_loaded"] == 2
    link = link_for(result, "PO-1002")
    assert link["invoice_numbers"] == ["INV-2002", "INV-2003"]
    assert link["fulfilment"] == "complete"


def test_malformed_path_is_relative_with_posix_separators(tmp_path):
    nested = tmp_path / "deep" / "inner"
    os.makedirs(str(nested))
    (nested / "bad.json").write_text('{"po_number": ', encoding="utf-8")
    result = matching.match_documents(str(tmp_path))
    assert result["documents"]["malformed"][0]["path"] == "deep/inner/bad.json"


# ------------------------------------------------------------- references


def test_contradicted_reference_is_excluded_from_candidacy(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-9", "Umbrella Industries", "2026-01-01", 1000.00,
        [line("UMB-1", "Umbrella", 10, 100.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-9", "Stark Industrial", "2026-01-05", 1000.00,
        [line("SPR-1", "Sprocket", 10, 100.00)], references_po="PO-9"))
    result = matching.match_documents(str(tmp_path))
    assert result["links"] == []
    assert result["unmatched_invoices"] == ["INV-9"]
    types = exception_types(result, invoice_number="INV-9")
    assert "REFERENCE_MISMATCH" in types
    assert "VENDOR_MISMATCH" in types
    assert "INVOICE_WITHOUT_PO" in types
    assert "AMBIGUOUS_MATCH" not in types
    excluded = [c for c in result["candidates"] if c["invoice_number"] == "INV-9"]
    assert excluded and all(c["excluded_by"] == "REFERENCE_MISMATCH" for c in excluded)
    assert all(c["score"] == 0.0 for c in excluded)


def test_corroborated_reference_survives_amount_discrepancy(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-5", "Stark Industrial", "2026-05-07", 20000.00,
        [line("ARC-01", "Arc reactor", 2, 10000.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-6", "Stark Industrial", "2026-05-16", 28000.00,
        [line("ARC-01", "Arc reactor", 2, 10000.00),
         line(None, "Expedited handling fee", 1, 8000.00)],
        references_po="PO-5"))
    result = matching.match_documents(str(tmp_path))
    link = link_for(result, "PO-5")
    assert link["status"] == "auto_linked"
    assert link["score"] >= 0.95
    assert "OVER_BILLING" in exception_types(result, invoice_number="INV-6")


def test_unresolved_reference_falls_back_to_content(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-7", "Globex Corp", "2026-06-01", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-7", "Globex Corp", "2026-06-04", 1000.00,
        [line("W", "Widget", 10, 100.00)], references_po="PO-DOES-NOT-EXIST"))
    result = matching.match_documents(str(tmp_path))
    assert link_for(result, "PO-7")["invoice_numbers"] == ["INV-7"]
    assert "REFERENCE_UNRESOLVED" in exception_types(result, invoice_number="INV-7")


def test_absent_reference_is_not_an_exception(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-8", "Globex Corp", "2026-06-01", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-8", "Globex Corp", "2026-06-04", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    result = matching.match_documents(str(tmp_path))
    assert result["exceptions"] == []
    assert link_for(result, "PO-8")["status"] == "auto_linked"


# --------------------------------------------------- vendor / currency drift


@pytest.mark.parametrize("po_vendor,invoice_vendor", [
    ("Globex Corporation", "Globex Corp"),
    ("Smith & Sons", "Smith and Sons"),
])
def test_vendor_drift_still_links_without_vendor_mismatch(
        tmp_path, po_vendor, invoice_vendor):
    write(tmp_path, "po.json", po(
        "PO-1", po_vendor, "2026-01-01", 1000.00, [line("W", "Widget", 10, 100.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-1", invoice_vendor, "2026-01-05", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    result = matching.match_documents(str(tmp_path))
    assert link_for(result, "PO-1")["invoice_numbers"] == ["INV-1"]
    assert "VENDOR_MISMATCH" not in exception_types(result)


def test_currency_mismatch_on_an_otherwise_perfect_match(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-1", "Globex Corp", "2026-01-01", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    payload = inv("INV-1", "Globex Corp", "2026-01-05", 1000.00,
                  [line("W", "Widget", 10, 100.00)])
    payload["currency"] = "EUR"
    write(tmp_path, "inv.json", payload)
    result = matching.match_documents(str(tmp_path))
    assert "CURRENCY_MISMATCH" in exception_types(result, invoice_number="INV-1")


def test_internal_total_mismatch(tmp_path):
    payload = po("PO-1", "Globex Corp", "2026-01-01", 1000.00,
                 [line("W", "Widget", 10, 100.00)])
    payload["subtotal"] = 900.00
    payload["tax"] = 0
    write(tmp_path, "po.json", payload)
    result = matching.match_documents(str(tmp_path))
    assert "INTERNAL_TOTAL_MISMATCH" in exception_types(result, po_number="PO-1")


# ------------------------------------------------------ amount and line rules


def test_under_billing_is_partial_fulfilment_with_missing_line(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-3", "Initech", "2026-02-01", 6200.00,
        [line("LIC", "Licence seats", 10, 500.00),
         line("SUP", "Support plan", 1, 1200.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-4", "Initech", "2026-02-10", 5000.00,
        [line("LIC", "Licence seats", 10, 500.00)]))
    result = matching.match_documents(str(tmp_path))
    link = link_for(result, "PO-3")
    assert link["fulfilment"] == "partial"
    assert link["amount_delta"] == -1200.0
    types = exception_types(result, invoice_number="INV-4")
    assert "PARTIAL_FULFILMENT" in types
    assert "OVER_BILLING" not in types
    assert "AMOUNT_MISMATCH" not in types
    assert "MISSING_LINE_ITEM" in exception_types(result, po_number="PO-3")
    for exception in result["exceptions"]:
        if exception["type"] == "PARTIAL_FULFILMENT":
            assert exception["severity"] == "warning"
            assert exception["fields"]["po_total"] == 6200.0
            assert exception["fields"]["invoiced_total"] == 5000.0
            assert exception["fields"]["delta"] == -1200.0


def test_quantity_and_price_variance_co_emit_under_a_lower_header_total(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-4", "Acme Office Supplies", "2026-03-01", 1130.00,
        [line("DRM-55", "Drum unit", 40, 25.00), line("PEN-1", "Pen", 1, 130.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-5", "Acme Office Supplies", "2026-03-05", 1117.04,
        [line("DRM-55", "Drum unit", 38, 26.00), line("PEN-1", "Pen", 1, 130.00)]))
    result = matching.match_documents(str(tmp_path))
    types = exception_types(result, po_number="PO-4")
    assert "QUANTITY_VARIANCE" in types
    assert "PRICE_VARIANCE" in types
    link = link_for(result, "PO-4")
    assert "QUANTITY_VARIANCE" in link["exception_types"]
    assert "PRICE_VARIANCE" in link["exception_types"]


def test_missing_total_yields_amount_mismatch_not_a_direction(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-6", "Globex Corp", "2026-04-01", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    payload = inv("INV-6", "Globex Corp", "2026-04-05", 1000.00,
                  [line("W", "Widget", 10, 100.00)])
    payload["total"] = None
    write(tmp_path, "inv.json", payload)
    result = matching.match_documents(str(tmp_path))
    types = exception_types(result, invoice_number="INV-6")
    if any(link["po_number"] == "PO-6" for link in result["links"]):
        assert "AMOUNT_MISMATCH" in types
        assert "OVER_BILLING" not in types
        assert "PARTIAL_FULFILMENT" not in types


def test_schema_violation_document_is_counted_and_eligible(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-1", "Globex Corp", "2026-01-01", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    payload = inv("INV-1", "Globex Corp", "2026-01-05", "1,000.00",
                  [line("W", "Widget", 10, 100.00)])
    payload["line_items"][0]["quantity"] = "10"
    write(tmp_path, "inv.json", payload)
    result = matching.match_documents(str(tmp_path))
    assert result["documents"]["invoices_loaded"] == 1
    assert result["documents"]["malformed"] == []
    assert link_for(result, "PO-1")["invoice_numbers"] == ["INV-1"]
    assert "SCHEMA_VIOLATION" in exception_types(result, invoice_number="INV-1")


# ------------------------------------------------- assignment and exhaustion


def test_closed_po_rejects_a_surplus_invoice(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-5", "Globex Corp", "2026-04-01", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    write(tmp_path, "first.json", inv(
        "INV-6", "Globex Corp", "2026-04-05", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    write(tmp_path, "second.json", inv(
        "INV-7", "Globex Corp", "2026-04-06", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    result = matching.match_documents(str(tmp_path))
    link = link_for(result, "PO-5")
    assert len(link["invoice_numbers"]) == 1
    surplus = [n for n in ("INV-6", "INV-7") if n not in link["invoice_numbers"]]
    assert result["unmatched_invoices"] == surplus
    without_po = [
        e for e in result["exceptions"]
        if e["type"] == "INVOICE_WITHOUT_PO" and e["invoice_number"] == surplus[0]
    ]
    assert len(without_po) == 1
    assert without_po[0]["fields"]["closest_po"] == "PO-5"
    assert without_po[0]["fields"]["closest_score"] >= 0.80


def test_an_invoice_takes_at_most_one_po_and_ambiguity_blocks_auto_link(tmp_path):
    for number in ("PO-A", "PO-B"):
        write(tmp_path, number + ".json", po(
            number, "Wayne Enterprises", "2026-05-01", 900.00,
            [line("SEC", "Security audit engagement", 1, 900.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-8", "Wayne Enterprises", "2026-05-10", 900.00,
        [line("SEC", "Security audit engagement", 1, 900.00)]))
    result = matching.match_documents(str(tmp_path))
    linked_invoices = [n for l in result["links"] for n in l["invoice_numbers"]]
    assert linked_invoices == ["INV-8"]
    assert all(link["status"] == "review" for link in result["links"])
    ambiguous = [e for e in result["exceptions"] if e["type"] == "AMBIGUOUS_MATCH"]
    assert len(ambiguous) == 1
    named = {c["po_number"] for c in ambiguous[0]["fields"]["candidates"]}
    assert named == {"PO-A", "PO-B"}


def test_hard_gate_rejects_a_same_vendor_unrelated_invoice(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-1", "Globex Corp", "2026-01-01", 9000.00,
        [line("SEC", "Security audit engagement", 1, 9000.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-1", "Globex Corp", "2026-01-10", 8700.00,
        [line("PAV", "Pavement resurfacing", 1, 8700.00)]))
    result = matching.match_documents(str(tmp_path))
    assert result["links"] == []
    assert result["unmatched_purchase_orders"] == ["PO-1"]
    assert result["unmatched_invoices"] == ["INV-1"]
    assert not [c for c in result["candidates"] if c["excluded_by"] is None]


# ---------------------------------------------------------------- thresholds


def test_threshold_overrides_are_echoed_and_honoured(tmp_path):
    write(tmp_path, "po.json", po(
        "PO-1", "Globex Corp", "2026-01-01", 1000.00,
        [line("W", "Widget", 10, 100.00)]))
    write(tmp_path, "inv.json", inv(
        "INV-1", "Globex Corp", "2026-01-05", 990.00,
        [line("W", "Widget", 10, 99.00)]))
    strict = matching.match_documents(
        str(tmp_path), auto_link_threshold=0.9999, review_threshold=0.2,
        tolerance_pct=0.0001)
    assert strict["thresholds"] == {
        "auto_link": 0.9999, "review": 0.2, "tolerance_pct": 0.0001}
    assert link_for(strict, "PO-1")["status"] == "review"
    assert link_for(strict, "PO-1")["fulfilment"] == "partial"

    loose = matching.match_documents(str(tmp_path), tolerance_pct=0.05)
    assert link_for(loose, "PO-1")["fulfilment"] == "complete"
    assert "PARTIAL_FULFILMENT" not in exception_types(loose, po_number="PO-1")

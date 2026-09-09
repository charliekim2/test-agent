"""Visible unit tests for app/python/scoring.py (FEAT-001, WO-0002).

Every input is a literal dict; this suite never touches the filesystem.
"""

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.getcwd(), "app", "python"))

import rapidfuzz  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402
from rapidfuzz.distance import JaroWinkler  # noqa: E402

import scoring  # noqa: E402

VERSION = rapidfuzz.__version__

ADVERSARIAL_PAIRS = [
    ("", ""),
    ("   ", "x"),
    ("Cafe Ltee", "Café Ltée"),
    ("a", "b"),
    ("x" * 5000, "x"),
    ("same", "same"),
    ("abc", "zzzzzz"),
    ("éèê", ""),
    ("acme", "acme"),
]


def po_doc(**overrides):
    doc = {
        "document_number": "PO-1000",
        "document_type": "purchase_order",
        "vendor": {"name": "Globex Corp"},
        "vendor_name": "Globex Corp",
        "vendor_name_normalized": "globex",
        "currency": "USD",
        "issue_date": "2026-05-04",
        "total": 100.0,
        "total_cents": 10000,
        "line_items": [],
        "references_po": None,
    }
    doc.update(overrides)
    return doc


def inv_doc(**overrides):
    doc = po_doc()
    doc.update(
        {
            "document_number": "INV-2000",
            "document_type": "invoice",
            "issue_date": "2026-05-18",
        }
    )
    doc.update(overrides)
    return doc


PO_1002 = po_doc(
    document_number="PO-1002",
    issue_date="2026-05-04",
    total=2592.0,
    total_cents=259200,
    line_items=[
        {"sku": "WID-A", "description": "Widget A", "quantity": 200,
         "unit_price": 10.0, "line_total": 2000.0},
        {"sku": "BRK-01", "description": "Bracket, steel", "quantity": 100,
         "unit_price": 4.0, "line_total": 400.0},
    ],
)

INV_2003 = inv_doc(
    document_number="INV-2003",
    issue_date="2026-05-18",
    total=432.0,
    total_cents=43200,
    line_items=[
        {"sku": "BRK-01", "description": "Bracket, steel", "quantity": 100,
         "unit_price": 4.0, "line_total": 400.0},
    ],
)

INV_2002 = inv_doc(
    document_number="INV-2002",
    issue_date="2026-05-18",
    total=2160.0,
    total_cents=216000,
    line_items=[
        {"sku": "WID-A", "description": "Widget A", "quantity": 200,
         "unit_price": 10.0, "line_total": 2000.0},
    ],
)

PO_1006 = po_doc(
    document_number="PO-1006",
    vendor={"name": "Wayne Ent."},
    vendor_name="Wayne Ent.",
    vendor_name_normalized="wayne ent",
    issue_date="2026-05-01",
    total=9000.0,
    total_cents=900000,
    line_items=[
        {"description": "Security audit, engagement", "quantity": 1,
         "unit_price": 9000.0, "line_total": 9000.0},
    ],
)

INV_2007 = inv_doc(
    document_number="INV-2007",
    vendor={"name": "Wayne Ent."},
    vendor_name="Wayne Ent.",
    vendor_name_normalized="wayne ent",
    issue_date="2026-05-20",
    total=3240.0,
    total_cents=324000,
    line_items=[
        {"description": "Consulting services, hrs", "quantity": 20,
         "unit_price": 150.0, "line_total": 3000.0},
    ],
)

PO_1001 = po_doc(
    document_number="PO-1001",
    vendor={"name": "Acme Office Supplies"},
    vendor_name="Acme Office Supplies",
    vendor_name_normalized="acme office supplies",
    issue_date="2026-04-02",
    total=669.6,
    total_cents=66960,
    line_items=[
        {"sku": "PAP-A4", "description": "Paper A4, ream", "quantity": 40,
         "unit_price": 12.0, "line_total": 480.0},
        {"sku": "PEN-BL", "description": "Pens, blue, box", "quantity": 20,
         "unit_price": 6.0, "line_total": 120.0},
    ],
)

INV_2009 = inv_doc(
    document_number="INV-2009",
    vendor={"name": "Acme Office Supplies"},
    vendor_name="Acme Office Supplies",
    vendor_name_normalized="acme office supplies",
    issue_date="2026-04-20",
    total=1296.0,
    total_cents=129600,
    line_items=[
        {"sku": "TON-K", "description": "Toner cartridge, black", "quantity": 8,
         "unit_price": 150.0, "line_total": 1200.0},
    ],
)

PO_1005 = po_doc(
    document_number="PO-1005",
    vendor_name_normalized="initech",
    issue_date="2026-04-01",
    total=20000.0,
    total_cents=2000000,
    line_items=[
        {"sku": "ARC-01", "description": "Arc welder", "quantity": 2,
         "unit_price": 10000.0, "line_total": 20000.0},
    ],
)

INV_2006 = inv_doc(
    document_number="INV-2006",
    vendor_name_normalized="initech",
    issue_date="2026-04-10",
    total=28000.0,
    total_cents=2800000,
    line_items=[
        {"sku": "ARC-01", "description": "Arc welder", "quantity": 2,
         "unit_price": 10000.0, "line_total": 20000.0},
        {"description": "Expedited handling fee", "quantity": 1,
         "unit_price": 8000.0, "line_total": 8000.0},
    ],
)


def _docs_from_strings(a, b):
    left = po_doc(vendor={"name": a}, vendor_name=a, vendor_name_normalized=a,
                  issue_date=a, line_items=[{"description": a, "quantity": 1,
                                             "unit_price": 1.0, "line_total": 1.0}])
    right = inv_doc(vendor={"name": b}, vendor_name=b, vendor_name_normalized=b,
                    issue_date=b, line_items=[{"description": b, "quantity": 1,
                                               "unit_price": 1.0, "line_total": 1.0}])
    return left, right


def _all_similarities(a, b):
    """Every similarity value this module can produce for a string pair."""
    left, right = _docs_from_strings(a, b)
    values = {
        "vendor_similarity": scoring.vendor_similarity(left, right),
        "vendor_similarity_str": scoring.vendor_similarity(a, b),
        "amount_similarity": scoring.amount_similarity(left, right, 100),
        "line_containment": scoring.line_containment(left, right, 100),
        "date_similarity": scoring.date_similarity(left, right),
    }
    result = scoring.score_pair(left, right)
    values["score"] = result["score"]
    for name, value in result["components"].items():
        values["component_" + name] = value
    for pair in scoring.match_line_items(left, right)["pairs"]:
        values["line_pair"] = pair["similarity"]
    return values


def test_rapidfuzz_api():
    """Pin the installed rapidfuzz's actual behaviour (rules are execution facts)."""
    assert fuzz.ratio("abc", "abc", processor=None, score_cutoff=None) == 100, (
        "fuzz.* must be 0-100 on rapidfuzz %s" % VERSION
    )
    assert JaroWinkler.normalized_similarity("abc", "abc", processor=None) == 1.0, (
        "distance.normalized_similarity must be 0-1 on rapidfuzz %s" % VERSION
    )

    below = fuzz.ratio("abc", "zzzzzz", processor=None, score_cutoff=90)
    assert below is not None, (
        "a below-cutoff fuzz call must return 0.0, not None; rapidfuzz %s" % VERSION
    )
    assert below == 0.0, (
        "score_cutoff filters to 0.0 (not None) on rapidfuzz %s: %r" % (VERSION, below)
    )
    below_jw = JaroWinkler.normalized_similarity(
        "abc", "zzzzzz", processor=None, score_cutoff=0.95
    )
    assert below_jw is not None and below_jw == 0.0, (
        "below-cutoff JaroWinkler must be 0.0, not None; rapidfuzz %s" % VERSION
    )

    assert not hasattr(scoring, "string_metric"), (
        "rapidfuzz.string_metric is a removed API; rapidfuzz %s" % VERSION
    )

    for a, b in ADVERSARIAL_PAIRS:
        for name, value in _all_similarities(a, b).items():
            assert isinstance(value, float), (
                "%s(%r, %r) must be a float on rapidfuzz %s, got %r"
                % (name, a[:12], b[:12], VERSION, value)
            )
            assert 0.0 <= value <= 1.0, (
                "%s(%r, %r) escaped [0,1] on rapidfuzz %s: %r"
                % (name, a[:12], b[:12], VERSION, value)
            )


def test_no_forbidden_rapidfuzz_usage():
    source = open(os.path.join("app", "python", "scoring.py"), encoding="utf-8").read()
    for banned in ("WRatio", "QRatio", "cdist", "string_metric", "numpy", "pandas"):
        assert banned not in source, "%s is forbidden (rapidfuzz %s)" % (banned, VERSION)
    assert source.count("score_cutoff=None") >= 1
    assert "score_cutoff=0" not in source
    assert ".similarity(" not in source.replace("normalized_similarity(", "")
    assert source.count("/ 100.0") == 1, "exactly one 0-100 conversion site"


# --------------------------------------------------------------- vendor


def test_vendor_tax_id_exact_match_wins():
    left = po_doc(vendor={"name": "Globex Corporation", "tax_id": "US-99-1"},
                  vendor_name_normalized="globex corporation")
    right = inv_doc(vendor={"name": "Something Else Entirely", "tax_id": "US-99-1"},
                    vendor_name_normalized="something else entirely")
    assert scoring.vendor_similarity(left, right) == 1.0


def test_vendor_drift_still_links():
    assert scoring.vendor_similarity("globex corporation", "globex corp") >= 0.95
    assert scoring.vendor_similarity("Smith & Sons", "Smith and Sons") >= 0.95
    assert scoring.vendor_similarity("globex", "globex") == 1.0


def test_vendor_suffix_only_equality_is_capped():
    value = scoring.vendor_similarity("globex corporation", "globex corp")
    assert value <= 0.95


@pytest.mark.parametrize(
    "a,b",
    [
        ("acme office supplies", "acme industrial coatings"),
        ("umbrella industries", "stark industrial"),
        ("wayne ent.", "wayne holdings"),
    ],
)
def test_different_vendors_stay_apart(a, b):
    value = scoring.vendor_similarity(a, b)
    assert 0.0 <= value < 0.85, "%r vs %r scored %r (rapidfuzz %s)" % (a, b, value, VERSION)


def test_vendor_missing_names_do_not_raise():
    assert scoring.vendor_similarity({}, {}) == 0.0
    assert scoring.vendor_similarity(po_doc(vendor={}, vendor_name="",
                                            vendor_name_normalized=""), inv_doc()) == 0.0


# ---------------------------------------------------------- line matching


def test_match_line_items_worked_example():
    assert scoring.match_line_items(PO_1002, INV_2003) == {
        "pairs": [{"po_index": 1, "invoice_index": 0, "similarity": 1.0}],
        "unmatched_po_indexes": [0],
        "unmatched_invoice_indexes": [],
    }


def test_match_line_items_reports_extra_invoice_line():
    result = scoring.match_line_items(PO_1005, INV_2006)
    assert result["pairs"] == [{"po_index": 0, "invoice_index": 0, "similarity": 1.0}]
    assert result["unmatched_po_indexes"] == []
    assert result["unmatched_invoice_indexes"] == [1]


def test_match_line_items_description_fallback_and_uniqueness():
    po = po_doc(line_items=[
        {"description": "Bracket, steel", "quantity": 1, "unit_price": 4.0,
         "line_total": 4.0},
        {"description": "Bracket steel", "quantity": 1, "unit_price": 4.0,
         "line_total": 4.0},
    ])
    inv = inv_doc(line_items=[
        {"description": "Bracket, steel", "quantity": 1, "unit_price": 4.0,
         "line_total": 4.0},
    ])
    result = scoring.match_line_items(po, inv)
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["invoice_index"] == 0
    assert result["pairs"][0]["po_index"] == 0
    assert result["unmatched_invoice_indexes"] == []
    assert result["unmatched_po_indexes"] == [1]


def test_match_line_items_no_match_below_threshold():
    assert scoring.match_line_items(PO_1006, INV_2007)["pairs"] == []
    assert scoring.match_line_items(PO_1006, INV_2007)["unmatched_po_indexes"] == [0]
    assert scoring.match_line_items(PO_1006, INV_2007)["unmatched_invoice_indexes"] == [0]


def test_match_line_items_missing_line_items_key():
    assert scoring.match_line_items({}, {}) == {
        "pairs": [], "unmatched_po_indexes": [], "unmatched_invoice_indexes": []}


def test_match_line_items_is_deterministic():
    first = scoring.match_line_items(PO_1002, INV_2003)
    second = scoring.match_line_items(PO_1002, INV_2003)
    assert first == second


# ------------------------------------------------- amount and containment


def test_worked_example_split_member():
    assert scoring.line_containment(PO_1002, INV_2003, 1296) == 1.0
    assert scoring.amount_similarity(PO_1002, INV_2003, 1296) == pytest.approx(
        0.916667, abs=1e-6)
    assert scoring.vendor_similarity(PO_1002, INV_2003) == 1.0
    assert scoring.date_similarity(PO_1002, INV_2003) == 1.0
    result = scoring.score_pair(PO_1002, INV_2003)
    assert result["components"] == {"vendor": 1.0, "amount": 0.9167,
                                    "line_overlap": 1.0, "date": 1.0}
    assert result["score"] == 0.9792
    assert result["score"] >= 0.55
    assert result["score"] >= 0.80


def test_worked_example_sibling_split_member():
    assert scoring.score_pair(PO_1002, INV_2002)["score"] == 0.9958


def test_amount_similarity_three_positional_args():
    assert scoring.amount_similarity(PO_1002, INV_2003, 1296) == pytest.approx(
        0.916667, abs=1e-6)
    precomputed = scoring.match_line_items(PO_1002, INV_2003)
    assert scoring.amount_similarity(
        PO_1002, INV_2003, 1296, precomputed) == scoring.amount_similarity(
        PO_1002, INV_2003, 1296)


def test_overbilling_penalises_only_the_excess():
    assert scoring.line_containment(PO_1005, INV_2006, 10000) == pytest.approx(
        0.714286, abs=1e-5)
    assert scoring.amount_similarity(PO_1005, INV_2006, 10000) == pytest.approx(
        0.5102, abs=1e-4)
    result = scoring.score_pair(PO_1005, INV_2006)
    assert result["components"]["line_overlap"] == 0.5
    assert result["score"] == 0.7276


def test_unrelated_same_vendor_pair_scores_below_review_floor():
    assert scoring.match_line_items(PO_1006, INV_2007)["pairs"] == []
    assert scoring.line_containment(PO_1006, INV_2007, 4500) == 0.0
    assert scoring.amount_similarity(PO_1006, INV_2007, 4500) == 0.0
    assert scoring.score_pair(PO_1006, INV_2007)["score"] == 0.45
    assert scoring.score_pair(PO_1006, INV_2007)["score"] < 0.55


def test_acme_cross_pair_scores_low():
    result = scoring.score_pair(PO_1001, INV_2009)
    assert result["components"]["line_overlap"] == 0.0
    assert result["components"]["amount"] == 0.0
    assert result["score"] < 0.55


def test_symmetric_formula_is_not_used():
    # A contained partial must not be punished for being smaller than its PO.
    assert scoring.amount_similarity(PO_1002, INV_2003, 1296) > 0.9


def test_amount_degenerate_cases():
    po = po_doc(total=None, total_cents=None, line_items=[])
    inv = inv_doc(total=None, total_cents=None, line_items=[])
    assert scoring.amount_similarity(po, inv, 1) == 0.0
    assert scoring.amount_similarity(po_doc(total_cents=0, total=0.0), inv_doc(
        total_cents=0, total=0.0), 1) == 1.0
    assert scoring.amount_similarity(po_doc(total_cents=0, total=0.0), inv_doc(
        total_cents=5000), 1) == 0.0
    assert scoring.line_containment(po_doc(total_cents=10000),
                                    inv_doc(total_cents=10000), 50) == 1.0
    assert scoring.line_containment(po_doc(total_cents=10000),
                                    inv_doc(total_cents=90000), 50) == 0.0


# --------------------------------------------------------------- date


def test_date_similarity_bands():
    assert scoring.date_similarity(po_doc(issue_date="2026-01-01"),
                                   inv_doc(issue_date="2026-01-01")) == 1.0
    assert scoring.date_similarity(po_doc(issue_date="2026-01-01"),
                                   inv_doc(issue_date="2026-04-01")) == 1.0
    assert scoring.date_similarity(po_doc(issue_date="2026-01-01"),
                                   inv_doc(issue_date="2025-12-31")) == 0.3
    assert scoring.date_similarity(po_doc(issue_date="2026-01-01"),
                                   inv_doc(issue_date="2027-01-01")) == 0.0
    mid = scoring.date_similarity(po_doc(issue_date="2026-01-01"),
                                  inv_doc(issue_date="2026-08-01"))
    assert 0.0 < mid < 1.0


def test_date_similarity_unparseable():
    assert scoring.date_similarity(po_doc(issue_date="not-a-date"), inv_doc()) == 0.0
    assert scoring.date_similarity(po_doc(issue_date=None), inv_doc()) == 0.0
    assert scoring.date_similarity({}, {}) == 0.0


# --------------------------------------------------------- score_pair / gate


def test_score_pair_shape_and_weights():
    result = scoring.score_pair(PO_1002, INV_2003)
    assert set(result) == {"score", "components"}
    assert set(result["components"]) == {"vendor", "amount", "line_overlap", "date"}
    assert scoring.WEIGHTS == {"vendor": 0.35, "amount": 0.25,
                               "line_overlap": 0.30, "date": 0.10}
    assert sum(scoring.WEIGHTS.values()) == pytest.approx(1.0)
    for value in result["components"].values():
        assert 0.0 <= value <= 1.0
    assert 0.0 <= result["score"] <= 1.0
    assert result["score"] == round(result["score"], 4)


def test_score_pair_line_overlap_is_invoice_side_fraction():
    result = scoring.score_pair(PO_1005, INV_2006)
    assert result["components"]["line_overlap"] == 0.5
    assert scoring.score_pair(po_doc(), inv_doc())["components"]["line_overlap"] == 0.0


def test_score_pair_is_pure_and_deterministic():
    po_before = copy.deepcopy(PO_1002)
    inv_before = copy.deepcopy(INV_2003)
    first = scoring.score_pair(PO_1002, INV_2003)
    second = scoring.score_pair(PO_1002, INV_2003)
    third = scoring.score_pair(copy.deepcopy(PO_1002), copy.deepcopy(INV_2003))
    assert first == second == third
    assert PO_1002 == po_before
    assert INV_2003 == inv_before


def test_score_pair_never_raises_on_junk():
    for po, inv in [({}, {}), (po_doc(line_items=None), inv_doc(line_items=None)),
                    (po_doc(total_cents=None), inv_doc(issue_date=None)),
                    ({"line_items": [{}]}, {"line_items": [{}]})]:
        result = scoring.score_pair(po, inv)
        assert 0.0 <= result["score"] <= 1.0


def test_link_gate_line_overlap_clause():
    components = scoring.score_pair(PO_1002, INV_2003)["components"]
    assert scoring.link_gate(PO_1002, INV_2003, components, 1296) is True


def test_link_gate_rejects_unrelated_pair():
    components = scoring.score_pair(PO_1006, INV_2007)["components"]
    assert scoring.link_gate(PO_1006, INV_2007, components, 4500) is False


def test_link_gate_uses_raw_envelope_not_amount_component():
    # Contained partial: amount component is high, but the totals are far apart
    # and no line matches, so the gate must stay shut.
    po = po_doc(total=1000.0, total_cents=100000, line_items=[
        {"sku": "A", "description": "Alpha widget", "quantity": 1,
         "unit_price": 1000.0, "line_total": 1000.0}])
    inv = inv_doc(total=100.0, total_cents=10000, line_items=[
        {"sku": "Z", "description": "Zeta gizmo", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    components = scoring.score_pair(po, inv)["components"]
    assert components["line_overlap"] == 0.0
    assert scoring.link_gate(po, inv, components, 500) is False


def test_link_gate_amount_envelope_clause():
    po = po_doc(total=1000.0, total_cents=100000, line_items=[])
    inv = inv_doc(total=1000.0, total_cents=100000, line_items=[])
    components = {"vendor": 1.0, "amount": 0.0, "line_overlap": 0.0, "date": 1.0}
    assert scoring.link_gate(po, inv, components, 500) is True


def test_link_gate_tax_id_clause():
    po = po_doc(vendor={"name": "Alpha", "tax_id": "T-1"},
                vendor_name_normalized="alpha", total_cents=100000, line_items=[])
    inv = inv_doc(vendor={"name": "Beta", "tax_id": "T-1"},
                  vendor_name_normalized="beta", total_cents=1, line_items=[])
    components = {"vendor": 1.0, "amount": 0.0, "line_overlap": 0.0, "date": 1.0}
    assert scoring.link_gate(po, inv, components, 1) is True


def test_public_surface():
    for name in ("score_pair", "vendor_similarity", "amount_similarity",
                 "line_containment", "date_similarity", "match_line_items",
                 "link_gate"):
        assert callable(getattr(scoring, name))
    assert sorted(scoring.__all__) == sorted([
        "score_pair", "vendor_similarity", "amount_similarity", "line_containment",
        "date_similarity", "match_line_items", "link_gate"])

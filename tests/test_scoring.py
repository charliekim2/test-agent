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


# ------------------------------------------------- WO-0005 regressions
#
# Acme holds TWO purchase orders, so BOTH cross-pairs must score low.

PO_1008 = po_doc(
    document_number="PO-1008",
    vendor={"name": "Acme Office Supplies"},
    vendor_name="Acme Office Supplies",
    vendor_name_normalized="acme office supplies",
    issue_date="2026-05-20",
    total=1296.0,
    total_cents=129600,
    line_items=[
        {"sku": "TNR-BK", "description": "Toner cartridge, black", "quantity": 30,
         "unit_price": 40.0, "line_total": 1200.0},
    ],
)

INV_2001 = inv_doc(
    document_number="INV-2001",
    vendor={"name": "Acme Office Supplies"},
    vendor_name="Acme Office Supplies",
    vendor_name_normalized="acme office supplies",
    issue_date="2026-05-11",
    total=669.6,
    total_cents=66960,
    references_po="PO-1001",
    line_items=[
        {"sku": "PAP-500", "description": "Copy paper, 500ct case", "quantity": 100,
         "unit_price": 5.0, "line_total": 500.0},
        {"sku": "PEN-012", "description": "Ballpoint pens, box of 12", "quantity": 50,
         "unit_price": 2.0, "line_total": 100.0},
    ],
)


def test_acme_second_cross_pair_scores_low():
    """PO-1008 x INV-2001: same vendor, nothing else in common."""
    assert scoring.match_line_items(PO_1008, INV_2001)["pairs"] == []
    assert scoring.line_containment(PO_1008, INV_2001, 648) == 0.0
    result = scoring.score_pair(PO_1008, INV_2001)
    assert result["components"]["vendor"] == 1.0
    assert result["components"]["line_overlap"] == 0.0
    assert result["components"]["amount"] == 0.0
    assert result["score"] < 0.55
    components = result["components"]
    assert scoring.link_gate(PO_1008, INV_2001, components, 648) is False


def test_acme_both_cross_pairs_score_below_their_true_pairs():
    cross_a = scoring.score_pair(PO_1001, INV_2009)["score"]
    cross_b = scoring.score_pair(PO_1008, INV_2001)["score"]
    true_pair = scoring.score_pair(PO_1008, INV_2009)["score"]
    assert cross_a < 0.55
    assert cross_b < 0.55
    assert true_pair >= 0.80
    assert true_pair > max(cross_a, cross_b)


def test_suffix_only_cap_survives_prenormalised_vendor_names():
    """A pre-stripped `vendor_name_normalized` must not bypass the cap."""
    po = po_doc(vendor={"name": "Globex Corporation"},
                vendor_name="Globex Corporation",
                vendor_name_normalized="globex")
    inv = inv_doc(vendor={"name": "Globex Corp"},
                  vendor_name="Globex Corp",
                  vendor_name_normalized="globex")
    value = scoring.vendor_similarity(po, inv)
    assert value == pytest.approx(0.95)
    assert value <= 0.95
    assert scoring.score_pair(po, inv)["components"]["vendor"] <= 0.95
    # Identical raw names remain a perfect vendor match.
    assert scoring.vendor_similarity(PO_1002, INV_2003) == 1.0


def test_none_total_cents_never_reopens_the_amount_gate():
    """An explicit `total_cents: None` means "no total", not "derive from total"."""
    po = {"total_cents": None, "total": 100, "line_items": [],
          "vendor_name": "Globex Corp", "issue_date": "2026-05-04"}
    inv = {"total_cents": 10000, "total": 100, "line_items": [],
           "vendor_name": "Globex Corp", "issue_date": "2026-05-18"}
    assert scoring.amount_similarity(po, inv, 1) == 0.0
    assert scoring.line_containment(po, inv, 1) == 0.0
    components = scoring.score_pair(po, inv)["components"]
    assert components["amount"] == 0.0
    assert scoring.link_gate(po, inv, components, 100000) is False
    # Symmetrically on the invoice side.
    assert scoring.amount_similarity(inv, {"total_cents": None, "total": 100}, 1) == 0.0
    # A missing key may still fall back to `total`.
    assert scoring.amount_similarity(
        {"total": 100.0, "line_items": []}, {"total": 100.0, "line_items": []}, 50
    ) == 1.0


def test_weights_are_not_mutable_global_state():
    baseline = scoring.score_pair(PO_1002, INV_2003)
    with pytest.raises(TypeError):
        scoring.WEIGHTS["vendor"] = 0.99
    with pytest.raises((TypeError, AttributeError)):
        scoring.WEIGHTS.clear()
    assert scoring.score_pair(PO_1002, INV_2003) == baseline
    assert scoring.WEIGHTS == {"vendor": 0.35, "amount": 0.25,
                               "line_overlap": 0.30, "date": 0.10}


def test_sku_equality_is_case_sensitive():
    po = po_doc(line_items=[
        {"sku": "ABC", "description": "Alpha widget, boxed", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    inv = inv_doc(line_items=[
        {"sku": "abc", "description": "Zeta gizmo, crated", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    result = scoring.match_line_items(po, inv)
    assert result["pairs"] == []
    assert result["unmatched_po_indexes"] == [0]
    assert result["unmatched_invoice_indexes"] == [0]
    assert scoring.score_pair(po, inv)["components"]["line_overlap"] == 0.0
    # Identical SKUs still match exactly.
    same = inv_doc(line_items=[
        {"sku": "ABC", "description": "Zeta gizmo, crated", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    assert scoring.match_line_items(po, same)["pairs"] == [
        {"po_index": 0, "invoice_index": 0, "similarity": 1.0}]


@pytest.mark.parametrize("bad", [
    "2026-01-01Tgarbage",
    "2026-01-01 garbage",
    "2026-01-01T",
    "2026-01-01T12:00:00garbage",
    "2026-01-01T99:99:99",
    "2026-13-45",
    "2026-01-01/2026-02-01",
])
def test_malformed_dates_score_zero(bad):
    assert scoring.date_similarity(po_doc(issue_date=bad), inv_doc()) == 0.0
    assert scoring.date_similarity(po_doc(), inv_doc(issue_date=bad)) == 0.0
    assert scoring.score_pair(po_doc(issue_date=bad), inv_doc())["components"][
        "date"] == 0.0


@pytest.mark.parametrize("good", [
    "2026-05-04",
    "2026-05-04T09:30:00",
    "2026-05-04 09:30:00",
    "2026-05-04T09:30:00Z",
    "2026-05-04T09:30:00+00:00",
])
def test_wellformed_timestamps_still_parse(good):
    assert scoring.date_similarity(po_doc(issue_date=good),
                                   inv_doc(issue_date="2026-05-18")) == 1.0


# ------------------------------------------------------------------------
# WO-0008: regressions for the blocking review findings on WO-0005.
# ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "with_suffix_a,with_suffix_b,bare_a,bare_b",
    [
        ("Initech Inc", "Initrode Inc", "Initech", "Initrode"),
        ("Initech Incorporated", "Initrode Inc.", "Initech", "Initrode"),
        (
            "Acme Office Supplies Ltd",
            "Acme Industrial Coatings Ltd",
            "Acme Office Supplies",
            "Acme Industrial Coatings",
        ),
        (
            "Umbrella Industries GmbH",
            "Stark Industrial GmbH",
            "Umbrella Industries",
            "Stark Industrial",
        ),
        ("Wayne Ent. LLC", "Wayne Holdings LLC", "Wayne Ent.", "Wayne Holdings"),
    ],
)
def test_legal_suffix_never_inflates_ordinary_vendor_fuzzy_scoring(
    with_suffix_a, with_suffix_b, bare_a, bare_b
):
    """Fuzzy vendor scoring compares the NORMALISED (suffix-stripped) names.

    A shared legal suffix is not evidence that two vendors are the same, so it
    must contribute nothing: the score of a pair carrying suffixes has to equal
    the score of the same pair without them.
    """
    with_suffix = scoring.vendor_similarity(with_suffix_a, with_suffix_b)
    bare = scoring.vendor_similarity(bare_a, bare_b)
    assert with_suffix == pytest.approx(bare), (
        "%r vs %r scored %r but %r vs %r scored %r (rapidfuzz %s)"
        % (with_suffix_a, with_suffix_b, with_suffix, bare_a, bare_b, bare, VERSION)
    )
    assert 0.0 <= with_suffix < 0.85


def test_suffix_tokens_do_not_inflate_vendor_scoring_on_documents():
    """Same finding, reached through real document dicts rather than strings."""
    po = po_doc(
        vendor={"name": "Initech Incorporated"},
        vendor_name="Initech Incorporated",
        vendor_name_normalized="initech",
    )
    inv = inv_doc(
        vendor={"name": "Initrode Incorporated"},
        vendor_name="Initrode Incorporated",
        vendor_name_normalized="initrode",
    )
    value = scoring.vendor_similarity(po, inv)
    assert value == pytest.approx(scoring.vendor_similarity("Initech", "Initrode"))
    assert value < 0.85
    assert scoring.score_pair(po, inv)["components"]["vendor"] == round(value, 4)


def test_suffix_stripping_still_leaves_true_matches_and_the_cap_intact():
    """The fix must not disturb behaviour the contract pins."""
    assert scoring.vendor_similarity("globex corporation", "globex corp") == pytest.approx(
        0.95
    )
    assert scoring.vendor_similarity("Smith & Sons", "Smith and Sons") >= 0.95
    assert scoring.vendor_similarity("globex", "globex") == 1.0
    assert scoring.vendor_similarity(PO_1002, INV_2003) == 1.0
    assert scoring.vendor_similarity({}, {}) == 0.0


def _sku_pair_docs(po_sku, inv_sku):
    """Two one-line docs whose DESCRIPTIONS are nowhere near similar.

    Any pair produced can therefore only come from the SKU-exact stage.
    """
    po = po_doc(line_items=[
        {"sku": po_sku, "description": "Alpha widget, boxed", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    inv = inv_doc(line_items=[
        {"sku": inv_sku, "description": "Zeta gizmo, crated", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    return po, inv


@pytest.mark.parametrize("po_sku,inv_sku", [
    ("ABC ", "ABC"),
    ("ABC", "ABC "),
    (" ABC", "ABC"),
    ("A BC", "ABC"),
    ("\tABC", "ABC"),
    ("ABC\n", "ABC"),
])
def test_sku_exact_match_does_not_trim_whitespace(po_sku, inv_sku):
    """Whitespace trimming must not forge an exact match between unequal ids."""
    po, inv = _sku_pair_docs(po_sku, inv_sku)
    result = scoring.match_line_items(po, inv)
    assert result["pairs"] == [], "%r matched %r" % (po_sku, inv_sku)
    assert result["unmatched_po_indexes"] == [0]
    assert result["unmatched_invoice_indexes"] == [0]
    assert scoring.score_pair(po, inv)["components"]["line_overlap"] == 0.0


@pytest.mark.parametrize("po_sku,inv_sku", [
    (12345, "12345"),
    ("12345", 12345),
    (12345, 12345.0),
    (12345.0, "12345.0"),
    (True, "True"),
    (True, 1),
    (None, "None"),
    (("A",), "('A',)"),
])
def test_sku_exact_match_does_not_coerce_to_string(po_sku, inv_sku):
    """str() coercion must not forge an exact match between unequal ids."""
    po, inv = _sku_pair_docs(po_sku, inv_sku)
    result = scoring.match_line_items(po, inv)
    assert result["pairs"] == [], "%r matched %r" % (po_sku, inv_sku)
    assert result["unmatched_invoice_indexes"] == [0]
    assert scoring.score_pair(po, inv)["components"]["line_overlap"] == 0.0


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\n", None])
def test_blank_or_absent_sku_is_not_an_identifier(blank):
    """A blank SKU on both sides is not an exact match; it is no identifier."""
    po, inv = _sku_pair_docs(blank, blank)
    result = scoring.match_line_items(po, inv)
    assert result["pairs"] == []
    assert result["unmatched_po_indexes"] == [0]
    assert result["unmatched_invoice_indexes"] == [0]
    # A missing `sku` key behaves the same way.
    po_missing = po_doc(line_items=[
        {"description": "Alpha widget, boxed", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    inv_missing = inv_doc(line_items=[
        {"description": "Zeta gizmo, crated", "quantity": 1,
         "unit_price": 100.0, "line_total": 100.0}])
    assert scoring.match_line_items(po_missing, inv_missing)["pairs"] == []


@pytest.mark.parametrize("sku", ["ABC", "BRK-01", "ABC ", " ", 12345, 12345.0])
def test_identical_sku_values_of_the_same_type_still_match_exactly(sku):
    """The fix must not break the exact matches the contract depends on."""
    po, inv = _sku_pair_docs(sku, sku)
    result = scoring.match_line_items(po, inv)
    if isinstance(sku, str) and not sku.strip():
        assert result["pairs"] == []          # blank: no identifier at all
    else:
        assert result["pairs"] == [
            {"po_index": 0, "invoice_index": 0, "similarity": 1.0}]
        assert scoring.score_pair(po, inv)["components"]["line_overlap"] == 1.0


def test_sku_worked_example_line_matching_is_unchanged():
    assert scoring.match_line_items(PO_1002, INV_2003) == {
        "pairs": [{"po_index": 1, "invoice_index": 0, "similarity": 1.0}],
        "unmatched_po_indexes": [0],
        "unmatched_invoice_indexes": [],
    }
    assert scoring.score_pair(PO_1002, INV_2003)["score"] == 0.9792

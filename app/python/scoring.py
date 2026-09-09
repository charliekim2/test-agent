"""FEAT-001 pair scoring (PURE).

This module scores ONE (purchase order, invoice) pair at a time and decides
nothing.  It is pure: no filesystem, no network, no database, no clock, no
randomness, no module-level mutable state, and it never mutates its arguments.

Every similarity value returned or stored by this module lives in [0.0, 1.0].
``rapidfuzz.fuzz.*`` returns 0-100, so it is converted at exactly one site,
``_pct_to_unit``, and clamped before it leaves the module.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from types import MappingProxyType

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

__all__ = [
    "score_pair",
    "vendor_similarity",
    "amount_similarity",
    "line_containment",
    "date_similarity",
    "match_line_items",
    "link_gate",
]

# The weights are immutable: they are plain float constants, and the public
# ``WEIGHTS`` mapping is a read-only view over a dict nothing else references.
# score_pair() reads the constants, never a mutable container, so no module
# state can change how this module scores.
_WEIGHT_VENDOR = 0.35
_WEIGHT_AMOUNT = 0.25
_WEIGHT_LINE_OVERLAP = 0.30
_WEIGHT_DATE = 0.10

WEIGHTS = MappingProxyType(
    {
        "vendor": _WEIGHT_VENDOR,
        "amount": _WEIGHT_AMOUNT,
        "line_overlap": _WEIGHT_LINE_OVERLAP,
        "date": _WEIGHT_DATE,
    }
)

DESCRIPTION_MATCH_THRESHOLD = 0.85
SUFFIX_ONLY_CAP = 0.95
TOLERANCE_PCT = 0.005

DATE_FULL_DAYS = 90
DATE_ZERO_DAYS = 365
DATE_PREDATES_SCORE = 0.3

_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "llc",
        "lc",
        "llp",
        "lp",
        "ltd",
        "limited",
        "plc",
        "gmbh",
        "ag",
        "sa",
        "sas",
        "sarl",
        "srl",
        "spa",
        "bv",
        "nv",
        "ab",
        "oy",
        "as",
        "pty",
        "pte",
        "kk",
        "kg",
        "mbh",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MONEY_STRIP = re.compile(r"[^0-9eE+\-.]")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_WITH_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")


# ---------------------------------------------------------------- primitives


def _pct_to_unit(value):
    """The ONE conversion site from a rapidfuzz 0-100 score to 0-1."""
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _clamp01(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN
        return 0.0
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def _coerce_doc(doc):
    """Accept a document dict; tolerate a bare string or None without raising."""
    if isinstance(doc, dict):
        return doc
    if isinstance(doc, str):
        return {"vendor_name_normalized": doc, "vendor_name": doc, "vendor": {}}
    return {}


def _normalize_text(value):
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def _strip_legal_suffixes(normalized):
    tokens = normalized.split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _fuzzy_unit(a, b):
    """Token metric combined with a whole-string metric; the LOWER wins."""
    if not a or not b:
        return 0.0
    token = _pct_to_unit(fuzz.token_set_ratio(a, b, processor=None, score_cutoff=None))
    ratio = _pct_to_unit(fuzz.ratio(a, b, processor=None, score_cutoff=None))
    jaro = JaroWinkler.normalized_similarity(a, b, processor=None, score_cutoff=None)
    whole = max(_clamp01(ratio), _clamp01(jaro))
    return _clamp01(min(_clamp01(token), whole))


def _text_similarity(a, b):
    left = _normalize_text(a)
    right = _normalize_text(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return _fuzzy_unit(left, right)


def _to_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if number != number else number
    if isinstance(value, str):
        cleaned = _MONEY_STRIP.sub("", value.replace(",", ""))
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _total_cents(doc):
    """-> int|None.  `total_cents` is AUTHORITATIVE when the key is present.

    A present-but-None (or uncoercible) `total_cents` means "no usable total"
    and must stay None: reconstructing it from `total` would let a document
    documents.py already judged totalless open the amount gate.  `total` is
    consulted only when the `total_cents` key is absent altogether.
    """
    if not isinstance(doc, dict):
        return None
    if "total_cents" in doc:
        value = doc.get("total_cents")
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        number = _to_number(value)
        if number is None:
            return None
        return int(round(number))
    number = _to_number(doc.get("total"))
    if number is None:
        return None
    return int(round(number * 100.0))


def _tolerance_for(po_total_cents):
    if po_total_cents is None:
        return 1
    return max(1, int(round(TOLERANCE_PCT * abs(po_total_cents))))


def _lines(doc):
    items = doc.get("line_items")
    if not isinstance(items, list):
        return []
    return [item if isinstance(item, dict) else {} for item in items]


def _line_total(line):
    number = _to_number(line.get("line_total"))
    if number is not None:
        return number
    quantity = _to_number(line.get("quantity"))
    unit_price = _to_number(line.get("unit_price"))
    if quantity is None or unit_price is None:
        return None
    return quantity * unit_price


def _sku_key(line):
    """-> hashable key | None; an identifier, compared EXACTLY.

    A SKU-exact match is the strongest line signal there is, so it must fire
    only on identifiers that are genuinely equal.  Therefore:

    * NO whitespace trimming - `"ABC "` and `"ABC"` are different
      identifiers, and trimming would forge an exact match between them.
    * NO string coercion - the integer `12345` and the string `"12345"` are
      different identifiers, and `str()` would forge an exact match between
      them.  The key carries the value's type, so `12345`, `12345.0` and
      `"12345"` are three distinct identifiers.
    * Case is significant: `ABC` and `abc` are different identifiers.
    * Absent, blank (empty or whitespace-only) and non-scalar SKUs return
      None, meaning "no identifier": such a line makes no exact-match claim
      and must fall through to description similarity.  `bool` is excluded
      because True/False are not identifiers.
    """
    value = line.get("sku")
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        return ("str", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        if value != value:  # NaN is never equal to itself
            return None
        return ("float", value)
    return None


def _tax_id(doc):
    vendor = doc.get("vendor")
    if not isinstance(vendor, dict):
        return ""
    value = vendor.get("tax_id")
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


def _vendor_names(doc):
    """-> (full, core); the two normalised vendor forms.

    `core` is the NORMALISED-NAME contract form: NFKD, casefolded,
    punctuation-folded, `&` -> `and`, and legal suffixes STRIPPED - exactly
    what documents.normalize_vendor_name produces.  Ordinary fuzzy vendor
    scoring compares `core` and nothing else, so a legal suffix can never
    contribute a shared token: "Initech Inc" vs "Initrode Inc" scores
    precisely as "Initech" vs "Initrode".

    `full` is the same normalisation with the legal suffix RETAINED.  It is
    used ONLY to tell a suffix-only difference apart from a true identity, so
    that the suffix-only cap stays reachable; it never feeds a fuzzy metric.
    """
    raw = ""
    value = doc.get("vendor_name")
    if isinstance(value, str) and value.strip():
        raw = value
    else:
        vendor = doc.get("vendor")
        if isinstance(vendor, dict):
            value = vendor.get("name")
            if isinstance(value, str) and value.strip():
                raw = value

    pre = doc.get("vendor_name_normalized")
    pre_normalized = _normalize_text(pre) if isinstance(pre, str) else ""

    full = _normalize_text(raw) or pre_normalized
    # The pre-normalised field is authoritative for the core form when it is
    # present; re-stripping is harmless and covers a field that was not
    # stripped.  Fall back to the raw name when the field is absent or is
    # nothing but a legal suffix.
    core = _strip_legal_suffixes(pre_normalized) or _strip_legal_suffixes(full)
    return full, core


def _issue_date(doc):
    value = doc.get("issue_date")
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # The WHOLE string must be a valid date or datetime.  Truncating at the
    # first "T"/space would accept `2026-01-01Tgarbage` as a real date.
    if _DATE_ONLY.match(text):
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            return None
    if _DATE_WITH_TIME.match(text):
        candidate = text[:-1] + "+00:00" if text[-1] in ("Z", "z") else text
        try:
            return datetime.datetime.fromisoformat(candidate).date()
        except ValueError:
            return None
    return None


# ------------------------------------------------------------------- public


def vendor_similarity(po, invoice):
    """-> float 0..1 (NOT 0..100)."""
    po_doc = _coerce_doc(po)
    inv_doc = _coerce_doc(invoice)

    po_tax = _tax_id(po_doc)
    inv_tax = _tax_id(inv_doc)
    if po_tax and inv_tax and po_tax == inv_tax:
        return 1.0

    po_full, po_core = _vendor_names(po_doc)
    inv_full, inv_core = _vendor_names(inv_doc)
    if not (po_full or po_core) or not (inv_full or inv_core):
        return 0.0

    if po_full and inv_full and po_full == inv_full:
        # Identical names, suffix included: a perfect vendor match.
        return 1.0
    if po_core and inv_core and po_core == inv_core:
        # Equal only after legal-suffix stripping (the raw forms differ):
        # near, but never a suffix-only auto-link.  Checked BEFORE the fuzzy
        # path so an already-suffix-stripped `vendor_name_normalized` cannot
        # bypass the cap.
        return SUFFIX_ONLY_CAP

    # Ordinary fuzzy scoring compares the NORMALISED (suffix-stripped) names.
    left = po_core or po_full
    right = inv_core or inv_full
    if left == right:
        return 1.0
    return _clamp01(_fuzzy_unit(left, right))


def match_line_items(po, invoice):
    """-> {"pairs": [...], "unmatched_po_indexes": [...],
           "unmatched_invoice_indexes": [...]}"""
    po_lines = _lines(_coerce_doc(po))
    inv_lines = _lines(_coerce_doc(invoice))

    used_po = set()
    used_inv = set()
    pairs = []

    # 1. SKU-exact matches (sku present and equal on both sides).
    for po_index, po_line in enumerate(po_lines):
        po_sku = _sku_key(po_line)
        if po_sku is None:
            continue
        for inv_index, inv_line in enumerate(inv_lines):
            if inv_index in used_inv:
                continue
            if _sku_key(inv_line) != po_sku:
                continue
            used_po.add(po_index)
            used_inv.add(inv_index)
            pairs.append(
                {"po_index": po_index, "invoice_index": inv_index, "similarity": 1.0}
            )
            break

    # 2. Description similarity among the remaining lines, greedy, deterministic.
    candidates = []
    for po_index, po_line in enumerate(po_lines):
        if po_index in used_po:
            continue
        for inv_index, inv_line in enumerate(inv_lines):
            if inv_index in used_inv:
                continue
            similarity = _clamp01(
                _text_similarity(po_line.get("description"), inv_line.get("description"))
            )
            if similarity >= DESCRIPTION_MATCH_THRESHOLD:
                candidates.append((-similarity, po_index, inv_index, similarity))

    for _neg, po_index, inv_index, similarity in sorted(candidates):
        if po_index in used_po or inv_index in used_inv:
            continue
        used_po.add(po_index)
        used_inv.add(inv_index)
        pairs.append(
            {
                "po_index": po_index,
                "invoice_index": inv_index,
                "similarity": _clamp01(similarity),
            }
        )

    pairs.sort(key=lambda pair: (pair["po_index"], pair["invoice_index"]))
    return {
        "pairs": pairs,
        "unmatched_po_indexes": sorted(
            index for index in range(len(po_lines)) if index not in used_po
        ),
        "unmatched_invoice_indexes": sorted(
            index for index in range(len(inv_lines)) if index not in used_inv
        ),
    }


def line_containment(po, invoice, tolerance_cents, line_match=None):
    """-> float 0..1; matched invoice line value over all invoice line value."""
    po_doc = _coerce_doc(po)
    inv_doc = _coerce_doc(invoice)

    po_lines = _lines(po_doc)
    inv_lines = _lines(inv_doc)

    inv_totals = [_line_total(line) for line in inv_lines]
    basis = sum(value for value in inv_totals if value is not None and value > 0)

    if not po_lines or not inv_lines or basis <= 0:
        # No usable line basis: fall back to the raw envelope test on totals.
        return _envelope(po_doc, inv_doc, tolerance_cents)

    if line_match is None:
        line_match = match_line_items(po_doc, inv_doc)
    pairs = line_match.get("pairs") if isinstance(line_match, dict) else None
    if not isinstance(pairs, list):
        pairs = []

    matched = 0.0
    seen = set()
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        index = pair.get("invoice_index")
        if not isinstance(index, int) or index in seen:
            continue
        if 0 <= index < len(inv_totals):
            seen.add(index)
            value = inv_totals[index]
            if value is not None and value > 0:
                matched += value

    return _clamp01(round(matched / basis, 6))


def _envelope(po_doc, inv_doc, tolerance_cents):
    """The raw amount envelope test on totals, in integer cents."""
    po_cents = _total_cents(po_doc)
    inv_cents = _total_cents(inv_doc)
    if po_cents is None or inv_cents is None:
        return 0.0
    try:
        tolerance = int(tolerance_cents)
    except (TypeError, ValueError):
        tolerance = _tolerance_for(po_cents)
    return 1.0 if abs(inv_cents - po_cents) <= tolerance else 0.0


def amount_similarity(po, invoice, tolerance_cents, line_match=None):
    """-> float 0..1; directional, containment-based.

    A contained partial is CONSISTENT with its purchase order and is not
    penalised for being smaller; only the EXCESS over the PO total is penalised.
    """
    po_doc = _coerce_doc(po)
    inv_doc = _coerce_doc(invoice)

    po_cents = _total_cents(po_doc)
    inv_cents = _total_cents(inv_doc)
    if po_cents is None or inv_cents is None:
        return 0.0
    if po_cents == 0:
        return 1.0 if inv_cents == 0 else 0.0

    try:
        tolerance = int(tolerance_cents)
    except (TypeError, ValueError):
        tolerance = _tolerance_for(po_cents)

    containment = _clamp01(line_containment(po_doc, inv_doc, tolerance, line_match))
    excess = max(0, inv_cents - po_cents)

    if excess <= tolerance and inv_cents >= po_cents - tolerance:
        amount = containment
    elif excess <= tolerance:
        amount = containment * (0.90 + 0.10 * (inv_cents / po_cents))
    else:
        amount = containment * (1.0 - min(1.0, excess / inv_cents))

    return _clamp01(round(amount, 6))


def date_similarity(po, invoice):
    """-> float 0..1; 1.0 for 0-90 days after the PO, 0 by 365 days."""
    po_date = _issue_date(_coerce_doc(po))
    inv_date = _issue_date(_coerce_doc(invoice))
    if po_date is None or inv_date is None:
        return 0.0
    delta = (inv_date - po_date).days
    if delta < 0:
        return DATE_PREDATES_SCORE
    if delta <= DATE_FULL_DAYS:
        return 1.0
    if delta >= DATE_ZERO_DAYS:
        return 0.0
    span = float(DATE_ZERO_DAYS - DATE_FULL_DAYS)
    return _clamp01(1.0 - (delta - DATE_FULL_DAYS) / span)


def score_pair(po, invoice):
    """-> {"score": float 0..1, "components": {...}}.  Pure, deterministic."""
    po_doc = _coerce_doc(po)
    inv_doc = _coerce_doc(invoice)

    po_cents = _total_cents(po_doc)
    tolerance = _tolerance_for(po_cents)

    line_match = match_line_items(po_doc, inv_doc)
    inv_line_count = len(_lines(inv_doc))
    if inv_line_count:
        line_overlap = _clamp01(len(line_match["pairs"]) / inv_line_count)
    else:
        line_overlap = 0.0

    vendor = _clamp01(vendor_similarity(po_doc, inv_doc))
    amount = _clamp01(amount_similarity(po_doc, inv_doc, tolerance, line_match))
    date = _clamp01(date_similarity(po_doc, inv_doc))

    score = (
        _WEIGHT_VENDOR * vendor
        + _WEIGHT_AMOUNT * amount
        + _WEIGHT_LINE_OVERLAP * line_overlap
        + _WEIGHT_DATE * date
    )

    return {
        "score": round(_clamp01(score), 4),
        "components": {
            "vendor": round(vendor, 4),
            "amount": round(amount, 4),
            "line_overlap": round(line_overlap, 4),
            "date": round(date, 4),
        },
    }


def link_gate(po, invoice, components, tolerance_cents):
    """-> bool; the hard gate.  True iff the pair may be linked at all."""
    po_doc = _coerce_doc(po)
    inv_doc = _coerce_doc(invoice)

    overlap = 0.0
    if isinstance(components, dict):
        overlap = _clamp01(components.get("line_overlap") or 0.0)
    if overlap > 0.0:
        return True

    # RAW envelope test on the totals - never the `amount` component.
    if _envelope(po_doc, inv_doc, tolerance_cents) == 1.0:
        return True

    po_tax = _tax_id(po_doc)
    inv_tax = _tax_id(inv_doc)
    if po_tax and inv_tax and po_tax == inv_tax:
        return True

    return False

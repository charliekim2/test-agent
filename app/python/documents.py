"""FEAT-001 document loading and normalisation (WO-0001).

This module is the ONLY component of the feature that touches the filesystem.
It walks a data directory recursively for ``*.json`` files, classifies each
document as a purchase order or an invoice from its ``document_type`` field
(falling back to ``po_number`` vs ``invoice_number``), and returns a fully
JSON-serialisable result.

Fault isolation is a functional requirement: every file is read and parsed in
its own try/except; one bad file never aborts the load or loses the other
documents.  Structural validation *records* violations but never discards the
document.

Stdlib only.
"""

import json
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

__all__ = ["load_documents", "normalize_money", "to_cents", "normalize_vendor_name"]

# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

_CLEAN_MONEY_RE = re.compile(r"[^0-9.\-]")

# Strings that produce an empty/meaningless numeric body after cleaning.
_EMPTY_NUMERIC = {".", "-", "-.", "+", "+.", ""}


def _clean_money_string(s):
    """Strip currency symbols, thousands separators and other noise from a
    money string, keeping digits, dots and a leading minus."""
    return _CLEAN_MONEY_RE.sub("", s)


def normalize_money(value):
    """-> float|None.

    Accepts a number, or a string carrying currency symbols, thousands
    separators and surrounding whitespace.  Returns ``None`` when the value is
    absent or genuinely uncoercible.  Never raises into the caller.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        cleaned = _clean_money_string(s)
        if cleaned in _EMPTY_NUMERIC:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def to_cents(value):
    """-> int|None.

    Converts to an integer number of cents via ``Decimal(str(value))`` and
    ``ROUND_HALF_UP`` - never via binary float arithmetic, so ``0.145`` maps to
    ``15`` rather than ``14``.  Accepts the same string forms as
    ``normalize_money``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        d = Decimal(str(value))
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        cleaned = _clean_money_string(s)
        if cleaned in _EMPTY_NUMERIC:
            return None
        try:
            d = Decimal(cleaned)
        except InvalidOperation:
            return None
    else:
        return None
    try:
        cents = (d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return int(cents)


# ---------------------------------------------------------------------------
# Vendor name normalisation
# ---------------------------------------------------------------------------

_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:inc\.?|incorporated|l\.l\.c\.?|llc|ltd\.?|limited|"
    r"corp\.?|corporation|co\.?|company|plc|gmbh|ag|sa|bv|nv|pty)\s*$"
)


def normalize_vendor_name(s):
    """-> str comparison key.

    NFKD-normalises and strips combining marks, casefolds, maps ``&`` to
    ``and``, strips punctuation, collapses internal whitespace, then removes
    trailing LEGAL-FORM suffixes only.  Distinguishing words (industries,
    industrial, enterprises, ent, foods, supplies, group, holdings) are kept.
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    s = s.replace("&", "and")
    # Remove stacked trailing legal-form suffixes (e.g. "Globex Corp Ltd").
    previous = None
    while previous != s:
        previous = s
        s = _LEGAL_SUFFIX_RE.sub("", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------------


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _coerce_number(v):
    """Best-effort numeric coercion (returns None when impossible)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    if isinstance(v, str):
        f = normalize_money(v)
        if f is None:
            return None
        return int(f) if f.is_integer() else f
    return None


def _zero_default(value):
    """Absent/coercible values for subtotal/shipping/tax/discount -> 0."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        f = normalize_money(value)
        return f if f is not None else 0
    return 0


def _classify(raw):
    """Return (document_type, number_key) for a parsed dict, or (None, None).

    Classifies from ``document_type``, falling back to the presence of
    ``po_number`` versus ``invoice_number``.  Never uses the filename or the
    parent directory name.
    """
    if not isinstance(raw, dict):
        return None, None
    dt = raw.get("document_type")
    if isinstance(dt, str):
        normalized = dt.strip().casefold()
        if normalized == "purchase_order":
            return "purchase_order", "po_number"
        if normalized == "invoice":
            return "invoice", "invoice_number"
    if "po_number" in raw:
        return "purchase_order", "po_number"
    if "invoice_number" in raw:
        return "invoice", "invoice_number"
    return None, None


def _process_document(raw, rel_path, document_type, number_key):
    """Normalise one parsed document.  Returns (doc, problems)."""
    problems = []

    # -- document number -----------------------------------------------------
    number = raw.get(number_key)
    if number is None:
        problems.append("missing required field: %s" % number_key)
        document_number = None
    elif isinstance(number, str):
        document_number = number
    else:
        document_number = str(number)
        problems.append("field %r is not a string" % number_key)

    # -- vendor --------------------------------------------------------------
    vendor = raw.get("vendor")
    if not isinstance(vendor, dict):
        problems.append("missing or invalid field: vendor (expected object)")
        vendor = {}
        vendor_name = None
    else:
        vendor_name = vendor.get("name")
        if not isinstance(vendor_name, str) or not vendor_name:
            problems.append("missing required field: vendor.name")
            vendor_name = None

    # -- currency ------------------------------------------------------------
    currency = raw.get("currency")
    if not isinstance(currency, str) or not currency:
        problems.append("missing required field: currency")
        currency = None

    # -- issue date ----------------------------------------------------------
    issue_date = raw.get("issue_date")
    if issue_date is None:
        problems.append("missing required field: issue_date")

    # -- totals --------------------------------------------------------------
    total_raw = raw.get("total")
    if total_raw is None:
        problems.append("missing required field: total")
    if isinstance(total_raw, bool) or isinstance(total_raw, str):
        problems.append("field 'total' is not numeric")
    total = normalize_money(total_raw)
    total_cents = to_cents(total)

    subtotal = _zero_default(raw.get("subtotal"))
    shipping = _zero_default(raw.get("shipping"))
    tax = _zero_default(raw.get("tax"))
    discount = _zero_default(raw.get("discount"))

    # -- line items ----------------------------------------------------------
    line_items_raw = raw.get("line_items")
    if line_items_raw is None:
        problems.append("missing required field: line_items")
        line_items = []
    elif not isinstance(line_items_raw, list):
        problems.append("field 'line_items' is not a list")
        line_items = []
    else:
        line_items = []
        for i, line in enumerate(line_items_raw):
            if not isinstance(line, dict):
                problems.append("line item %d is not an object" % i)
                line_items.append(line)
                continue
            new_line = dict(line)
            for key in ("description", "quantity", "unit_price", "line_total"):
                if key not in line:
                    problems.append("line item %d missing required field: %s" % (i, key))
            for key in ("quantity", "unit_price", "line_total"):
                if key in line and not _is_number(line[key]):
                    problems.append("line item %d field %r is not numeric" % (i, key))
            for key in ("quantity", "unit_price", "line_total"):
                if key in line:
                    coerced = _coerce_number(line[key])
                    if coerced is not None:
                        new_line[key] = coerced
            line_items.append(new_line)

    # -- references (a hint, never ground truth) -----------------------------
    references_po = raw.get("references_po")
    if references_po is not None and not isinstance(references_po, str):
        references_po = str(references_po)

    vendor_name_normalized = normalize_vendor_name(vendor_name) if vendor_name else ""

    doc = {
        "document_number": document_number,
        "document_type": document_type,
        "path": rel_path,
        "vendor": vendor,
        "vendor_name": vendor_name,
        "vendor_name_normalized": vendor_name_normalized,
        "currency": currency,
        "issue_date": issue_date,
        "line_items": line_items,
        "total": total,
        "total_cents": total_cents,
        "subtotal": subtotal,
        "shipping": shipping,
        "tax": tax,
        "discount": discount,
        "references_po": references_po,
        "raw": raw,
    }
    return doc, problems


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_documents(data_dir):
    """-> {"purchase_orders": [doc, ...], "invoices": [doc, ...],
           "malformed": [{"path": str, "error": str}, ...],
           "schema_violations": [{"document_number": str|None, "path": str,
                                  "problems": [str, ...]}, ...]}

    Each doc: {"document_number", "document_type", "path", "vendor",
               "vendor_name", "vendor_name_normalized", "currency",
               "issue_date", "line_items", "total", "total_cents", "subtotal",
               "shipping", "tax", "discount", "references_po", "raw"}
    `path` is relative to data_dir, POSIX separators.
    Raises ValueError if data_dir does not exist or is not a directory; that is
    the ONLY exception it may raise.  Never raises on malformed file content.
    """
    try:
        is_dir = os.path.isdir(data_dir)
    except (TypeError, ValueError):
        is_dir = False
    if not is_dir:
        raise ValueError("%r is not a directory" % (data_dir,))

    purchase_orders = []
    invoices = []
    malformed = []
    schema_violations = []

    for root, _dirs, files in os.walk(data_dir):
        for name in files:
            if not name.endswith(".json"):
                continue
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, data_dir)
            rel_posix = rel_path.replace(os.sep, "/")
            try:
                with open(full_path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as exc:
                malformed.append({"path": rel_posix, "error": str(exc)})
                continue

            document_type, number_key = _classify(raw)
            if document_type is None:
                # Valid JSON but not a usable document: no type and no number
                # (or not a dict at all).  It is not a PO, not an invoice, and
                # is not counted anywhere.
                malformed.append(
                    {
                        "path": rel_posix,
                        "error": "not a usable document: missing document_type "
                        "and both po_number/invoice_number",
                    }
                )
                continue

            doc, problems = _process_document(raw, rel_posix, document_type, number_key)
            if document_type == "purchase_order":
                purchase_orders.append(doc)
            else:
                invoices.append(doc)
            if problems:
                schema_violations.append(
                    {
                        "document_number": doc["document_number"],
                        "path": rel_posix,
                        "problems": problems,
                    }
                )

    purchase_orders.sort(key=lambda d: (d["document_number"] is None, d["document_number"], d["path"]))
    invoices.sort(key=lambda d: (d["document_number"] is None, d["document_number"], d["path"]))
    malformed.sort(key=lambda m: m["path"])
    schema_violations.sort(key=lambda v: v["path"])

    return {
        "purchase_orders": purchase_orders,
        "invoices": invoices,
        "malformed": malformed,
        "schema_violations": schema_violations,
    }

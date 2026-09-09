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

import datetime
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
        # A Python int can be arbitrarily large; float() raises OverflowError
        # for such values.  Coercion failures must never escape this module.
        try:
            return float(value)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        cleaned = _clean_money_string(s)
        if cleaned in _EMPTY_NUMERIC:
            return None
        try:
            return float(cleaned)
        except (ValueError, OverflowError):
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
        try:
            d = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
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
    except (InvalidOperation, ValueError, OverflowError):
        return None
    try:
        return int(cents)
    except (ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Vendor name normalisation
# ---------------------------------------------------------------------------

# Applied AFTER punctuation has been stripped and whitespace collapsed, so the
# alternatives are spelled without punctuation and tolerate the single spaces
# that punctuation removal leaves behind ("l.l.c." -> "l l c").
_LEGAL_SUFFIX_RE = re.compile(
    r"\s*\b(?:inc|incorporated|l\s*l\s*c|llc|ltd|limited|"
    r"corp|corporation|co|company|plc|gmbh|ag|s\s*a|bv|nv|pty)$"
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
    s = s.replace("&", " and ")
    # Punctuation first, THEN whitespace collapse, THEN legal-suffix removal:
    # doing it in any other order makes equivalent legal-form spellings
    # ("Globex (LLC)" vs "Globex Corp") produce different comparison keys.
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    # Remove stacked trailing legal-form suffixes (e.g. "Globex Corp Ltd").
    previous = None
    while previous != s:
        previous = s
        candidate = _LEGAL_SUFFIX_RE.sub("", s)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        # Never reduce a name to nothing (a vendor literally called "LLC").
        if candidate:
            s = candidate
    return s


# ---------------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------------


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y", "%B %d %Y")


def _looks_like_date(s):
    """True when `s` (a str) parses as a calendar date in a common format."""
    text = s.strip()
    if not text:
        return False
    try:
        datetime.date.fromisoformat(text)
        return True
    except ValueError:
        pass
    try:
        datetime.datetime.fromisoformat(text)
        return True
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            datetime.datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return False


def _coerce_number(v):
    """Best-effort numeric coercion (returns None when impossible)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v
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
        f = normalize_money(value)
        return f if f is not None else 0
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

    # -- document type (a required field in its own right) -------------------
    raw_type = raw.get("document_type")
    if "document_type" not in raw or raw_type is None:
        problems.append("missing required field: document_type")
    elif not isinstance(raw_type, str):
        problems.append("field 'document_type' is not a string")
    elif raw_type.strip().casefold() not in ("purchase_order", "invoice"):
        problems.append("field 'document_type' has unexpected value: %r" % (raw_type,))

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
        if vendor_name is None:
            problems.append("missing required field: vendor.name")
        elif not isinstance(vendor_name, str):
            problems.append("field 'vendor.name' is not a string")
            vendor_name = None
        elif not vendor_name.strip():
            problems.append("missing required field: vendor.name")
            vendor_name = None

    # -- currency ------------------------------------------------------------
    currency = raw.get("currency")
    if currency is None:
        problems.append("missing required field: currency")
    elif not isinstance(currency, str):
        problems.append("field 'currency' is not a string")
        currency = None
    elif not currency.strip():
        problems.append("missing required field: currency")
        currency = None

    # -- issue date ----------------------------------------------------------
    issue_date = raw.get("issue_date")
    if issue_date is None:
        problems.append("missing required field: issue_date")
    elif not isinstance(issue_date, str):
        problems.append("field 'issue_date' is not a string")
    elif not _looks_like_date(issue_date):
        problems.append("field 'issue_date' is not a valid date: %r" % (issue_date,))

    # -- totals --------------------------------------------------------------
    total_raw = raw.get("total")
    total = normalize_money(total_raw)
    if total_raw is None:
        problems.append("missing required field: total")
    elif not _is_number(total_raw):
        # bool, str, list, dict, ... - reported whether or not it is coercible.
        problems.append("field 'total' is not numeric")
    elif total is None:
        problems.append("field 'total' is not numeric")
    # Cents come from the RAW value where possible (Decimal on the original
    # string), never from binary float arithmetic.
    total_cents = to_cents(total_raw) if total is not None else None

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
                if key not in line or line[key] is None:
                    problems.append("line item %d missing required field: %s" % (i, key))
            # description and sku are strings; a non-string value is a
            # violation and is coerced to its string form for downstream use.
            for key in ("description", "sku"):
                value = line.get(key)
                if key in line and value is not None and not isinstance(value, str):
                    problems.append("line item %d field %r is not a string" % (i, key))
                    new_line[key] = str(value)
            for key in ("quantity", "unit_price", "line_total"):
                if key not in line or line[key] is None:
                    continue
                value = line[key]
                if _is_number(value):
                    continue
                problems.append("line item %d field %r is not numeric" % (i, key))
                coerced = _coerce_number(value)
                if coerced is not None:
                    new_line[key] = coerced
            line_items.append(new_line)

    # -- references (a hint, never ground truth) -----------------------------
    references_po = raw.get("references_po")
    if references_po is not None and not isinstance(references_po, str):
        problems.append("field 'references_po' is not a string")
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
            except Exception as exc:
                # json.JSONDecodeError, OSError, UnicodeDecodeError, RecursionError...
                malformed.append({"path": rel_posix, "error": str(exc) or exc.__class__.__name__})
                continue

            try:
                document_type, number_key = _classify(raw)
            except Exception as exc:  # pragma: no cover - defensive
                malformed.append({"path": rel_posix, "error": str(exc) or exc.__class__.__name__})
                continue
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

            # Normalisation runs inside the per-file guard too: a coercion
            # failure on ONE document must never abort the load and lose every
            # other document.
            try:
                doc, problems = _process_document(raw, rel_posix, document_type, number_key)
            except Exception as exc:
                malformed.append(
                    {
                        "path": rel_posix,
                        "error": "failed to normalise document: %s"
                        % (str(exc) or exc.__class__.__name__),
                    }
                )
                continue
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

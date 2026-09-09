"""FEAT-001 matching entrypoint (WO-0003).

`match_documents(data_dir)` is the ONLY public entrypoint of the feature.  It
loads every document under an arbitrary directory (recursively, layout-agnostic)
via ``documents.load_documents``, scores every (purchase order, invoice) pair via
``scoring.score_pair``, gates, assigns greedily (an invoice takes at most ONE
purchase order; a purchase order accepts MANY invoices), reconciles each linked
set in integer cents, and derives header- and line-level exceptions.

Stdlib + ``documents`` + ``scoring`` only.  No app shell imports, no hard-coded
document directory, no per-document special cases.
"""

import datetime
import os

import documents
import scoring

__all__ = ["match_documents"]

WEIGHTS = {"vendor": 0.35, "amount": 0.25, "line_overlap": 0.30, "date": 0.10}

CORROBORATED_SCORE_FLOOR = 0.95
VENDOR_MATCH_THRESHOLD = 0.85
AMBIGUITY_GAP = 0.05
REFERENCE_MAX_PREDATE_DAYS = 30

SEVERITY = {
    "MALFORMED_DOCUMENT": "error",
    "SCHEMA_VIOLATION": "warning",
    "DUPLICATE_DOCUMENT": "warning",
    "PO_WITHOUT_INVOICE": "warning",
    "INVOICE_WITHOUT_PO": "warning",
    "AMOUNT_MISMATCH": "error",
    "OVER_BILLING": "error",
    "PARTIAL_FULFILMENT": "warning",
    "QUANTITY_VARIANCE": "warning",
    "PRICE_VARIANCE": "warning",
    "EXTRA_LINE_ITEM": "warning",
    "MISSING_LINE_ITEM": "warning",
    "VENDOR_MISMATCH": "error",
    "CURRENCY_MISMATCH": "error",
    "INTERNAL_TOTAL_MISMATCH": "error",
    "REFERENCE_MISMATCH": "error",
    "REFERENCE_UNRESOLVED": "warning",
    "AMBIGUOUS_MATCH": "warning",
}

# Exception types that describe a link itself (surfaced in link.exception_types).
LINK_LEVEL_TYPES = (
    "OVER_BILLING",
    "PARTIAL_FULFILMENT",
    "AMOUNT_MISMATCH",
    "QUANTITY_VARIANCE",
    "PRICE_VARIANCE",
    "EXTRA_LINE_ITEM",
    "MISSING_LINE_ITEM",
    "VENDOR_MISMATCH",
    "CURRENCY_MISMATCH",
    "AMBIGUOUS_MATCH",
)


# --------------------------------------------------------------- primitives


def _exc(type_, po_number, invoice_number, detail, fields=None):
    return {
        "type": type_,
        "severity": SEVERITY.get(type_, "warning"),
        "po_number": po_number,
        "invoice_number": invoice_number,
        "detail": detail,
        "fields": dict(fields) if fields else {},
    }


def _money(cents):
    """Presentational only: integer cents -> float rounded to 2dp."""
    if cents is None:
        return None
    return round(cents / 100.0, 2)


def _fmt(cents):
    if cents is None:
        return "unknown"
    return "%.2f" % (cents / 100.0)


def _score(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    number = max(0.0, min(1.0, number))
    return round(number, 4)


def _tolerance_cents(po_total_cents, tolerance_pct):
    """tolerance_cents = max(1, round(tolerance_pct * po_total_cents))."""
    if po_total_cents is None:
        return 1
    try:
        pct = float(tolerance_pct)
    except (TypeError, ValueError):
        pct = 0.005
    return max(1, int(round(pct * abs(po_total_cents))))


def _total_cents(doc):
    value = doc.get("total_cents")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return documents.to_cents(doc.get("total"))


def _issue_date(doc):
    value = doc.get("issue_date")
    if not isinstance(value, str):
        return None
    text = value.strip().split("T")[0].split(" ")[0]
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _tax_id(doc):
    vendor = doc.get("vendor")
    if not isinstance(vendor, dict):
        return ""
    value = vendor.get("tax_id")
    if value is None:
        return ""
    return str(value).strip()


def _currency(doc):
    value = doc.get("currency")
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _lines(doc):
    items = doc.get("line_items")
    if not isinstance(items, list):
        return []
    return [item if isinstance(item, dict) else {} for item in items]


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return documents.normalize_money(value)


def _line_total_cents(line):
    cents = documents.to_cents(line.get("line_total"))
    if cents is not None:
        return cents
    quantity = _number(line.get("quantity"))
    unit_price = _number(line.get("unit_price"))
    if quantity is None or unit_price is None:
        return None
    return documents.to_cents(quantity * unit_price)


def _describe(line):
    value = line.get("description")
    if isinstance(value, str) and value.strip():
        return value.strip()
    sku = line.get("sku")
    if sku is not None:
        return str(sku)
    return "line item"


# -------------------------------------------------------------- references


def _vendor_agrees(po, invoice):
    po_tax = _tax_id(po)
    inv_tax = _tax_id(invoice)
    if po_tax and inv_tax and po_tax == inv_tax:
        return True
    return scoring.vendor_similarity(po, invoice) >= VENDOR_MATCH_THRESHOLD


def _currency_agrees(po, invoice):
    po_currency = _currency(po)
    inv_currency = _currency(invoice)
    if not po_currency or not inv_currency:
        return True
    return po_currency == inv_currency


def _reference_corroboration(po, invoice, components):
    """-> (corroborated: bool, reason: str|None).

    Amount is DELIBERATELY not part of this test: over-billing, under-billing
    and partial fulfilment are reported as exceptions, never used as evidence
    that a reference is wrong.
    """
    if not _vendor_agrees(po, invoice):
        return False, "vendor similarity below %.2f" % VENDOR_MATCH_THRESHOLD
    if float(components.get("line_overlap") or 0.0) <= 0.0:
        return False, "no line item overlap"
    if not _currency_agrees(po, invoice):
        return False, "currency disagreement"
    po_date = _issue_date(po)
    inv_date = _issue_date(invoice)
    if po_date is not None and inv_date is not None:
        predates = (po_date - inv_date).days
        if predates > REFERENCE_MAX_PREDATE_DAYS:
            return False, "invoice predates the purchase order by %d days" % predates
    return True, None


# -------------------------------------------------------------- assignment


def _set_total_cents(members):
    total = 0
    for member in members:
        cents = member["invoice_cents"]
        if cents is None:
            return None
        total += cents
    return total


def _po_closed(po_cents, members, tolerance):
    if not members:
        return False
    if po_cents is None:
        return False
    total = _set_total_cents(members)
    if total is None:
        return False
    return abs(total - po_cents) <= tolerance


def _covers_open_line(po, line_match, invoiced_by_line, tolerance_pct):
    """True iff the invoice matches a PO line that is not yet fully invoiced."""
    po_lines = _lines(po)
    for pair in line_match.get("pairs", []):
        index = pair.get("po_index")
        if not isinstance(index, int) or not (0 <= index < len(po_lines)):
            continue
        line_cents = _line_total_cents(po_lines[index])
        if line_cents is None:
            return True
        line_tolerance = _tolerance_cents(line_cents, tolerance_pct)
        if invoiced_by_line.get(index, 0) < line_cents - line_tolerance:
            return True
    return False


def _assign(pair_entries, auto_link_threshold, review_threshold, tolerance_pct):
    """Greedy descending assignment.  Returns (sets, assigned, ambiguous)."""
    eligible = [
        entry
        for entry in pair_entries
        if entry["gated"] and entry["excluded_by"] is None
        and entry["score"] >= review_threshold
    ]
    eligible.sort(key=lambda e: (-e["score"], e["po_number"], e["invoice_number"]))

    by_invoice = {}
    for entry in eligible:
        by_invoice.setdefault(entry["invoice_number"], []).append(entry)

    ambiguous = {}
    for invoice_number, entries in by_invoice.items():
        ranked = sorted(entries, key=lambda e: (-e["score"], e["po_number"]))
        if len(ranked) >= 2 and (ranked[0]["score"] - ranked[1]["score"]) < AMBIGUITY_GAP:
            ambiguous[invoice_number] = [
                {"po_number": ranked[0]["po_number"], "score": ranked[0]["score"]},
                {"po_number": ranked[1]["po_number"], "score": ranked[1]["score"]},
            ]

    sets = {}
    invoiced_lines = {}
    assigned = {}
    for entry in eligible:
        invoice_number = entry["invoice_number"]
        if invoice_number in assigned:
            continue
        po_number = entry["po_number"]
        members = sets.setdefault(po_number, [])
        by_line = invoiced_lines.setdefault(po_number, {})
        if _po_closed(entry["po_cents"], members, entry["tolerance"]):
            # PO EXHAUSTION: the linked set already reconciles.
            if entry["score"] < auto_link_threshold:
                continue
            if not _covers_open_line(
                entry["po"], entry["line_match"], by_line, tolerance_pct
            ):
                continue
        members.append(entry)
        assigned[invoice_number] = po_number
        po_lines = _lines(entry["po"])
        for pair in entry["line_match"].get("pairs", []):
            po_index = pair.get("po_index")
            inv_index = pair.get("invoice_index")
            if not isinstance(po_index, int) or not (0 <= po_index < len(po_lines)):
                continue
            inv_lines = _lines(entry["invoice"])
            if not isinstance(inv_index, int) or not (0 <= inv_index < len(inv_lines)):
                continue
            cents = _line_total_cents(inv_lines[inv_index])
            if cents:
                by_line[po_index] = by_line.get(po_index, 0) + cents

    return sets, assigned, ambiguous


# -------------------------------------------------- line level exceptions


def _line_level_exceptions(po, po_number, members):
    """QUANTITY_VARIANCE / PRICE_VARIANCE / EXTRA_LINE_ITEM / MISSING_LINE_ITEM.

    Independent and additive: these never replace a header-level amount
    exception.  Quantity is aggregated over the whole linked SET so a legitimate
    1:many split is not reported as a shortfall on every member.
    """
    out = []
    po_lines = _lines(po)
    matched = {}
    for member in members:
        invoice = member["invoice"]
        invoice_number = member["invoice_number"]
        inv_lines = _lines(invoice)
        line_match = member["line_match"]
        for pair in line_match.get("pairs", []):
            po_index = pair.get("po_index")
            inv_index = pair.get("invoice_index")
            if not isinstance(po_index, int) or not (0 <= po_index < len(po_lines)):
                continue
            if not isinstance(inv_index, int) or not (0 <= inv_index < len(inv_lines)):
                continue
            matched.setdefault(po_index, []).append((invoice_number, inv_lines[inv_index]))
        for inv_index in line_match.get("unmatched_invoice_indexes", []):
            if not isinstance(inv_index, int) or not (0 <= inv_index < len(inv_lines)):
                continue
            line = inv_lines[inv_index]
            out.append(
                _exc(
                    "EXTRA_LINE_ITEM",
                    po_number,
                    invoice_number,
                    "Invoice line %r has no corresponding purchase order line"
                    % _describe(line),
                    {
                        "invoice_index": inv_index,
                        "description": _describe(line),
                        "line_total": _money(_line_total_cents(line)),
                    },
                )
            )

    for po_index, po_line in enumerate(po_lines):
        entries = matched.get(po_index)
        if not entries:
            out.append(
                _exc(
                    "MISSING_LINE_ITEM",
                    po_number,
                    members[0]["invoice_number"] if len(members) == 1 else None,
                    "Purchase order line %r was never invoiced" % _describe(po_line),
                    {
                        "po_index": po_index,
                        "description": _describe(po_line),
                        "line_total": _money(_line_total_cents(po_line)),
                    },
                )
            )
            continue

        po_quantity = _number(po_line.get("quantity"))
        invoiced_quantity = 0.0
        quantity_known = po_quantity is not None
        for _invoice_number, inv_line in entries:
            value = _number(inv_line.get("quantity"))
            if value is None:
                quantity_known = False
            else:
                invoiced_quantity += value
        holders = sorted({name for name, _line in entries})
        holder = holders[0] if len(holders) == 1 else None
        if quantity_known and abs(invoiced_quantity - po_quantity) > 1e-9:
            out.append(
                _exc(
                    "QUANTITY_VARIANCE",
                    po_number,
                    holder,
                    "Line %r invoiced %g of %g ordered"
                    % (_describe(po_line), invoiced_quantity, po_quantity),
                    {
                        "po_index": po_index,
                        "description": _describe(po_line),
                        "ordered_quantity": po_quantity,
                        "invoiced_quantity": invoiced_quantity,
                        "invoice_numbers": holders,
                    },
                )
            )

        po_price = documents.to_cents(po_line.get("unit_price"))
        for invoice_number, inv_line in entries:
            inv_price = documents.to_cents(inv_line.get("unit_price"))
            if po_price is None or inv_price is None or po_price == inv_price:
                continue
            out.append(
                _exc(
                    "PRICE_VARIANCE",
                    po_number,
                    invoice_number,
                    "Line %r billed at %s against an ordered unit price of %s"
                    % (_describe(po_line), _fmt(inv_price), _fmt(po_price)),
                    {
                        "po_index": po_index,
                        "description": _describe(po_line),
                        "po_unit_price": _money(po_price),
                        "invoice_unit_price": _money(inv_price),
                    },
                )
            )
    return out


def _internal_total_exception(doc):
    """INTERNAL_TOTAL_MISMATCH: total != subtotal + shipping + tax - discount,
    or subtotal != sum(line_total).  All comparison in integer cents."""
    raw = doc.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    if "subtotal" not in raw:
        return None
    subtotal = documents.to_cents(doc.get("subtotal"))
    if subtotal is None:
        return None
    shipping = documents.to_cents(doc.get("shipping")) or 0
    tax = documents.to_cents(doc.get("tax")) or 0
    discount = documents.to_cents(doc.get("discount")) or 0
    total = _total_cents(doc)
    problems = []
    fields = {"subtotal": _money(subtotal), "total": _money(total)}
    if total is not None:
        expected = subtotal + shipping + tax - discount
        if expected != total:
            problems.append(
                "total %s != subtotal + shipping + tax - discount (%s)"
                % (_fmt(total), _fmt(expected))
            )
            fields["expected_total"] = _money(expected)
    line_cents = 0
    usable = False
    for line in _lines(doc):
        cents = _line_total_cents(line)
        if cents is None:
            usable = False
            break
        usable = True
        line_cents += cents
    if usable and line_cents != subtotal:
        problems.append(
            "subtotal %s != sum of line totals (%s)" % (_fmt(subtotal), _fmt(line_cents))
        )
        fields["line_total_sum"] = _money(line_cents)
    if not problems:
        return None
    number = doc.get("document_number")
    is_po = doc.get("document_type") == "purchase_order"
    return _exc(
        "INTERNAL_TOTAL_MISMATCH",
        number if is_po else None,
        None if is_po else number,
        "; ".join(problems),
        fields,
    )


# ------------------------------------------------------------ pair matrix


def _identity(doc):
    number = doc.get("document_number")
    if isinstance(number, str) and number.strip():
        return number
    return "<%s>" % (doc.get("path") or "unknown")


def _collect(docs, exceptions, is_po):
    """-> (ordered unique docs, key list).  Duplicates are reported, once."""
    seen = {}
    unique = []
    for doc in docs:
        key = _identity(doc)
        if key in seen:
            exceptions.append(
                _exc(
                    "DUPLICATE_DOCUMENT",
                    key if is_po else None,
                    None if is_po else key,
                    "Document number %s appears in more than one file (%s, %s)"
                    % (key, seen[key].get("path"), doc.get("path")),
                    {"paths": [seen[key].get("path"), doc.get("path")]},
                )
            )
            continue
        seen[key] = doc
        unique.append(doc)
    return unique


def _build_pairs(po_docs, invoice_docs, tolerance_pct, exceptions):
    entries = []
    po_by_reference = {}
    for po in po_docs:
        key = _identity(po)
        po_by_reference[key.strip().upper()] = key

    for invoice in invoice_docs:
        reference = invoice.get("references_po")
        if isinstance(reference, str) and reference.strip():
            if reference.strip().upper() not in po_by_reference:
                exceptions.append(
                    _exc(
                        "REFERENCE_UNRESOLVED",
                        None,
                        _identity(invoice),
                        "Referenced purchase order %s is not present in the document "
                        "set; matching on content instead" % reference,
                        {"references_po": reference},
                    )
                )

    for po in po_docs:
        po_number = _identity(po)
        po_cents = _total_cents(po)
        tolerance = _tolerance_cents(po_cents, tolerance_pct)
        for invoice in invoice_docs:
            invoice_number = _identity(invoice)
            result = scoring.score_pair(po, invoice)
            raw_components = result.get("components") or {}
            components = {
                name: _score(raw_components.get(name))
                for name in ("vendor", "amount", "line_overlap", "date")
            }
            score = _score(result.get("score"))
            gated = bool(scoring.link_gate(po, invoice, components, tolerance))
            excluded_by = None

            reference = invoice.get("references_po")
            references_this_po = (
                isinstance(reference, str)
                and reference.strip().upper() == po_number.strip().upper()
            )
            if references_this_po:
                corroborated, reason = _reference_corroboration(po, invoice, components)
                if corroborated:
                    score = max(score, CORROBORATED_SCORE_FLOOR)
                    gated = True
                else:
                    excluded_by = "REFERENCE_MISMATCH"
                    score = 0.0
                    exceptions.append(
                        _exc(
                            "REFERENCE_MISMATCH",
                            po_number,
                            invoice_number,
                            "Invoice references %s but the documents contradict it "
                            "(%s)" % (po_number, reason),
                            {"references_po": reference, "reason": reason},
                        )
                    )
                    # The contradiction itself is reportable even though the
                    # pair leaves candidacy: a reviewer wants the reason.
                    if not _vendor_agrees(po, invoice):
                        similarity = _score(scoring.vendor_similarity(po, invoice))
                        exceptions.append(
                            _exc(
                                "VENDOR_MISMATCH",
                                po_number,
                                invoice_number,
                                "Vendor %r does not match %r (similarity %.4f)"
                                % (
                                    invoice.get("vendor_name"),
                                    po.get("vendor_name"),
                                    similarity,
                                ),
                                {
                                    "po_vendor": po.get("vendor_name"),
                                    "invoice_vendor": invoice.get("vendor_name"),
                                    "similarity": similarity,
                                },
                            )
                        )
                    if not _currency_agrees(po, invoice):
                        exceptions.append(
                            _exc(
                                "CURRENCY_MISMATCH",
                                po_number,
                                invoice_number,
                                "Currency %s does not match purchase order "
                                "currency %s" % (_currency(invoice), _currency(po)),
                                {
                                    "po_currency": _currency(po),
                                    "invoice_currency": _currency(invoice),
                                },
                            )
                        )

            entries.append(
                {
                    "po": po,
                    "invoice": invoice,
                    "po_number": po_number,
                    "invoice_number": invoice_number,
                    "po_cents": po_cents,
                    "invoice_cents": _total_cents(invoice),
                    "tolerance": tolerance,
                    "score": _score(score),
                    "components": components,
                    "gated": gated,
                    "excluded_by": excluded_by,
                    "line_match": scoring.match_line_items(po, invoice),
                    "referenced": references_this_po,
                }
            )
    return entries


def _promoted_score(entry, tolerance):
    """Recompute a member score with the amount component read on the SET total.

    The set reconciles, so the member's amount signal is its line containment.
    """
    components = dict(entry["components"])
    components["amount"] = _score(
        scoring.line_containment(
            entry["po"], entry["invoice"], tolerance, entry["line_match"]
        )
    )
    total = sum(WEIGHTS[name] * components[name] for name in WEIGHTS)
    return _score(total), components


# ------------------------------------------------------------------ links


def _build_link(po_number, members, ambiguous, auto_link_threshold, tolerance_pct):
    """-> (link dict, [exception, ...])."""
    members = sorted(members, key=lambda m: m["invoice_number"])
    po = members[0]["po"]
    po_cents = members[0]["po_cents"]
    tolerance = members[0]["tolerance"]
    set_cents = _set_total_cents(members)
    determinate = po_cents is not None and set_cents is not None
    delta = (set_cents - po_cents) if determinate else None

    scores = {member["invoice_number"]: member["score"] for member in members}
    reconciled = determinate and abs(delta) <= tolerance
    promoted = len(members) >= 2 and reconciled
    if promoted:
        for member in members:
            recomputed, _components = _promoted_score(member, tolerance)
            scores[member["invoice_number"]] = max(member["score"], recomputed)

    link_score = min(scores.values())
    status = "auto_linked" if (promoted or link_score >= auto_link_threshold) else "review"

    if not determinate:
        fulfilment = "partial"
    elif reconciled:
        fulfilment = "complete"
    elif delta > tolerance:
        fulfilment = "over"
    else:
        fulfilment = "partial"

    exceptions = []

    # -- header level amount: exactly one of OVER_BILLING / PARTIAL_FULFILMENT.
    single = members[0]["invoice_number"] if len(members) == 1 else None
    fields = {
        "po_total": _money(po_cents),
        "invoiced_total": _money(set_cents),
        "delta": _money(delta),
    }
    if not determinate:
        exceptions.append(
            _exc(
                "AMOUNT_MISMATCH",
                po_number,
                single,
                "Amount direction cannot be established: purchase order total %s, "
                "invoiced total %s" % (_fmt(po_cents), _fmt(set_cents)),
                fields,
            )
        )
    elif delta > tolerance:
        exceptions.append(
            _exc(
                "OVER_BILLING",
                po_number,
                single,
                "Invoiced %s of %s; excess %s"
                % (_fmt(set_cents), _fmt(po_cents), _fmt(delta)),
                fields,
            )
        )
    elif delta < -tolerance:
        exceptions.append(
            _exc(
                "PARTIAL_FULFILMENT",
                po_number,
                single,
                "Invoiced %s of %s; shortfall %s"
                % (_fmt(set_cents), _fmt(po_cents), _fmt(-delta)),
                fields,
            )
        )

    # -- line level, independent and additive.
    exceptions.extend(_line_level_exceptions(po, po_number, members))

    # -- vendor / currency / ambiguity, per member.
    for member in members:
        invoice = member["invoice"]
        invoice_number = member["invoice_number"]
        similarity = _score(scoring.vendor_similarity(po, invoice))
        if similarity < VENDOR_MATCH_THRESHOLD:
            exceptions.append(
                _exc(
                    "VENDOR_MISMATCH",
                    po_number,
                    invoice_number,
                    "Vendor %r does not match %r (similarity %.4f)"
                    % (invoice.get("vendor_name"), po.get("vendor_name"), similarity),
                    {
                        "po_vendor": po.get("vendor_name"),
                        "invoice_vendor": invoice.get("vendor_name"),
                        "similarity": similarity,
                    },
                )
            )
        po_currency = _currency(po)
        inv_currency = _currency(invoice)
        if po_currency and inv_currency and po_currency != inv_currency:
            exceptions.append(
                _exc(
                    "CURRENCY_MISMATCH",
                    po_number,
                    invoice_number,
                    "Currency %s does not match purchase order currency %s"
                    % (inv_currency, po_currency),
                    {"po_currency": po_currency, "invoice_currency": inv_currency},
                )
            )
        if invoice_number in ambiguous:
            exceptions.append(
                _exc(
                    "AMBIGUOUS_MATCH",
                    po_number,
                    invoice_number,
                    "Invoice matches %s and %s within %.2f"
                    % (
                        ambiguous[invoice_number][0]["po_number"],
                        ambiguous[invoice_number][1]["po_number"],
                        AMBIGUITY_GAP,
                    ),
                    {"candidates": ambiguous[invoice_number]},
                )
            )
        elif scores[invoice_number] < auto_link_threshold:
            exceptions.append(
                _exc(
                    "AMBIGUOUS_MATCH",
                    po_number,
                    invoice_number,
                    "Match to %s scored %.4f, below the auto-link threshold; "
                    "needs review" % (po_number, scores[invoice_number]),
                    {
                        "candidates": [
                            {"po_number": po_number, "score": scores[invoice_number]}
                        ]
                    },
                )
            )

    if any(member["invoice_number"] in ambiguous for member in members):
        status = "review"
    if any(
        exception["type"] == "AMBIGUOUS_MATCH" for exception in exceptions
    ) and not promoted:
        status = "review"

    link = {
        "po_number": po_number,
        "invoice_numbers": [member["invoice_number"] for member in members],
        "score": _score(link_score),
        "scores": {number: _score(value) for number, value in scores.items()},
        "status": status,
        "po_total": _money(po_cents),
        "invoiced_total": _money(set_cents),
        "amount_delta": _money(delta),
        "fulfilment": fulfilment,
        "exception_types": sorted(
            {
                exception["type"]
                for exception in exceptions
                if exception["type"] in LINK_LEVEL_TYPES
            }
        ),
    }
    return link, exceptions


# ------------------------------------------------------------- entrypoint


def match_documents(data_dir, *, auto_link_threshold=0.80, review_threshold=0.55,
                    tolerance_pct=0.005):
    """Match invoices to purchase orders in `data_dir`.

    data_dir: str path to a directory containing PO/invoice JSON documents
              (searched recursively; subdirectory layout is NOT assumed).
    Returns a plain dict (JSON-serialisable).  Never raises for malformed or
    missing document content; raises ValueError only if `data_dir` does not
    exist or is not a directory.
    """
    if isinstance(data_dir, (bytes, bytearray)):
        try:
            data_dir = bytes(data_dir).decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("data_dir is not a usable path")
    elif not isinstance(data_dir, str):
        # Tolerate os.PathLike (e.g. pathlib.Path) even though the contract
        # documents a str; anything else is a bad argument.
        try:
            data_dir = os.fspath(data_dir)
        except TypeError:
            raise ValueError("data_dir must be a path to an existing directory")
        if not isinstance(data_dir, str):
            raise ValueError("data_dir must be a path to an existing directory")
    if not isinstance(data_dir, str) or not data_dir:
        raise ValueError("data_dir must be a path to an existing directory")
    if not os.path.isdir(data_dir):
        raise ValueError("%r does not exist or is not a directory" % (data_dir,))

    loaded = documents.load_documents(data_dir)
    exceptions = []

    for entry in loaded.get("malformed", []):
        exceptions.append(
            _exc(
                "MALFORMED_DOCUMENT",
                None,
                None,
                "Could not parse %s: %s" % (entry.get("path"), entry.get("error")),
                {"path": entry.get("path"), "error": entry.get("error")},
            )
        )

    po_docs = _collect(loaded.get("purchase_orders", []), exceptions, True)
    invoice_docs = _collect(loaded.get("invoices", []), exceptions, False)
    by_path = {doc.get("path"): doc for doc in list(po_docs) + list(invoice_docs)}

    for violation in loaded.get("schema_violations", []):
        doc = by_path.get(violation.get("path"))
        is_po = bool(doc) and doc.get("document_type") == "purchase_order"
        number = violation.get("document_number")
        exceptions.append(
            _exc(
                "SCHEMA_VIOLATION",
                number if is_po else None,
                None if is_po else number,
                "%s: %s" % (violation.get("path"), "; ".join(violation.get("problems", []))),
                {
                    "path": violation.get("path"),
                    "problems": list(violation.get("problems", [])),
                },
            )
        )

    for doc in list(po_docs) + list(invoice_docs):
        internal = _internal_total_exception(doc)
        if internal is not None:
            exceptions.append(internal)

    pair_entries = _build_pairs(po_docs, invoice_docs, tolerance_pct, exceptions)
    sets, assigned, ambiguous = _assign(
        pair_entries, auto_link_threshold, review_threshold, tolerance_pct
    )

    links = []
    for po_number in sorted(sets):
        members = sets[po_number]
        if not members:
            continue
        link, link_exceptions = _build_link(
            po_number, members, ambiguous, auto_link_threshold, tolerance_pct
        )
        links.append(link)
        exceptions.extend(link_exceptions)

    linked_po_numbers = {link["po_number"] for link in links}
    unmatched_pos = sorted(
        {_identity(po) for po in po_docs} - linked_po_numbers
    )
    for po_number in unmatched_pos:
        exceptions.append(
            _exc(
                "PO_WITHOUT_INVOICE",
                po_number,
                None,
                "Purchase order %s has no linked invoice" % po_number,
                {},
            )
        )

    best_by_invoice = {}
    for entry in pair_entries:
        if entry["excluded_by"] is not None:
            continue
        current = best_by_invoice.get(entry["invoice_number"])
        if current is None or entry["score"] > current["score"]:
            best_by_invoice[entry["invoice_number"]] = entry

    unmatched_invoices = sorted(
        {_identity(invoice) for invoice in invoice_docs} - set(assigned)
    )
    for invoice_number in unmatched_invoices:
        best = best_by_invoice.get(invoice_number)
        exceptions.append(
            _exc(
                "INVOICE_WITHOUT_PO",
                None,
                invoice_number,
                "Invoice %s could not be linked to any purchase order"
                % invoice_number,
                {
                    "closest_po": best["po_number"] if best else None,
                    "closest_score": best["score"] if best else 0.0,
                },
            )
        )

    candidates = [
        {
            "po_number": entry["po_number"],
            "invoice_number": entry["invoice_number"],
            "score": entry["score"],
            "components": dict(entry["components"]),
            "excluded_by": entry["excluded_by"],
        }
        for entry in pair_entries
        if (entry["gated"] and entry["excluded_by"] is None)
        or entry["excluded_by"] is not None
    ]
    candidates.sort(key=lambda c: (-c["score"], c["po_number"], c["invoice_number"]))

    exceptions.sort(
        key=lambda e: (e["po_number"] or "", e["invoice_number"] or "", e["type"])
    )

    return {
        "links": links,
        "exceptions": exceptions,
        "unmatched_purchase_orders": unmatched_pos,
        "unmatched_invoices": unmatched_invoices,
        "candidates": candidates,
        "documents": {
            "purchase_orders_loaded": len(loaded.get("purchase_orders", [])),
            "invoices_loaded": len(loaded.get("invoices", [])),
            "malformed": [
                {"path": entry.get("path"), "error": entry.get("error")}
                for entry in loaded.get("malformed", [])
            ],
        },
        "thresholds": {
            "auto_link": auto_link_threshold,
            "review": review_threshold,
            "tolerance_pct": tolerance_pct,
        },
    }


"""Single source of truth (SSOT) for the interview scaffold.

⚠️  MAINTAINER ONLY — this module contains the *plaintext answer key* (which
    vendor owns which order, which invoices belong to which order). It must NOT
    be shipped to the candidate. `make bundle` excludes the whole `tooling/`
    directory.

Everything the candidate sees is GENERATED from this module by
`tooling/generate.py`:
  - data/purchase_orders/*.json , data/invoices/*.json   (seed documents)
  - erp/vendors.json                                     (GET /vendors payload)
  - erp/relationships.json                               (salted hashes only)

Design notes:
  - The seed documents carry only a *hint* (`references_po`) which may be wrong
    or absent. The true linkage lives in `belongs_to` here and is never written
    into a document.
  - The ERP validates `POST /bills` by hashing the incoming identifiers with
    `SALT` and checking membership against the hash sets in relationships.json.
    No plaintext mapping is ever shipped. This defeats *casual reading*; it is
    not cryptographically airtight (the salt ships with the hashes and the tuple
    space is tiny). The live interviewer is the real backstop.
"""

from __future__ import annotations

import hashlib

# Not secret-grade. Concealment here is "you can't eyeball the answer key",
# not "you can't brute-force it". See module docstring.
SALT = "finofo-erp-2026-prawn-cascade"


def hash_pair(a: str, b: str) -> str:
    """Canonical hash for a related (a, b) identifier pair.

    The ERP service re-implements this exact formula (it cannot import this
    maintainer-only module). Keep the two in sync: ``sha256(SALT|a|b)``.
    """
    return hashlib.sha256(f"{SALT}|{a}|{b}".encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Vendors                                                                      #
# --------------------------------------------------------------------------- #
# `canonical_name` is what the ERP returns from GET /vendors.
# `doc_name` is the (deliberately slightly different) spelling used on the
# documents — the candidate must resolve doc_name -> vendor_id.
# `address` / `contact` / `tax_id` are stable per vendor so they work as a
# reliable fallback match key when the name is too fuzzy.
VENDORS = [
    {
        "vendor_id": "VEND-001",
        "canonical_name": "ACME Office Supply Co.",
        "doc_name": "Acme Office Supplies",
        "address": {"street": "12 Industrial Way", "city": "Newark", "state": "NJ", "postal_code": "07101", "country": "US"},
        "contact": {"email": "ap@acme-office.com", "phone": "+1-201-555-0112"},
        "tax_id": "12-3456789",
    },
    {
        "vendor_id": "VEND-002",
        "canonical_name": "Globex Corporation",
        "doc_name": "Globex Corp",
        "address": {"street": "500 Globex Plaza", "city": "Springfield", "state": "IL", "postal_code": "62704", "country": "US"},
        "contact": {"email": "billing@globex.com", "phone": "+1-217-555-0190"},
        "tax_id": "98-7654321",
    },
    {
        "vendor_id": "VEND-003",
        "canonical_name": "Initech, LLC",
        "doc_name": "Initech LLC",
        "address": {"street": "404 Cubicle Ln", "city": "Austin", "state": "TX", "postal_code": "73301", "country": "US"},
        "contact": {"email": "accounts@initech.com", "phone": "+1-512-555-0143"},
        "tax_id": "45-6789012",
    },
    {
        "vendor_id": "VEND-004",
        "canonical_name": "Umbrella Ind.",
        "doc_name": "Umbrella Industries",
        "address": {"street": "1 Raccoon Blvd", "city": "Raccoon City", "state": "MI", "postal_code": "48201", "country": "US"},
        "contact": {"email": "payables@umbrella-ind.com", "phone": "+1-313-555-0177"},
        "tax_id": "23-4567890",
    },
    {
        "vendor_id": "VEND-005",
        "canonical_name": "Stark Industries Inc.",
        "doc_name": "Stark Industrial",
        "address": {"street": "200 Park Ave", "city": "New York", "state": "NY", "postal_code": "10166", "country": "US"},
        "contact": {"email": "ap@starkindustries.com", "phone": "+1-212-555-0100"},
        "tax_id": "31-9999999",
    },
    {
        "vendor_id": "VEND-006",
        "canonical_name": "Wayne Enterprises",
        "doc_name": "Wayne Ent.",
        "address": {"street": "1007 Mountain Dr", "city": "Gotham", "state": "NJ", "postal_code": "07003", "country": "US"},
        "contact": {"email": "vendors@wayne-enterprises.com", "phone": "+1-201-555-0007"},
        "tax_id": "11-2233445",
    },
    {
        "vendor_id": "VEND-007",
        "canonical_name": "Soylent Corp",
        "doc_name": "Soylent Foods",
        "address": {"street": "Pier 7", "city": "San Francisco", "state": "CA", "postal_code": "94111", "country": "US"},
        "contact": {"email": "ap@soylentcorp.com", "phone": "+1-415-555-0021"},
        "tax_id": "77-8899001",
    },
    # --------------------------------------------------------------------- #
    # Hidden generalization-test vendors. These are returned by GET /vendors
    # (so a bill against a hidden order can be posted), but their documents are
    # NOT in data/ — see the "hidden" docs below and tooling/README.md.
    # --------------------------------------------------------------------- #
    {
        "vendor_id": "VEND-008",
        "canonical_name": "Wonka Industries, Inc.",
        "doc_name": "Wonka Industries",
        "address": {"street": "1 Cocoa Lane", "city": "Hershey", "state": "PA", "postal_code": "17033", "country": "US"},
        "contact": {"email": "ap@wonka-industries.com", "phone": "+1-717-555-0150"},
        "tax_id": "55-1112223",
        "hidden": True,
    },
    {
        "vendor_id": "VEND-009",
        "canonical_name": "Cyberdyne Systems Corp",
        "doc_name": "Cyberdyne Systems",
        "address": {"street": "18144 El Camino Real", "city": "Sunnyvale", "state": "CA", "postal_code": "94087", "country": "US"},
        "contact": {"email": "billing@cyberdyne.com", "phone": "+1-408-555-0162"},
        "tax_id": "55-3334445",
        "hidden": True,
    },
    {
        "vendor_id": "VEND-010",
        "canonical_name": "Tyrell Corporation",
        "doc_name": "Tyrell Corp",
        "address": {"street": "900 Tyrell Plaza", "city": "Los Angeles", "state": "CA", "postal_code": "90013", "country": "US"},
        "contact": {"email": "ap@tyrell.com", "phone": "+1-213-555-0174"},
        "tax_id": "55-5556667",
        "hidden": True,
    },
    {
        "vendor_id": "VEND-011",
        "canonical_name": "OsCorp Industries",
        "doc_name": "Oscorp",
        "address": {"street": "5th Avenue Tower", "city": "New York", "state": "NY", "postal_code": "10001", "country": "US"},
        "contact": {"email": "payables@oscorp.com", "phone": "+1-212-555-0186"},
        "tax_id": "55-7778889",
        "hidden": True,
    },
    {
        "vendor_id": "VEND-012",
        "canonical_name": "Pied Piper LLC",
        "doc_name": "Pied Piper",
        "address": {"street": "5230 Newell Rd", "city": "Palo Alto", "state": "CA", "postal_code": "94303", "country": "US"},
        "contact": {"email": "ap@piedpiper.com", "phone": "+1-650-555-0198"},
        "tax_id": "55-9990001",
        "hidden": True,
    },
    {
        "vendor_id": "VEND-013",
        "canonical_name": "Hooli Inc.",
        "doc_name": "Hooli",
        "address": {"street": "1401 N Shoreline Blvd", "city": "Mountain View", "state": "CA", "postal_code": "94043", "country": "US"},
        "contact": {"email": "ap@hooli.com", "phone": "+1-650-555-0110"},
        "tax_id": "55-2223334",
        "hidden": True,
    },
]

VENDORS_BY_ID = {v["vendor_id"]: v for v in VENDORS}


# --------------------------------------------------------------------------- #
# Documents                                                                    #
# --------------------------------------------------------------------------- #
# Each entry produces one JSON document. Numbers are authored explicitly (no
# randomness) so the scaffold is reproducible. "Clean" docs reconcile:
#   subtotal == sum(line_total);  total == subtotal + shipping + tax - discount
# Line tuple: (description, quantity, unit_price, line_total[, sku])
#
# Keys:
#   kind          "po" | "invoice"
#   number        PO-#### / INV-####
#   vendor        vendor_id
#   belongs_to    GROUND TRUTH linkage for invoices (None = orphan). Never emitted.
#   references_po HINT written into the invoice JSON (may be absent/wrong).
#   omit_vendor   vendor sub-fields to drop (e.g. ["address"], ["contact"])
#   show_tax_id   include vendor.tax_id on this doc (otherwise omitted — sporadic)
#   extra         sporadic extra top-level fields (allowed, never required)
#   any of subtotal/shipping/tax/discount absent => omitted from JSON
DOCS = [
    # --- Set A: clean 1:1 baseline + slight vendor-name drift -------------- #
    {
        "kind": "po", "number": "PO-1001", "vendor": "VEND-001", "issue_date": "2026-05-03",
        "lines": [("Copy paper, 500ct case", 100, 5.00, 500.00, "PAP-500"),
                  ("Ballpoint pens, box of 12", 50, 2.00, 100.00, "PEN-012")],
        "subtotal": 600.00, "shipping": 20.00, "tax": 49.60, "discount": 0.0, "total": 669.60,
        "show_tax_id": True, "extra": {"department": "Facilities"},
    },
    {
        "kind": "invoice", "number": "INV-2001", "vendor": "VEND-001",
        "belongs_to": "PO-1001", "references_po": "PO-1001", "issue_date": "2026-05-11",
        "lines": [("Copy paper, 500ct case", 100, 5.00, 500.00, "PAP-500"),
                  ("Ballpoint pens, box of 12", 50, 2.00, 100.00, "PEN-012")],
        "subtotal": 600.00, "shipping": 20.00, "tax": 49.60, "discount": 0.0, "total": 669.60,
        # No contact on this invoice -> must resolve V1 by fuzzy name or address.
        "omit_vendor": ["contact"],
    },

    # --- Set B: 1:many, fully fulfilled across two invoices ---------------- #
    {
        "kind": "po", "number": "PO-1002", "vendor": "VEND-002", "issue_date": "2026-05-04",
        "lines": [("Widget, type A", 200, 10.00, 2000.00, "WID-A"),
                  ("Mounting bracket", 100, 4.00, 400.00, "BRK-01")],
        "subtotal": 2400.00, "shipping": 0.0, "tax": 192.00, "discount": 0.0, "total": 2592.00,
        "extra": {"payment_terms": "NET 30"},
    },
    {
        "kind": "invoice", "number": "INV-2002", "vendor": "VEND-002",
        "belongs_to": "PO-1002", "references_po": "PO-1002", "issue_date": "2026-05-12",
        "lines": [("Widget, type A", 200, 10.00, 2000.00, "WID-A")],
        "subtotal": 2000.00, "shipping": 0.0, "tax": 160.00, "discount": 0.0, "total": 2160.00,
        "extra": {"payment_terms": "NET 30"},
    },
    {
        "kind": "invoice", "number": "INV-2003", "vendor": "VEND-002",
        "belongs_to": "PO-1002", "references_po": "PO-1002", "issue_date": "2026-05-18",
        "lines": [("Mounting bracket", 100, 4.00, 400.00, "BRK-01")],
        "subtotal": 400.00, "shipping": 0.0, "tax": 32.00, "discount": 0.0, "total": 432.00,
    },

    # --- Set C: 1:many, PARTIALLY fulfilled (support line never invoiced) -- #
    {
        "kind": "po", "number": "PO-1003", "vendor": "VEND-003", "issue_date": "2026-05-05",
        "lines": [("Software license, annual", 10, 500.00, 5000.00),
                  ("Premium support, annual", 1, 1200.00, 1200.00)],
        "subtotal": 6200.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 6200.00,
    },
    {
        "kind": "invoice", "number": "INV-2004", "vendor": "VEND-003",
        "belongs_to": "PO-1003", "references_po": "PO-1003", "issue_date": "2026-05-14",
        "lines": [("Software license, annual", 10, 500.00, 5000.00)],
        "subtotal": 5000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 5000.00,
    },

    # --- Set D: matched pair with quantity AND unit-price discrepancy ------ #
    {
        "kind": "po", "number": "PO-1004", "vendor": "VEND-004", "issue_date": "2026-05-06",
        "lines": [("Steel drum, 55gal", 40, 25.00, 1000.00, "DRM-55")],
        "subtotal": 1000.00, "shipping": 50.00, "tax": 80.00, "discount": 0.0, "total": 1130.00,
        "show_tax_id": True,
    },
    {
        "kind": "invoice", "number": "INV-2005", "vendor": "VEND-004",
        "belongs_to": "PO-1004", "references_po": "PO-1004", "issue_date": "2026-05-15",
        # qty 38 (not 40) and unit 26.00 (not 25.00): internally consistent, off vs PO.
        "lines": [("Steel drum, 55gal", 38, 26.00, 988.00, "DRM-55")],
        "subtotal": 988.00, "shipping": 50.00, "tax": 79.04, "discount": 0.0, "total": 1117.04,
        "show_tax_id": True,
    },

    # --- Set E: overbilling (+40%) -> human review, not auto-post ---------- #
    {
        "kind": "po", "number": "PO-1005", "vendor": "VEND-005", "issue_date": "2026-05-07",
        "lines": [("Arc reactor core", 2, 10000.00, 20000.00, "ARC-01")],
        "subtotal": 20000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 20000.00,
    },
    {
        "kind": "invoice", "number": "INV-2006", "vendor": "VEND-005",
        "belongs_to": "PO-1005", "references_po": "PO-1005", "issue_date": "2026-05-16",
        "lines": [("Arc reactor core", 2, 10000.00, 20000.00, "ARC-01"),
                  ("Expedited handling fee", 1, 8000.00, 8000.00)],
        "subtotal": 28000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 28000.00,
        "extra": {"notes": "Rush order surcharge applied."},
    },

    # --- Set F: orphan invoice (no PO exists) ------------------------------ #
    {
        "kind": "invoice", "number": "INV-2007", "vendor": "VEND-006",
        "belongs_to": None, "references_po": None, "issue_date": "2026-05-17",
        "lines": [("Consulting services, hrs", 20, 150.00, 3000.00)],
        "subtotal": 3000.00, "shipping": 0.0, "tax": 240.00, "discount": 0.0, "total": 3240.00,
    },

    # --- Set G: orphan PO (never invoiced) --------------------------------- #
    {
        "kind": "po", "number": "PO-1006", "vendor": "VEND-006", "issue_date": "2026-05-08",
        "lines": [("Security audit, engagement", 1, 9000.00, 9000.00)],
        "subtotal": 9000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 9000.00,
    },

    # --- Set H: missing optional fields; resolve vendor via email ---------- #
    {
        "kind": "po", "number": "PO-1007", "vendor": "VEND-007", "issue_date": "2026-05-09",
        "lines": [("Ration pack, individual", 500, 3.00, 1500.00)],
        "subtotal": 1500.00, "total": 1500.00,  # no shipping/tax/discount fields
    },
    {
        "kind": "invoice", "number": "INV-2008", "vendor": "VEND-007",
        "belongs_to": "PO-1007", "references_po": "PO-1007", "issue_date": "2026-05-19",
        "lines": [("Ration pack, individual", 500, 3.00, 1500.00)],
        # subtotal omitted, vendor.address omitted (missing data). contact.email
        # is still present so the vendor remains resolvable.
        "total": 1500.00,
        "omit_vendor": ["address"],
    },

    # --- Set I: same-vendor disambiguation (V1 also owns PO-1001) ---------- #
    {
        "kind": "po", "number": "PO-1008", "vendor": "VEND-001", "issue_date": "2026-05-20",
        "lines": [("Toner cartridge, black", 30, 40.00, 1200.00, "TNR-BK")],
        "subtotal": 1200.00, "shipping": 0.0, "tax": 96.00, "discount": 0.0, "total": 1296.00,
    },
    {
        "kind": "invoice", "number": "INV-2009", "vendor": "VEND-001",
        "belongs_to": "PO-1008", "references_po": "PO-1008", "issue_date": "2026-05-27",
        "lines": [("Toner cartridge, black", 30, 40.00, 1200.00, "TNR-BK")],
        "subtotal": 1200.00, "shipping": 0.0, "tax": 96.00, "discount": 0.0, "total": 1296.00,
    },

    # ======================================================================= #
    # HIDDEN generalization set. Marked "hidden": True so generate.py writes    #
    # these to tooling/hidden_data/ (excluded from the candidate bundle) rather #
    # than data/. The ERP still validates them (they flow through the same      #
    # relationship maps). Deliberately a touch EASIER than the visible set:      #
    # clean vendor-name drift, no malformed/corrupt docs, no same-vendor         #
    # ambiguity. New vendors (VEND-008..013) and number ranges (PO-2xxx /        #
    # INV-3xxx) so a solution overfit to the visible data will not generalize.   #
    # ======================================================================= #

    # --- Hidden A: clean 1:1 ---------------------------------------------- #
    {
        "kind": "po", "number": "PO-2001", "vendor": "VEND-008", "issue_date": "2026-06-01", "hidden": True,
        "lines": [("Everlasting gobstopper, case", 100, 12.00, 1200.00, "GOB-100"),
                  ("Fizzy lifting drink, bottle", 200, 3.00, 600.00, "FIZ-001")],
        "subtotal": 1800.00, "shipping": 0.0, "tax": 144.00, "discount": 0.0, "total": 1944.00,
    },
    {
        "kind": "invoice", "number": "INV-3001", "vendor": "VEND-008",
        "belongs_to": "PO-2001", "references_po": "PO-2001", "issue_date": "2026-06-09", "hidden": True,
        "lines": [("Everlasting gobstopper, case", 100, 12.00, 1200.00, "GOB-100"),
                  ("Fizzy lifting drink, bottle", 200, 3.00, 600.00, "FIZ-001")],
        "subtotal": 1800.00, "shipping": 0.0, "tax": 144.00, "discount": 0.0, "total": 1944.00,
    },

    # --- Hidden B: 1:many, fully fulfilled -------------------------------- #
    {
        "kind": "po", "number": "PO-2002", "vendor": "VEND-009", "issue_date": "2026-06-02", "hidden": True,
        "lines": [("T-800 endoskeleton unit", 5, 4000.00, 20000.00, "T800"),
                  ("Neural net processor", 5, 1000.00, 5000.00, "NNP-1")],
        "subtotal": 25000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 25000.00,
    },
    {
        "kind": "invoice", "number": "INV-3002", "vendor": "VEND-009",
        "belongs_to": "PO-2002", "references_po": "PO-2002", "issue_date": "2026-06-10", "hidden": True,
        "lines": [("T-800 endoskeleton unit", 5, 4000.00, 20000.00, "T800")],
        "subtotal": 20000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 20000.00,
    },
    {
        "kind": "invoice", "number": "INV-3003", "vendor": "VEND-009",
        "belongs_to": "PO-2002", "references_po": "PO-2002", "issue_date": "2026-06-15", "hidden": True,
        "lines": [("Neural net processor", 5, 1000.00, 5000.00, "NNP-1")],
        "subtotal": 5000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 5000.00,
    },

    # --- Hidden C: partially fulfilled (maintenance line never invoiced) -- #
    {
        "kind": "po", "number": "PO-2003", "vendor": "VEND-010", "issue_date": "2026-06-03", "hidden": True,
        "lines": [("Nexus-6 replicant", 4, 50000.00, 200000.00, "NX6"),
                  ("Off-world maintenance, yr", 1, 25000.00, 25000.00, "OWM-1")],
        "subtotal": 225000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 225000.00,
    },
    {
        "kind": "invoice", "number": "INV-3004", "vendor": "VEND-010",
        "belongs_to": "PO-2003", "references_po": "PO-2003", "issue_date": "2026-06-12", "hidden": True,
        "lines": [("Nexus-6 replicant", 4, 50000.00, 200000.00, "NX6")],
        "subtotal": 200000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 200000.00,
    },

    # --- Hidden D: quantity + unit-price discrepancy ---------------------- #
    {
        "kind": "po", "number": "PO-2004", "vendor": "VEND-011", "issue_date": "2026-06-04", "hidden": True,
        "lines": [("Glider, prototype", 3, 2000.00, 6000.00, "GLD-P")],
        "subtotal": 6000.00, "shipping": 100.00, "tax": 480.00, "discount": 0.0, "total": 6580.00,
        "show_tax_id": True,
    },
    {
        "kind": "invoice", "number": "INV-3005", "vendor": "VEND-011",
        "belongs_to": "PO-2004", "references_po": "PO-2004", "issue_date": "2026-06-14", "hidden": True,
        "lines": [("Glider, prototype", 2, 2100.00, 4200.00, "GLD-P")],
        "subtotal": 4200.00, "shipping": 100.00, "tax": 336.00, "discount": 0.0, "total": 4636.00,
        "show_tax_id": True,
    },

    # --- Hidden E: orphan PO (never invoiced) ----------------------------- #
    {
        "kind": "po", "number": "PO-2005", "vendor": "VEND-012", "issue_date": "2026-06-05", "hidden": True,
        "lines": [("Middle-out compression license, yr", 1, 30000.00, 30000.00, "MOC-1")],
        "subtotal": 30000.00, "shipping": 0.0, "tax": 0.0, "discount": 0.0, "total": 30000.00,
    },

    # --- Hidden F: orphan invoice (no PO) --------------------------------- #
    {
        "kind": "invoice", "number": "INV-3006", "vendor": "VEND-013",
        "belongs_to": None, "references_po": None, "issue_date": "2026-06-16", "hidden": True,
        "lines": [("Cloud hosting, monthly", 12, 800.00, 9600.00, "CLD-M")],
        "subtotal": 9600.00, "shipping": 0.0, "tax": 768.00, "discount": 0.0, "total": 10368.00,
    },
]


# --------------------------------------------------------------------------- #
# Malformed documents (emitted as-is; the "+ malformed docs" calibration)      #
# --------------------------------------------------------------------------- #
# Schema-invalid: quantity and total are strings (wrong types). Valid JSON, so
# it parses — the candidate's *validation* should reject it. Not in any
# relationship set (its references_po hint is intentionally misleading).
MALFORMED_INVOICE = {
    "document_type": "invoice",
    "invoice_number": "INV-2010",
    "references_po": "PO-1002",
    "vendor": {"name": "Globex Corp", "contact": {"email": "billing@globex.com"}},
    "currency": "USD",
    "issue_date": "2026-05-21",
    "line_items": [
        {"description": "Consulting services, hrs", "quantity": "20", "unit_price": 150.00, "line_total": 3000.00}
    ],
    "subtotal": 3000.00,
    "tax": 240.00,
    "total": "3,240.00",
}

# Corrupt upload: not valid JSON at all (truncated, trailing comma). Written as
# raw text. The seed loader surfaces this as a load error rather than crashing;
# handling it is the candidate's job.
CORRUPT_PO_NUMBER = "PO-1009"
CORRUPT_PO_TEXT = (
    "{\n"
    '  "document_type": "purchase_order",\n'
    '  "po_number": "PO-1009",\n'
    '  "vendor": { "name": "Initech LLC", },\n'
    '  "line_items": [\n'
    '    {"description": "Server rack, 42U", "quantity": 2, "unit_price": 800.00, "line_total": 1600.00\n'
)


# --------------------------------------------------------------------------- #
# Derived ground-truth maps (used to build the hashed relationships file)       #
# --------------------------------------------------------------------------- #
def vendor_orders() -> dict[str, list[str]]:
    """vendor_id -> [order numbers]."""
    out: dict[str, list[str]] = {}
    for d in DOCS:
        if d["kind"] == "po":
            out.setdefault(d["vendor"], []).append(d["number"])
    return out


def order_invoices() -> dict[str, list[str]]:
    """order number -> [invoice numbers that legitimately belong to it]."""
    out: dict[str, list[str]] = {d["number"]: [] for d in DOCS if d["kind"] == "po"}
    for d in DOCS:
        if d["kind"] == "invoice" and d.get("belongs_to"):
            out[d["belongs_to"]].append(d["number"])
    return out

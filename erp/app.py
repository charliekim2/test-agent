"""Fake ERP service for the PO/invoice interview.

Two endpoints the candidate integrates against:
  GET  /vendors  -> the canonical vendor list (resolve a document's vendor to a
                    vendor_id using these names / addresses / contacts).
  POST /bills    -> post a bill. This is the FINAL CORRECTNESS CHECK: it accepts
                    the bill only if the vendor owns the order AND every invoice
                    belongs to that order. That relationship is intentionally
                    NOT exposed by any GET endpoint.

The valid relationships are stored as salted SHA-256 hashes in
`relationships.json` (no plaintext mapping ships). Validation re-hashes the
incoming identifiers and checks membership.

Run locally:   uvicorn app:app --port 9000   (from this directory)
Interactive:   http://localhost:9000/docs    (Swagger UI, auto-generated)
"""

import hashlib
import json
import pathlib
from itertools import count

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

HERE = pathlib.Path(__file__).resolve().parent


def _load_json(name: str, default):
    path = HERE / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


VENDORS: list[dict] = _load_json("vendors.json", [])
_REL: dict = _load_json("relationships.json", {})

SALT: str = _REL.get("salt", "")
VENDOR_ORDER_HASHES: set[str] = set(_REL.get("vendor_order_hashes", []))
ORDER_INVOICE_HASHES: set[str] = set(_REL.get("order_invoice_hashes", []))
VENDOR_IDS: set[str] = {v["vendor_id"] for v in VENDORS}

# In-memory record of posted bills (resets on restart).
_POSTED: list[dict] = []
_bill_seq = count(1)


def _hash_pair(a: str, b: str) -> str:
    """Hash an identifier pair for the membership check: sha256(SALT|a|b)."""
    return hashlib.sha256(f"{SALT}|{a}|{b}".encode("utf-8")).hexdigest()


app = FastAPI(
    title="Fake ERP",
    version="1.0.0",
    description="Minimal ERP stand-in: list vendors and post bills. POST /bills "
                "validates the hidden vendor->order->invoice relationship.",
)


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #
class Address(BaseModel):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class Contact(BaseModel):
    email: str | None = None
    phone: str | None = None


class Vendor(BaseModel):
    vendor_id: str
    canonical_name: str
    address: Address | None = None
    contact: Contact | None = None
    tax_id: str | None = None


class BillLine(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class BillCreate(BaseModel):
    # Placeholder example ids only (PO-0000 / INV-0000 do not exist) so the docs
    # show the request shape without revealing a real vendor->order->invoice link.
    vendor_id: str = Field(..., examples=["VEND-001"])
    order_number: str = Field(..., examples=["PO-0000"])
    invoice_numbers: list[str] = Field(..., min_length=1, examples=[["INV-0000"]])
    total_amount: float = Field(..., examples=[1234.56])
    currency: str = "USD"
    lines: list[BillLine] | None = None


# --------------------------------------------------------------------------- #
# Endpoints                                                                    #
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok", "vendors": len(VENDORS)}


@app.get("/vendors", response_model=list[Vendor])
def list_vendors():
    """All vendors known to the ERP. Use these to resolve `vendor_id`."""
    return VENDORS


@app.post("/bills", status_code=201)
def post_bill(bill: BillCreate):
    """Post a bill. Validated in order; the first failure is returned.

    1. `vendor_id` must exist                       -> 404 vendor_not_found
    2. `order_number` must belong to that vendor    -> 422 order_vendor_mismatch
    3. every `invoice_number` must belong to order  -> 422 invoice_order_mismatch
    """
    if bill.vendor_id not in VENDOR_IDS:
        return JSONResponse(
            status_code=404,
            content={"error": "vendor_not_found", "detail": "Unknown vendor_id."},
        )

    if _hash_pair(bill.vendor_id, bill.order_number) not in VENDOR_ORDER_HASHES:
        return JSONResponse(
            status_code=422,
            content={
                "error": "order_vendor_mismatch",
                "detail": "This order number is not associated with this vendor.",
            },
        )

    offending = [
        inv for inv in bill.invoice_numbers
        if _hash_pair(bill.order_number, inv) not in ORDER_INVOICE_HASHES
    ]
    if offending:
        return JSONResponse(
            status_code=422,
            content={
                "error": "invoice_order_mismatch",
                "detail": "One or more invoice numbers do not belong to this order.",
                "offending": offending,
            },
        )

    bill_id = f"BILL-{next(_bill_seq):04d}"
    record = {
        "bill_id": bill_id,
        "status": "posted",
        "vendor_id": bill.vendor_id,
        "order_number": bill.order_number,
        "invoice_numbers": bill.invoice_numbers,
        "total_amount": bill.total_amount,
        "currency": bill.currency,
    }
    _POSTED.append(record)
    return record

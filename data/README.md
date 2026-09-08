# Seed documents

Free-form JSON, **one file per document**:

```
data/purchase_orders/PO-####.json
data/invoices/INV-####.json
```

Load them however you like (the app shells include a loader that reads every
`*.json` per directory and reports any file that fails to parse). The shape
below is the *ideal* — see `schemas/` for the formal JSON Schema. Reality is
messier than the schema on purpose.

## Document shape

| Field | Notes |
|---|---|
| `document_type` | `"purchase_order"` or `"invoice"`. |
| `po_number` / `invoice_number` | The identifier. POs use `po_number` (`PO-1234`), invoices use `invoice_number` (`INV-1234`). |
| `references_po` | (invoices only) A **hint** at the related PO. May be missing or wrong — don't trust it as ground truth. |
| `vendor` | `{ name, address?, contact?, tax_id? }`. The `name` is as written on the document and may differ slightly from the ERP's canonical spelling. `address`/`contact`/`tax_id` are useful fallback match keys. |
| `line_items[]` | Each: `{ description, quantity, unit_price, line_total, sku? }`. |
| `subtotal`, `shipping`, `tax`, `discount` | Money. Any of these may be absent (treat as 0 / unknown). `discount` is a positive amount subtracted. |
| `total` | The one money field always present — your amount-comparison anchor. |
| `currency`, `issue_date` | Always present. `currency` is ISO 4217; `issue_date` is the order/invoice date — an invoice's date is normally on or after its PO's, so it's a useful matching signal. |

Clean documents reconcile: `subtotal == Σ line_total` and
`total == subtotal + shipping + tax − discount`. Documents involved in an
exception may not.

Extra, sporadic fields (e.g. `payment_terms`, `department`, `notes`) may appear.
They are never required, but *could* help matching.

## What's in here

The set is small but deliberately varied. Across the documents you'll find,
among others: clean 1:1 matches, one order split across several invoices, an
under-fulfilled order, quantity/price discrepancies, an overbilled invoice, an
invoice with no order, an order with no invoice, slight vendor-name spelling
drift, the same vendor on more than one order, missing optional fields, and a
couple of malformed uploads (bad field types, and one file that isn't valid JSON
at all). Surfacing these cleanly is the point.

## A note on money

Amounts are decimals and can carry floating-point noise. Compare with a small
tolerance (or work in integer cents) rather than `==`. Identifiers — not amounts
— are what the ERP checks on `POST /bills`, so float drift won't break posting.

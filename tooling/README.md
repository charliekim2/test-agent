# Maintainer tooling (do NOT ship to candidates)

This directory is the **answer key** and the generator.

> ⚠️ `tooling/` is gitignored (`/tooling/` in `.gitignore`), so it is **not part
> of the git repo** — it won't be pushed and isn't visible to anyone you add as a
> collaborator. The flip side: it exists **only on your machine**. Keep a copy
> somewhere safe; the repo will not back it up.

## Files
- `ground_truth.py` — the single source of truth: vendors, documents, and the
  true vendor→order→invoice linkage. **Plaintext answer key.**
- `generate.py` — regenerates every candidate-facing artifact from the SSOT.
- `test_consistency.py` — guardrails (reconciliation, linkage, hash round-trips).
- `Makefile` — maintainer-only targets (kept out of the shipped root Makefile).
- `hidden_data/` — the held-back generalization set (see below). Generated.

## Regenerate after editing `ground_truth.py`
Run from the repo root (the targets live in this file, not the shipped Makefile):
```bash
make -f tooling/Makefile generate   # writes data/, tooling/hidden_data/, erp/*.json, openapi
make -f tooling/Makefile test       # consistency checks  (or: pytest tooling/)
```
Then commit the regenerated `data/` and `erp/*.json` and push.

## The hidden generalization set
`data/` holds the documents the candidate works with during the interview.
`tooling/hidden_data/` holds a **second set the candidate never sees up front**
(vendors VEND-008..013, numbers PO-2xxx / INV-3xxx). Send it to them only once
they're confident with their implementation — it checks that their solution
generalizes instead of overfitting the visible data. It's intentionally a touch
easier (cleaner vendor-name drift, no malformed/corrupt docs, no same-vendor
ambiguity) and covers: clean 1:1, 1:many fully fulfilled, partial fulfillment,
quantity/price discrepancy, orphan PO, orphan invoice.

The ERP already validates this set — its vendors are returned by `GET /vendors`
and its relationships are in `erp/relationships.json`, so a correct bill posts
green just like the visible set.

### How to hand it over
The seed loader reads `DATA_DIR/purchase_orders/*.json` and
`DATA_DIR/invoices/*.json`. Give the candidate the contents of
`tooling/hidden_data/` and have them either:
- copy the files into their `data/purchase_orders/` and `data/invoices/`, or
- point `DATA_DIR` at a folder laid out the same way.

No code change is required on their side — same shapes, new documents.

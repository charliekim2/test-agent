# PO ↔ Invoice Matching & ERP Posting

A take-home-style exercise for a live session. You have ~90 minutes. You may use
the internet and AI within reason, but you must be able to explain your design
choices and your code.

## The problem

You're given a pile of **purchase orders** and **invoices** as JSON documents
(in `data/`). Build a system that:

**Part 1 — Matching.** Match invoices to their purchase orders. Surface the
*exceptions* that matter (amounts that don't reconcile, vendor mismatches,
orders with no invoice, invoices with no order, …). Compute a similarity score
between documents and decide, above some threshold, whether to **auto-link** a
PO and an invoice as belonging to the same order. The approach is up to you
(exact keys, fuzzy/Levenshtein, embeddings — your call). Think about the
different relationships documents can have, and the user-error edge cases that
show up when people write and upload these documents.

**Part 2 — ERP readiness & posting.** Define a tolerance for how much an invoice
set may "drift" from its order (e.g. partial fulfillment, overbilling). If a set
is within tolerance, it's **ready to post**. Transform it into a *bill* and POST
it to the ERP. Constraints from the ERP:

- Every bill needs a **`vendor_id`**. The ERP owns the vendor list
  (`GET /vendors`); the documents only carry vendor *details* (name/address/
  contact), and the names don't always match exactly — you must associate them.
- A bill also needs an **order number** and **invoice number(s)**.
- `POST /bills` **rejects** the bill if the order isn't associated with the
  vendor, or an invoice doesn't belong to the order. This is your final
  correctness check — the order↔vendor↔invoice relationship is *not* exposed by
  any GET endpoint, so you have to get the matching right.

> Treat the ERP (`erp/`) as an opaque external service. Don't reverse-engineer
> its internals to recover the answer — use `GET /vendors` and `POST /bills`.

## What the scaffold gives you (and what it doesn't)

Provided, so you don't burn time on setup:

| | |
|---|---|
| `data/` | Seed POs & invoices, one JSON file per document. See `data/README.md`. |
| `schemas/` | JSON Schema (draft 2020-12) describing the *ideal* document shape. |
| `erp/` | A running fake ERP: `GET /vendors`, `POST /bills`, plus `/docs` (Swagger) and `/openapi.json`. |
| `app/python/`, `app/node/` | A thin app shell in each language: config, a DB connection helper, an ERP client, a seed loader, and a `TODO` entrypoint. |
| Docker Compose + Makefile | Two ways to run everything (see below). |

**Not** provided — this is your work: the matching/scoring logic, the data model
(no DB schema or migrations are created for you — model the documents and
relationships however suits the task; you can also just work in memory), the
drift/readiness rules, and the bill transformation.

## Run it — pick one language and one path

### Option A: no Docker (fastest to start)

Uses a file-backed SQLite DB and runs the ERP locally. Two terminals:

```bash
make erp            # terminal 1 — fake ERP on http://localhost:9000
make py             # terminal 2 — Python app     (creates venv, installs deps)
# or
make node           # terminal 2 — Node app       (npm install)
```

### Option B: Docker Compose

Postgres + ERP + your app, networked together. One command:

```bash
docker compose --profile python up   # postgres + erp + python app
# or
docker compose --profile node up     # postgres + erp + node app
```

Either way the app prints the loaded document counts and the ERP health on
startup. (Both ship identical code; only the env differs — Postgres vs SQLite,
service hostnames vs localhost.) `make help` lists all targets.

### Storage is a single switch

The app picks its store from `DATABASE_URL`:
`sqlite:///./app.sqlite` (fallback default) or `postgresql://…` (Docker default).
You're free to ignore the DB entirely and work from the loaded documents.

## Poke the ERP directly

```bash
curl http://localhost:9000/vendors
curl -X POST http://localhost:9000/bills -H 'content-type: application/json' \
  -d '{"vendor_id":"VEND-XXX","order_number":"PO-XXXX","invoice_numbers":["INV-XXXX"],"total_amount":0}'
```

A valid post returns `201`. Mismatches return `404` (unknown vendor) or `422`
(`order_vendor_mismatch` / `invoice_order_mismatch`).

## Languages & tooling

Python 3.12 (pip + venv) or Node 24 (npm). Use whichever you're faster in.
Suggested-but-optional libraries are listed (commented) in
`app/python/requirements.txt`; add anything you like.

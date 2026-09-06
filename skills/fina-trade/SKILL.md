---
name: fina-trade
description: Persist normalized equity-derivatives RFQs, versioned quotes, trades, and append-only lifecycle events in Postgres; expose the repository through MCP tools and bridge lifecycle events to FinA scheduler re-pricing.
---
# FinA Trade

Use this skill as the production trade-repository boundary. Persist RFQs, quotes, trades, and lifecycle events in Postgres through `PostgresTradeRepository`; use `TradeRepository` only for deterministic in-memory tests. The normalized relational contract is `schema/postgres.sql`.

## Domain model

Persist four related records:

- **RFQ**: client request, instrument/product identity, complete pricing request, correlation ID, and RFQ status.
- **Quote**: immutable quote version linked to an RFQ, complete pricing request, RiskCube summary/result reference, PV, price, validity, and optional expiry.
- **Trade**: accepted quote and RFQ references, instrument identity, economic terms, notional, currency, and lifecycle status.
- **Lifecycle event**: append-only before/after trade state, event type, reason, payload, and occurrence timestamp.

Do not overwrite a quote to represent a re-price. Create a new `quote_version`; update the trade’s accepted quote reference only when business logic accepts the new quote. RiskCube cells and large result objects remain owned by `fina-pricer` S3 persistence; store only the quote summary and object/reference metadata here.

## MCP tools

The `fina-trade` MCP server exposes:

- `rfq_create(rfq)`
- `quote_persist(quote)`
- `trade_accept(trade)`
- `trade_amend(trade_id, changes, reason)`
- `trade_get(trade_id)`
- `trade_lifecycle(trade_id)`

All tools use `POSTGRES_URL` or `DATABASE_URL`. Each mutation is transactional. `trade_amend` writes the trade and lifecycle event in one transaction; only a committed mutation may be bridged to the scheduler EventBus.

## Scheduler integration

Register the persistence adapter at the single scheduler entrance. The normal flow is:

```text
rfq_create
  → fina-pricer pricing_and_sensitivity
  → quote_persist
  → trade_accept
  → trade_amend / fixing / corporate event
  → lifecycle event
  → scheduler subscription
  → fina-pricer re-price
  → new quote version
```

Use stable IDs and correlation IDs across all records. Consumers must be idempotent by `event_id`. Never put credentials in RFQ, quote, trade, lifecycle payloads, or logs.

## Deployment

Manage dependencies with `uv sync` and commit `uv.lock`. The Vercel Python entrypoint is `api/index.py`; expose Streamable HTTP MCP at `/mcp`. Provision a Postgres-compatible Vercel database integration and inject its connection string as `POSTGRES_URL` or `DATABASE_URL`; run `schema/postgres.sql` as a controlled migration before enabling writes. Do not run destructive or implicit schema changes from ordinary MCP tools.

## Verification

Run `uv run pytest -q`. With a real Postgres database, migrate `schema/postgres.sql`, create an RFQ, persist two quote versions, accept one into a trade, amend the trade, then assert the RFQ status, quote versions, trade status, and ordered lifecycle events. The large RiskCube payload must remain in the pricer-owned S3 store and only its reference/summary may be persisted here.

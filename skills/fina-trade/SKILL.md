---
name: fina-trade
description: Persist normalized equity-derivatives RFQs, versioned quotes, trades, and append-only lifecycle events in Postgres; expose the repository through MCP tools and bridge lifecycle events to FinA scheduler re-pricing.
---
# FinA Trade

Use this skill as the production trade-repository boundary. Persist RFQs, quotes, trades, and lifecycle events in Postgres through `PostgresTradeRepository`; use `TradeRepository` only for deterministic in-memory tests. The normalized relational contract is `schema/postgres.sql`.

## Domain model

Persist six related records:

- **RFQ**: client request, instrument/product identity, complete pricing request, correlation ID, and RFQ status. An RFQ carries 1..N quotes (`quote_version`).
- **Quote**: immutable quote version linked to an RFQ, complete pricing request, RiskCube summary/result reference, PV, price, validity, and optional expiry. Each quote resolves to one instrument identity.
- **Trade**: accepted quote and RFQ references, instrument identity, economic terms, notional, currency, portfolio, quantity, and lifecycle status. Trades are many-to-one with an instrument.
- **Lifecycle event**: append-only before/after trade state, event type, reason, payload, and occurrence timestamp.
- **Instrument**: the tradeable product. Born at the *initial* quote of an RFQ — `initial_quote_id` and `priced_at` are stamped on the first quote and never overwritten by re-prices (a re-price writes a new `quote_version`, keeping the instrument priced at its initial datetime). Stays `indicative = TRUE` until a quote is accepted, then becomes a real instrument (`indicative = FALSE`).
- **Position**: aggregate of all non-terminal trades for one instrument in one portfolio, keyed by `(portfolio, instrument_id)` — `quantity` = Σ live trade quantity, `notional` = Σ live trade notional, `live_trades` = count. Recomputed transactionally on accept / amend / cancel; a position with zero live trades is removed.

Do not overwrite a quote to represent a re-price. Create a new `quote_version`; update the trade’s accepted quote reference only when business logic accepts the new quote. RiskCube cells and large result objects remain owned by `fina-pricer` S3 persistence; store only the quote summary and object/reference metadata here.

## MCP tools

The `fina-trade` MCP server exposes:

- `rfq_create(rfq)`
- `quote_persist(quote)` (creates the instrument at its initial quote)
- `trade_accept(trade)` (portfolio/quantity optional; realizes the instrument and creates/updates its position)
- `trade_amend(trade_id, changes, reason)` (terms plus optional portfolio/quantity; recomputes positions)
- `trade_cancel(trade_id, reason)`
- `trade_get(trade_id)`
- `trade_lifecycle(trade_id)`
- `rfq_query(filters?, created_from?, created_to?, limit?)`
- `quote_query(filters?, created_from?, created_to?, limit?)`
- `trade_query(filters?, created_from?, created_to?, limit?)`
- `instrument_query(filters?, created_from?, created_to?, limit?)`
- `position_query(filters?, limit?)`
- `lifecycle_query(filters?, created_from?, created_to?, limit?)`
- `database_health()` (connection + per-table row counts)

All tools use `POSTGRES_URL` or `DATABASE_URL`. Each mutation is transactional. `trade_amend` writes the trade and lifecycle event in one transaction; only a committed mutation may be bridged to the scheduler EventBus.

Every RFQ, quote, trade, and lifecycle event has UTC `created_at` and `updated_at` timestamps. Legacy domain timestamps (`received_at`, `quoted_at`, and `occurred_at`) are retained as aliases or event-time fields. Query tools accept ISO dates (`YYYY-MM-DD`) for `created_from` and `created_to`; the range is half-open and inclusive by calendar day. When both dates are omitted, the query returns records created from today at `00:00:00Z` through before tomorrow at `00:00:00Z`. `filters` supports exact indexed business fields such as IDs, status, instrument/product, currency, client, and lifecycle event type. Results are newest-first and capped at 500 rows.

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

Run `uv run pytest -q`. With a real Postgres database, migrate `schema/postgres.sql` (twice — the migration is idempotent), create an RFQ, persist two quote versions, accept one into a trade, amend the trade, then assert the RFQ status, quote versions, trade status, ordered lifecycle events, the instrument flipped `indicative=false`, and the position aggregated under `(portfolio, instrument_id)`. The large RiskCube payload must remain in the pricer-owned S3 store and only its reference/summary may be persisted here.

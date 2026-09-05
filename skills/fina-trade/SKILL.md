---
name: fina-trade
description: Register trades, observe fixing and corporate events, apply lifecycle transitions, and publish durable trade lifecycle events for FinA processes.
---
# FinA Trade

Use this skill as the trade-repository boundary. Validate trade payloads against `schema/trade.schema.json`, persist every mutation through `TradeRepository`, and publish an event only after the mutation succeeds. The repository is intentionally small and deterministic so it can be embedded by the scheduler or exposed by a future MCP server.

## Contract

A trade has stable `trade_id` and `instrument_id`, product and terms, positive `notional`, currency, status, quote, and ISO-8601 timestamps. `register_trade` accepts RFQ/quote data and creates `LIVE` only when `status` is explicitly supplied as `LIVE`; otherwise it remains `QUOTED`. `amend_trade` and `cancel_trade` are lifecycle mutations and publish `trade.lifecycle.amended` or `trade.lifecycle.cancelled`. `observe_trade` records an observation and publishes `trade.lifecycle.observed`; `apply_corporate_event` records a corporate event and publishes `trade.lifecycle.corporate_event`.

## Event envelope

```json
{"topic":"trade.lifecycle.amended","payload":{"trade_id":"T1","before":{},"after":{},"reason":"market_fixing"},"trade_id":"T1"}
```

Consumers must be idempotent by `event_id` or `(trade_id, updated_at, topic)`. Never overwrite a completed immutable audit record; the reference implementation keeps an in-memory append-only event log and can be replaced by a database adapter without changing the skill contract.

## Verification

Run `pytest -q tests`. The tests cover registration, amend/cancel transitions, fixing observations, corporate events, append-only event history, and invalid status transitions. In an end-to-end scheduler process, use `register`, then subscribe a pricing handler to lifecycle topics, and finish with grouped sensitivity OLAP.

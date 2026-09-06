from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row


class PostgresTradeRepository:
    """Transactional RFQ, quote, trade, and lifecycle repository."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
        if not self.dsn:
            raise RuntimeError("POSTGRES_URL or DATABASE_URL is required")

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[Any]]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    def migrate(self, sql: str) -> None:
        with self.connection() as conn:
            conn.execute(sql)

    def create_rfq(self, rfq: dict[str, Any]) -> dict[str, Any]:
        rfq_id = rfq.get("rfq_id", "RFQ-" + uuid.uuid4().hex)
        now = datetime.now(timezone.utc)
        record = {**rfq, "rfq_id": rfq_id}
        with self.connection() as conn:
            row = conn.execute("""
                INSERT INTO rfqs (rfq_id, correlation_id, client_id, instrument_id, product_type, request, status, received_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'RECEIVED', %s, %s)
                RETURNING *
            """, (rfq_id, record["correlation_id"], record.get("client_id"), record["instrument_id"], record["product_type"], Jsonb(record["request"]), now, now)).fetchone()
        return dict(row)

    def persist_quote(self, quote: dict[str, Any]) -> dict[str, Any]:
        with self.connection() as conn:
            version = conn.execute("SELECT COALESCE(MAX(quote_version), 0) + 1 AS next FROM quotes WHERE rfq_id = %s", (quote["rfq_id"],)).fetchone()["next"]
            quote_id = quote.get("quote_id", "Q-" + uuid.uuid4().hex)
            result = quote["quote"]
            valuation = result.get("RiskCube", {}).get("valuation", {})
            row = conn.execute("""
                INSERT INTO quotes (quote_id, rfq_id, quote_version, pricing_request, quote, pv_amount, pv_currency, price_pct_of_notional, status, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'VALID', %s)
                RETURNING *
            """, (quote_id, quote["rfq_id"], version, Jsonb(quote["pricing_request"]), Jsonb(result), result.get("PV", valuation.get("pv_amount")), result.get("PV_currency", valuation.get("pv_currency")), result.get("price_pct_of_notional", valuation.get("price_pct_of_notional")), quote.get("expires_at"))).fetchone()
            conn.execute("UPDATE rfqs SET status = 'QUOTED', updated_at = now() WHERE rfq_id = %s", (quote["rfq_id"],))
        return dict(row)

    def accept_quote(self, trade: dict[str, Any]) -> dict[str, Any]:
        trade_id = trade.get("trade_id", "T-" + uuid.uuid4().hex)
        with self.connection() as conn:
            quote = conn.execute("SELECT * FROM quotes WHERE quote_id = %s FOR UPDATE", (trade["quote_id"],)).fetchone()
            if not quote or quote["status"] not in ("VALID", "ACCEPTED"):
                raise ValueError("quote is not valid")
            row = conn.execute("""
                INSERT INTO trades (trade_id, rfq_id, accepted_quote_id, instrument_id, product_type, terms, notional, currency, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (trade_id, quote["rfq_id"], quote["quote_id"], trade["instrument_id"], trade["product_type"], Jsonb(trade.get("terms", {})), trade["notional"], trade["currency"], trade.get("status", "LIVE"))).fetchone()
            conn.execute("UPDATE quotes SET status = 'ACCEPTED', trade_id = %s WHERE quote_id = %s", (trade_id, quote["quote_id"]))
            conn.execute("UPDATE rfqs SET status = 'CONVERTED', updated_at = now() WHERE rfq_id = %s", (quote["rfq_id"],))
            self._event(conn, trade_id, "registered", None, dict(row), {"quote_id": quote["quote_id"]})
        return dict(row)

    def amend_trade(self, trade_id: str, changes: dict[str, Any], reason: str = "amend") -> dict[str, Any]:
        with self.connection() as conn:
            before = conn.execute("SELECT * FROM trades WHERE trade_id = %s FOR UPDATE", (trade_id,)).fetchone()
            if not before: raise KeyError(trade_id)
            if before["status"] in ("CANCELLED", "MATURED", "TERMINATED"): raise ValueError("trade is terminal")
            terms = dict(before["terms"] or {}); terms.update(changes.get("terms", {}))
            row = conn.execute("UPDATE trades SET terms = %s, status = 'AMENDED', updated_at = now() WHERE trade_id = %s RETURNING *", (Jsonb(terms), trade_id)).fetchone()
            self._event(conn, trade_id, "amended", dict(before), dict(row), {"changes": changes, "reason": reason})
        return dict(row)

    def get_trade(self, trade_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM trades WHERE trade_id = %s", (trade_id,)).fetchone()
        if not row: raise KeyError(trade_id)
        return dict(row)

    def lifecycle(self, trade_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM trade_lifecycle_events WHERE trade_id = %s ORDER BY occurred_at, event_id", (trade_id,)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _event(conn: psycopg.Connection[Any], trade_id: str, event_type: str, before: dict[str, Any] | None, after: dict[str, Any], payload: dict[str, Any]) -> None:
        conn.execute("INSERT INTO trade_lifecycle_events (event_id, trade_id, event_type, before_state, after_state, payload) VALUES (%s, %s, %s, %s, %s, %s)", (f"{trade_id}:{uuid.uuid4().hex}", trade_id, event_type, Jsonb(before) if before else None, Jsonb(after), Jsonb(payload)))

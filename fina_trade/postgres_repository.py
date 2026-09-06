from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterator

import psycopg
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row


def _jsonable(value: Any) -> Any:
    """Convert psycopg values into stable JSON/MCP-compatible values."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


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
        return _jsonable(dict(row))

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
        return _jsonable(dict(row))

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
            self._event(conn, trade_id, "registered", None, _jsonable(dict(row)), {"quote_id": quote["quote_id"]})
        return _jsonable(dict(row))

    def amend_trade(self, trade_id: str, changes: dict[str, Any], reason: str = "amend") -> dict[str, Any]:
        with self.connection() as conn:
            before = conn.execute("SELECT * FROM trades WHERE trade_id = %s FOR UPDATE", (trade_id,)).fetchone()
            if not before: raise KeyError(trade_id)
            if before["status"] in ("CANCELLED", "MATURED", "TERMINATED"): raise ValueError("trade is terminal")
            terms = dict(before["terms"] or {}); terms.update(changes.get("terms", {}))
            row = conn.execute("UPDATE trades SET terms = %s, status = 'AMENDED', updated_at = now() WHERE trade_id = %s RETURNING *", (Jsonb(terms), trade_id)).fetchone()
            self._event(conn, trade_id, "amended", _jsonable(dict(before)), _jsonable(dict(row)), {"changes": changes, "reason": reason})
        return _jsonable(dict(row))

    def get_trade(self, trade_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM trades WHERE trade_id = %s", (trade_id,)).fetchone()
        if not row: raise KeyError(trade_id)
        return _jsonable(dict(row))

    def lifecycle(self, trade_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM trade_lifecycle_events WHERE trade_id = %s ORDER BY occurred_at, event_id", (trade_id,)).fetchall()
        return [_jsonable(dict(row)) for row in rows]

    @staticmethod
    def _range_bounds(created_from: str | None, created_to: str | None) -> tuple[datetime, datetime]:
        """Return a half-open UTC range; omitted bounds mean today in UTC."""
        today = datetime.now(timezone.utc).date()
        start = datetime.combine(date.fromisoformat(created_from), time.min, tzinfo=timezone.utc) if created_from else datetime.combine(today, time.min, tzinfo=timezone.utc)
        end = datetime.combine(date.fromisoformat(created_to) + timedelta(days=1), time.min, tzinfo=timezone.utc) if created_to else (start + timedelta(days=1))
        if end <= start:
            raise ValueError("created_to must be on or after created_from")
        return start, end

    def _query(self, table: str, fields: dict[str, str], filters: dict[str, Any] | None, created_from: str | None, created_to: str | None, limit: int) -> dict[str, Any]:
        start, end = self._range_bounds(created_from, created_to)
        clauses = ["created_at >= %s", "created_at < %s"]
        values: list[Any] = [start, end]
        for key, value in (filters or {}).items():
            if value in (None, ""):
                continue
            column = fields.get(key)
            if column is None:
                raise ValueError(f"unsupported filter for {table}: {key}")
            clauses.append(f"{column} = %s")
            values.append(value)
        safe_limit = max(1, min(int(limit), 500))
        sql = f"SELECT * FROM {table} WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT %s"
        values.append(safe_limit)
        with self.connection() as conn:
            rows = conn.execute(sql, values).fetchall()
        return {"rows": [_jsonable(dict(row)) for row in rows], "count": len(rows), "created_from": start.isoformat(), "created_to": end.isoformat(), "limit": safe_limit}

    def query_rfqs(self, filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self._query("rfqs", {"rfq_id": "rfq_id", "correlation_id": "correlation_id", "client_id": "client_id", "instrument_id": "instrument_id", "product_type": "product_type", "status": "status"}, filters, created_from, created_to, limit)

    def query_quotes(self, filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self._query("quotes", {"quote_id": "quote_id", "rfq_id": "rfq_id", "trade_id": "trade_id", "status": "status", "pv_currency": "pv_currency"}, filters, created_from, created_to, limit)

    def query_trades(self, filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self._query("trades", {"trade_id": "trade_id", "rfq_id": "rfq_id", "accepted_quote_id": "accepted_quote_id", "instrument_id": "instrument_id", "product_type": "product_type", "currency": "currency", "status": "status"}, filters, created_from, created_to, limit)

    def query_lifecycle(self, filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self._query("trade_lifecycle_events", {"event_id": "event_id", "trade_id": "trade_id", "event_type": "event_type"}, filters, created_from, created_to, limit)

    @staticmethod
    def _event(conn: psycopg.Connection[Any], trade_id: str, event_type: str, before: dict[str, Any] | None, after: dict[str, Any], payload: dict[str, Any]) -> None:
        conn.execute("INSERT INTO trade_lifecycle_events (event_id, trade_id, event_type, before_state, after_state, payload) VALUES (%s, %s, %s, %s, %s, %s)", (f"{trade_id}:{uuid.uuid4().hex}", trade_id, event_type, Jsonb(before) if before else None, Jsonb(after), Jsonb(payload)))

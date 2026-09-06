from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .postgres_repository import PostgresTradeRepository


def repository() -> PostgresTradeRepository:
    return PostgresTradeRepository()


def _allowed_hosts() -> list[str]:
    """Allow Vercel's runtime host plus local development hosts."""
    hosts = {
        "fina-trade-ten.vercel.app",
        "localhost",
        "localhost:*",
        "127.0.0.1",
        "127.0.0.1:*",
    }
    for key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        value = os.environ.get(key, "").strip()
        if value:
            hosts.add(value.removeprefix("https://").removeprefix("http://").rstrip("/"))
    extra = os.environ.get("FINA_ALLOWED_HOSTS", "")
    hosts.update(item.strip() for item in extra.split(",") if item.strip())
    return sorted(hosts)


mcp = FastMCP(
    "fina-trade",
    transport_security=TransportSecuritySettings(allowed_hosts=_allowed_hosts()),
)


@mcp.tool()
def database_health() -> dict[str, Any]:
    """Check that the configured Postgres database is reachable and report per-table row counts."""
    return repository().health()


@mcp.tool()
def database_migrate() -> dict[str, Any]:
    """Apply the additive normalized schema; require explicit migration opt-in."""
    if os.environ.get("FINA_ALLOW_MIGRATIONS") != "true":
        raise ValueError("set FINA_ALLOW_MIGRATIONS=true for explicit schema migration")
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "schema" / "postgres.sql").read_text(encoding="utf-8")
    repository().migrate(sql)
    return {"ok": True, "migrated": True}


@mcp.tool()
def rfq_create(rfq: dict[str, Any]) -> dict[str, Any]:
    """Persist a received equity-derivatives RFQ."""
    return repository().create_rfq(rfq)


@mcp.tool()
def quote_persist(quote: dict[str, Any]) -> dict[str, Any]:
    """Persist a versioned quote returned by fina-pricer for an RFQ."""
    return repository().persist_quote(quote)


@mcp.tool()
def trade_accept(trade: dict[str, Any]) -> dict[str, Any]:
    """Accept a quote and create the normalized trade aggregate."""
    return repository().accept_quote(trade)


@mcp.tool()
def trade_amend(trade_id: str, changes: dict[str, Any], reason: str = "amend") -> dict[str, Any]:
    """Apply a lifecycle amendment (terms and optionally portfolio/quantity) and append an audit event transactionally."""
    return repository().amend_trade(trade_id, changes, reason)


@mcp.tool()
def trade_cancel(trade_id: str, reason: str = "cancel") -> dict[str, Any]:
    """Cancel a non-terminal trade and recompute the affected (portfolio, instrument_id) position."""
    return repository().cancel_trade(trade_id, reason)


@mcp.tool()
def trade_get(trade_id: str) -> dict[str, Any]:
    """Read one normalized trade."""
    return repository().get_trade(trade_id)


@mcp.tool()
def trade_lifecycle(trade_id: str) -> list[dict[str, Any]]:
    """Read append-only lifecycle events for one trade."""
    return repository().lifecycle(trade_id)


@mcp.tool()
def rfq_query(filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Query RFQs; omitted dates default to the current UTC day."""
    return repository().query_rfqs(filters, created_from, created_to, limit)


@mcp.tool()
def quote_query(filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Query quotes; omitted dates default to the current UTC day."""
    return repository().query_quotes(filters, created_from, created_to, limit)


@mcp.tool()
def trade_query(filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Query trades; omitted dates default to the current UTC day."""
    return repository().query_trades(filters, created_from, created_to, limit)


@mcp.tool()
def instrument_query(filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Query tradeable instruments; an instrument is born at its initial quote (priced at that datetime) and becomes real (indicative=false) when a quote is accepted."""
    return repository().query_instruments(filters, created_from, created_to, limit)


@mcp.tool()
def position_query(filters: dict[str, Any] | None = None, limit: int = 100) -> dict[str, Any]:
    """Query live positions aggregated per (portfolio, instrument_id) over non-terminal trades."""
    return repository().query_positions(filters, limit)


@mcp.tool()
def lifecycle_query(filters: dict[str, Any] | None = None, created_from: str | None = None, created_to: str | None = None, limit: int = 100) -> dict[str, Any]:
    """Query lifecycle events; omitted dates default to the current UTC day."""
    return repository().query_lifecycle(filters, created_from, created_to, limit)


def main() -> None:
    mcp.run(transport=os.environ.get("MCP_TRANSPORT", "stdio"))


app = mcp.streamable_http_app()

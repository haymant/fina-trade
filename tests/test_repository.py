import os

import pytest
from fina_trade import TradeRepository


def trade():
    return {"trade_id": "T1", "instrument_id": "FCN-1", "product_type": "FCN", "notional": 100000.0, "currency": "USD", "quote": {"pv": 98.2}}


def test_register_amend_observe_and_event_order():
    events = []
    repo = TradeRepository(events.append)
    assert repo.register(trade())["status"] == "QUOTED"
    assert repo.amend("T1", {"quote": {"pv": 97.9}}, "new_market")['status'] == "AMENDED"
    repo.observe("T1", {"date": "2027-06-01", "fixing": 6.1})
    assert [event["topic"] for event in events] == ["trade.lifecycle.registered", "trade.lifecycle.amended", "trade.lifecycle.observed"]
    assert len(repo.events) == 3


def test_cancel_is_terminal():
    repo = TradeRepository()
    repo.register(trade())
    assert repo.cancel("T1")["status"] == "CANCELLED"
    with pytest.raises(ValueError): repo.amend("T1", {"quote": {"pv": 1}})


def test_invalid_trade_rejected():
    with pytest.raises(ValueError): TradeRepository().register({"trade_id": "x", "instrument_id": "i", "product_type": "FCN", "notional": 0, "currency": "USD"})
    with pytest.raises(ValueError): TradeRepository().register({"trade_id": "y", "instrument_id": "i", "product_type": "FCN", "notional": 10, "currency": "USD", "quantity": 0})


def test_positions_aggregate_live_trades_per_portfolio_instrument():
    repo = TradeRepository()
    base = {"instrument_id": "FCN-1", "product_type": "FCN", "notional": 100000.0, "currency": "USD"}
    repo.register({"trade_id": "T1", **base})
    repo.register({"trade_id": "T2", **base, "quantity": 2, "portfolio": "RISK"})
    repo.register({"trade_id": "T3", **base, "notional": 50000.0, "portfolio": "RISK"})
    positions = repo.positions()
    assert len(positions) == 2
    by_key = {(p["portfolio"], p["instrument_id"]): p for p in positions}
    assert by_key[("DEFAULT", "FCN-1")]["live_trades"] == 1
    assert by_key[("DEFAULT", "FCN-1")]["notional"] == 100000.0
    assert by_key[("RISK", "FCN-1")]["live_trades"] == 2
    assert by_key[("RISK", "FCN-1")]["quantity"] == 3
    assert by_key[("RISK", "FCN-1")]["notional"] == 150000.0
    repo.cancel("T2", "stop")
    positions = repo.positions()
    by_key = {(p["portfolio"], p["instrument_id"]): p for p in positions}
    assert by_key[("RISK", "FCN-1")]["live_trades"] == 1
    assert by_key[("RISK", "FCN-1")]["quantity"] == 1


@pytest.mark.skipif(not os.environ.get("POSTGRES_URL"), reason="POSTGRES_URL is required for Postgres-backed tests")
def test_pg_instrument_position_lifecycle():
    from pathlib import Path
    from fina_trade.postgres_repository import PostgresTradeRepository

    repo = PostgresTradeRepository()
    repo.migrate((Path(__file__).resolve().parents[1] / "schema" / "postgres.sql").read_text(encoding="utf-8"))

    rfq = repo.create_rfq({
        "rfq_id": "RFQ-TEST-INST-1", "correlation_id": "corr-test-inst-1", "client_id": "acmecap",
        "instrument_id": "FCN-QA-001", "product_type": "FCN",
        "request": {"payload": "req", "parameters": {"spot": 100.0}},
    })

    def price(quote_id):
        return {
            "quote_id": quote_id, "rfq_id": rfq["rfq_id"],
            "pricing_request": {"InstrumentKey": {"name": "FCN-QA-001", "product_type": "FCN"}, "parameters": {"spot": 100.0}},
            "quote": {"PV": 98200.0, "PV_currency": "USD", "price_pct_of_notional": 98.2, "RiskCube": {"valuation": {}}},
        }

    repo.persist_quote(price("Q-INST-1"))
    repo.persist_quote(price("Q-INST-2"))
    instruments = repo.query_instruments({"instrument_id": "FCN-QA-001"})
    assert instruments["count"] == 1
    born = instruments["rows"][0]
    assert born["indicative"] is True
    assert born["initial_quote_id"] == "Q-INST-1"

    trade = repo.accept_quote({
        "trade_id": "T-INST-1", "quote_id": "Q-INST-2", "instrument_id": "FCN-QA-001", "product_type": "FCN",
        "notional": 200000.0, "currency": "USD", "portfolio": "RISK", "quantity": 2, "terms": {"strike": 100.0},
    })
    assert trade["portfolio"] == "RISK"
    assert trade["quantity"] == 2.0

    instruments = repo.query_instruments({"instrument_id": "FCN-QA-001"})
    assert instruments["rows"][0]["indicative"] is False
    assert instruments["rows"][0]["initial_quote_id"] == "Q-INST-1"

    positions = repo.query_positions({"instrument_id": "FCN-QA-001"})
    assert positions["count"] == 1
    pos = positions["rows"][0]
    assert pos["portfolio"] == "RISK"
    assert pos["quantity"] == 2.0
    assert pos["notional"] == "200000"
    assert pos["live_trades"] == 1

    repo.amend_trade("T-INST-1", {"terms": {"strike": 99.0}}, "reprice")
    repo.cancel_trade("T-INST-1", "test")
    assert repo.query_positions({"instrument_id": "FCN-QA-001"})["count"] == 0

    health = repo.health()
    assert health["ok"] is True
    assert "instruments" in health["tables"] and "positions" in health["tables"]

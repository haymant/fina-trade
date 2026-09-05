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

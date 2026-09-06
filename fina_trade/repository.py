from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TradeRepository:
    """Append-only trade state plus lifecycle event history."""
    VALID = {"RFQ", "QUOTED", "LIVE", "AMENDED", "CANCELLED", "MATURED", "TERMINATED"}
    TERMINAL = {"CANCELLED", "MATURED", "TERMINATED"}

    def __init__(self, publish=None):
        self.trades: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.publish = publish

    def register(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        item = deepcopy(trade)
        required = ["trade_id", "instrument_id", "product_type", "notional", "currency"]
        missing = [key for key in required if key not in item]
        if missing: raise ValueError("missing trade fields: " + ",".join(missing))
        if item["notional"] <= 0: raise ValueError("notional must be positive")
        if item["trade_id"] in self.trades: raise ValueError("trade already exists: " + item["trade_id"])
        item.setdefault("portfolio", "DEFAULT")
        item.setdefault("quantity", 1)
        if item["quantity"] <= 0: raise ValueError("quantity must be positive")
        item.setdefault("status", "QUOTED")
        if item["status"] not in self.VALID: raise ValueError("invalid status")
        item.setdefault("created_at", _now()); item["updated_at"] = item["created_at"]
        self.trades[item["trade_id"]] = item
        self._emit("trade.lifecycle.registered", item["trade_id"], {"after": item})
        return deepcopy(item)

    def get(self, trade_id: str) -> Dict[str, Any]:
        if trade_id not in self.trades: raise KeyError(trade_id)
        return deepcopy(self.trades[trade_id])

    def amend(self, trade_id: str, changes: Dict[str, Any], reason: str = "amend") -> Dict[str, Any]:
        return self._mutate(trade_id, "AMENDED", changes, "trade.lifecycle.amended", reason)

    def cancel(self, trade_id: str, reason: str = "cancel") -> Dict[str, Any]:
        return self._mutate(trade_id, "CANCELLED", {}, "trade.lifecycle.cancelled", reason)

    def observe(self, trade_id: str, observation: Dict[str, Any]) -> Dict[str, Any]:
        trade = self._mutable(trade_id)
        trade.setdefault("observations", []).append(deepcopy(observation))
        trade["updated_at"] = _now()
        self._emit("trade.lifecycle.observed", trade_id, {"observation": observation, "after": trade})
        return deepcopy(trade)

    def apply_corporate_event(self, trade_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        trade = self._mutable(trade_id)
        trade.setdefault("corporate_events", []).append(deepcopy(event))
        trade["updated_at"] = _now()
        self._emit("trade.lifecycle.corporate_event", trade_id, {"event": event, "after": trade})
        return deepcopy(trade)

    def positions(self) -> List[Dict[str, Any]]:
        """Aggregate live trades per (portfolio, instrument_id)."""
        aggregate: Dict[tuple, Dict[str, Any]] = {}
        for trade in self.trades.values():
            if trade["status"] in self.TERMINAL:
                continue
            key = (trade.get("portfolio", "DEFAULT"), trade["instrument_id"])
            row = aggregate.setdefault(key, {
                "portfolio": key[0], "instrument_id": key[1], "product_type": trade["product_type"],
                "quantity": 0, "notional": 0, "currency": trade["currency"], "live_trades": 0, "updated_at": trade["updated_at"],
            })
            row["quantity"] = (row["quantity"] or 0) + (trade.get("quantity") or 1)
            row["notional"] = (row["notional"] or 0) + float(trade["notional"])
            row["live_trades"] += 1
            if trade["updated_at"] > row["updated_at"]:
                row["updated_at"] = trade["updated_at"]
        return [aggregate[key] for key in sorted(aggregate)]

    def _mutable(self, trade_id: str) -> Dict[str, Any]:
        if trade_id not in self.trades: raise KeyError(trade_id)
        if self.trades[trade_id]["status"] in self.TERMINAL: raise ValueError("trade is terminal")
        return self.trades[trade_id]

    def _mutate(self, trade_id: str, status: str, changes: Dict[str, Any], topic: str, reason: str) -> Dict[str, Any]:
        trade = self._mutable(trade_id); before = deepcopy(trade)
        trade.update(deepcopy(changes)); trade["status"] = status; trade["updated_at"] = _now()
        self._emit(topic, trade_id, {"before": before, "after": trade, "reason": reason})
        return deepcopy(trade)

    def _emit(self, topic: str, trade_id: str, payload: Dict[str, Any]) -> None:
        event = {"topic": topic, "trade_id": trade_id, "event_id": "%s:%d" % (trade_id, len(self.events) + 1), "payload": deepcopy(payload)}
        self.events.append(event)
        if self.publish: self.publish(event)

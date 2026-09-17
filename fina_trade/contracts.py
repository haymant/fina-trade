from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TradeContractError(ValueError):
    code = "trade.contract_error"


class IllegalTransitionError(TradeContractError):
    code = "trade.illegal_transition"


class StaleStateVersionError(TradeContractError):
    code = "trade.stale_state_version"


class TerminalTradeError(TradeContractError):
    code = "trade.terminal_state"


@dataclass(frozen=True)
class Operation:
    name: str
    from_states: frozenset[str]
    to_state: str | None
    actor_capability: str
    reason_required: bool
    repricing_required: bool
    settlement_effect: str
    event_topic: str
    refresh_targets: tuple[str, ...]


OPERATIONS: dict[str, Operation] = {
    "trade.accept": Operation("trade.accept", frozenset({"QUOTED"}), "LIVE", "trading.trade.accept", True, False, "open", "trade.accepted", ("trading.trade.trades", "trading.position.positions")),
    "trade.amend": Operation("trade.amend", frozenset({"LIVE", "AMENDED"}), "AMENDED", "trading.trade.amend", True, True, "adjust", "trade.amended", ("trading.trade.trades", "trading.position.positions", "trading.lifecycle.timeline")),
    "trade.cancel": Operation("trade.cancel", frozenset({"LIVE", "AMENDED"}), "CANCELLED", "trading.trade.cancel", True, False, "close", "trade.cancelled", ("trading.trade.trades", "trading.position.positions", "trading.lifecycle.timeline")),
    "trade.fixing": Operation("trade.fixing", frozenset({"LIVE", "AMENDED"}), None, "trading.trade.fixing", True, True, "none", "trade.fixing.recorded", ("trading.trade.trades", "trading.lifecycle.timeline")),
    "trade.settle": Operation("trade.settle", frozenset({"LIVE", "AMENDED"}), "MATURED", "trading.trade.settle", True, False, "close", "trade.settled", ("trading.trade.trades", "trading.position.positions", "trading.lifecycle.timeline")),
}


def validate_operation(name: str, current_state: str, expected_state_version: int | None, actual_state_version: int, reason: str | None = None) -> Operation:
    operation = OPERATIONS.get(name)
    if operation is None:
        raise IllegalTransitionError(f"unknown operation: {name}")
    if current_state in {"CANCELLED", "MATURED", "TERMINATED"}:
        raise TerminalTradeError(f"trade is terminal: {current_state}")
    if current_state not in operation.from_states:
        raise IllegalTransitionError(f"{name} cannot transition from {current_state}")
    if expected_state_version is not None and expected_state_version != actual_state_version:
        raise StaleStateVersionError(f"expected state_version={expected_state_version}, actual={actual_state_version}")
    if operation.reason_required and not (reason and reason.strip()):
        raise TradeContractError(f"reason is required for {name}")
    return operation


def envelope(result: Any, *, operation: str, correlation_id: str, causation_id: str | None = None) -> dict[str, Any]:
    return {"schema": "fina.trade.operation-result.v1", "operation": operation, "correlation_id": correlation_id, "causation_id": causation_id, "result": result}

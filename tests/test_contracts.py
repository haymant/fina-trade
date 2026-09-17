import json
from pathlib import Path

import pytest

from fina_trade.contracts import IllegalTransitionError, StaleStateVersionError, TerminalTradeError, validate_operation


def test_operation_registry_separates_amend_cancel_and_fixing():
    amend = validate_operation("trade.amend", "LIVE", 0, 0, "market move")
    cancel = validate_operation("trade.cancel", "LIVE", 0, 0, "desk close")
    fixing = validate_operation("trade.fixing", "LIVE", 0, 0, "observation")
    assert amend.event_topic != cancel.event_topic
    assert fixing.to_state is None
    assert amend.repricing_required is True
    assert cancel.repricing_required is False


def test_stale_versions_and_terminal_states_are_typed():
    with pytest.raises(StaleStateVersionError):
        validate_operation("trade.amend", "LIVE", 1, 2, "retry")
    with pytest.raises(TerminalTradeError):
        validate_operation("trade.cancel", "CANCELLED", 0, 0, "retry")
    with pytest.raises(IllegalTransitionError):
        validate_operation("trade.accept", "LIVE", 0, 0, "retry")


def test_canonical_schema_requires_concurrency_and_trace_fields():
    schema = json.loads((Path(__file__).parents[1] / "schema/trade/canonical.schema.json").read_text())
    assert set(schema["required"]) >= {"state_version", "correlation_id", "trade_id"}
    assert schema["properties"]["status"]["enum"] == ["QUOTED", "LIVE", "AMENDED", "CANCELLED", "MATURED", "TERMINATED"]

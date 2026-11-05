"""Staff-decision input validation (#27), without workflow or database calls."""

from typing import Any

import pytest
from pydantic import ValidationError

from clinic_assistant.messages import SavedDecision, StaffDecisionRequest

INVALID_DECISIONS: tuple[object, ...] = (
    "approved",
    "rejected",
    "APPROVE",
    " approve ",
    "",
    None,
    True,
    1,
    [],
    {},
)
INVALID_REASONS: tuple[object, ...] = (
    None,
    "",
    " \t\r\n",
    "\u2003\u00a0",
    123,
    True,
    [],
    {},
    "x" * 1001,
    "🙂" * 1001,
    " \t" + "x" * 1001 + "\n ",
)


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_valid_decision_trims_reason(decision: str) -> None:
    payload = {"decision": decision, "reason": " \tReviewed by staff.\n "}
    request = StaffDecisionRequest.model_validate(payload)
    assert request.model_dump() == {
        "decision": decision,
        "reason": "Reviewed by staff.",
    }


@pytest.mark.parametrize(
    "reason",
    [
        "x",
        "x" * 1000,
        "🙂" * 1000,
        " \t" + "🙂" * 1000 + "\n ",
        "\u2003Reviewed\u00a0",
    ],
)
def test_reason_boundaries_count_code_points_after_trimming(reason: str) -> None:
    request = StaffDecisionRequest(decision="approve", reason=reason)
    assert request.reason == reason.strip()


@pytest.mark.parametrize(
    "payload,field",
    [
        ({}, "decision"),
        ({"reason": "Reviewed"}, "decision"),
        ({"decision": "approve"}, "reason"),
        *[
            ({"decision": decision, "reason": "Reviewed"}, "decision")
            for decision in INVALID_DECISIONS
        ],
        *[
            ({"decision": "reject", "reason": reason}, "reason")
            for reason in INVALID_REASONS
        ],
        (
            {"decision": "approve", "reason": "Reviewed", "extra": True},
            "extra",
        ),
        (
            {
                "decision": "approve",
                "reason": "Reviewed",
                "decided_at": "2026-11-05T10:00:00+04:00",
            },
            "decided_at",
        ),
    ],
)
def test_invalid_decision_input(payload: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError) as error:
        StaffDecisionRequest.model_validate(payload)
    assert error.value.errors()[0]["loc"] == (field,)


def test_input_schema_contains_only_required_staff_fields() -> None:
    schema = StaffDecisionRequest.model_json_schema()
    assert set(schema["properties"]) == {"decision", "reason"}
    assert set(schema["required"]) == {"decision", "reason"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["decision"]["enum"] == ["approve", "reject"]
    assert schema["properties"]["reason"]["minLength"] == 1
    assert schema["properties"]["reason"]["maxLength"] == 1000


def test_saved_decision_preserves_existing_contract() -> None:
    saved = SavedDecision.model_validate(
        {
            "decision": "reject",
            "reason": " \tReviewed\n",
            "decided_at": "2026-11-05T10:00:00+04:00",
        }
    )
    assert saved.reason == "Reviewed"
    assert saved.decided_at.utcoffset() is not None
    with pytest.raises(ValidationError):
        SavedDecision.model_validate({"decision": "reject", "reason": "Reviewed"})

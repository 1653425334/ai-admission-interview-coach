from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.interview_map import InterviewMap, VerificationStatus
from app.services.interview_map_validation import InterviewMapValidationError, validate_interview_map


FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "milestone_two"


def gold_map() -> dict[str, object]:
    return json.loads(
        (FIXTURE_DIRECTORY / "attention_robustness_interview_map.json").read_text(
            encoding="utf-8"
        )
    )


def test_gold_interview_map_is_schema_valid_and_semantically_valid() -> None:
    interview_map = InterviewMap.model_validate(gold_map())

    validate_interview_map(interview_map)

    assert interview_map.schema_version == "interview-map-v1"
    assert interview_map.risks[0].verification_status is VerificationStatus.UNVERIFIED


def test_schema_rejects_unknown_fields() -> None:
    payload = gold_map()
    payload["unexpected"] = "not permitted"

    with pytest.raises(ValidationError, match="unexpected"):
        InterviewMap.model_validate(payload)


def test_schema_defaults_risk_to_unverified() -> None:
    payload = gold_map()
    del payload["risks"][0]["verification_status"]  # type: ignore[index]

    interview_map = InterviewMap.model_validate(payload)

    assert interview_map.risks[0].verification_status is VerificationStatus.UNVERIFIED


def test_validation_rejects_risk_without_known_evidence() -> None:
    payload = gold_map()
    payload["risks"][0]["evidence_ids"] = ["ev-missing"]  # type: ignore[index]

    with pytest.raises(InterviewMapValidationError, match="unknown evidence"):
        validate_interview_map(InterviewMap.model_validate(payload))


def test_validation_rejects_risk_without_known_claim() -> None:
    payload = gold_map()
    payload["risks"][0]["claim_id"] = "claim-missing"  # type: ignore[index]

    with pytest.raises(InterviewMapValidationError, match="unknown claim"):
        validate_interview_map(InterviewMap.model_validate(payload))


def test_schema_rejects_objective_without_coverage_conditions() -> None:
    payload = gold_map()
    payload["risks"][0]["objectives"][0]["coverage_conditions"] = []  # type: ignore[index]

    with pytest.raises(ValidationError, match="coverage_conditions"):
        InterviewMap.model_validate(payload)


def test_validation_rejects_non_initial_verification_status() -> None:
    payload = gold_map()
    payload["risks"][0]["verification_status"] = "VERIFIED"  # type: ignore[index]

    with pytest.raises(InterviewMapValidationError, match="UNVERIFIED"):
        validate_interview_map(InterviewMap.model_validate(payload))


def test_validation_rejects_profile_claim_reference_outside_claims() -> None:
    payload = gold_map()
    payload["candidate_profile"]["high_value_claim_ids"] = ["claim-missing"]  # type: ignore[index]

    with pytest.raises(InterviewMapValidationError, match="profile"):
        validate_interview_map(InterviewMap.model_validate(payload))


def test_validation_rejects_evidence_outside_input_manifest() -> None:
    payload = gold_map()
    payload["evidence"][0]["document_id"] = "44444444-4444-4444-8444-444444444444"  # type: ignore[index]

    with pytest.raises(InterviewMapValidationError, match="input manifest"):
        validate_interview_map(InterviewMap.model_validate(payload))

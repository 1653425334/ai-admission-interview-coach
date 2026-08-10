"""Deterministic semantic checks for persisted ``interview-map-v1`` output."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.interview_map import InterviewMap, VerificationStatus


class InterviewMapValidationError(ValueError):
    """Raised when a schema-valid map violates cross-object M2 invariants."""


def validate_interview_map(interview_map: InterviewMap) -> None:
    """Validate references and M2-only invariants before persistence.

    Pydantic verifies shape. This service verifies relationships which a
    structured-output provider cannot enforce: evidence must come from the
    immutable input snapshot, risks must remain evidence-grounded, and the
    profile can only point at claims already represented in the map.
    """

    _assert_unique((evidence.evidence_id for evidence in interview_map.evidence), "evidence ID")
    _assert_unique((claim.claim_id for claim in interview_map.claims), "claim ID")
    _assert_unique((risk.risk_id for risk in interview_map.risks), "risk ID")
    _assert_unique(interview_map.priority_risk_ids, "priority risk ID")

    manifest_by_document_id = {
        document.document_id: document for document in interview_map.input_manifest
    }
    evidence_by_id = {evidence.evidence_id: evidence for evidence in interview_map.evidence}
    claim_by_id = {claim.claim_id: claim for claim in interview_map.claims}
    risk_ids = {risk.risk_id for risk in interview_map.risks}

    for evidence in interview_map.evidence:
        manifest_document = manifest_by_document_id.get(evidence.document_id)
        if manifest_document is None:
            raise InterviewMapValidationError(
                f"evidence {evidence.evidence_id} references a document outside the input manifest"
            )
        if manifest_document.document_type != evidence.document_type:
            raise InterviewMapValidationError(
                f"evidence {evidence.evidence_id} document type does not match the input manifest"
            )
        if evidence.location.page_number > manifest_document.page_count:
            raise InterviewMapValidationError(
                f"evidence {evidence.evidence_id} page number exceeds the input manifest"
            )

    for claim in interview_map.claims:
        _require_known_ids(
            claim.evidence_ids,
            evidence_by_id,
            f"claim {claim.claim_id} references unknown evidence",
        )

    objective_ids: list[str] = []
    condition_ids: list[str] = []
    for risk in interview_map.risks:
        _require_known_ids(
            risk.evidence_ids,
            evidence_by_id,
            f"risk {risk.risk_id} references unknown evidence",
        )
        claim = claim_by_id.get(risk.claim_id)
        if claim is None:
            raise InterviewMapValidationError(
                f"risk {risk.risk_id} references unknown claim {risk.claim_id}"
            )
        if not set(risk.evidence_ids).intersection(claim.evidence_ids):
            raise InterviewMapValidationError(
                f"risk {risk.risk_id} must share evidence with associated claim {risk.claim_id}"
            )
        if risk.verification_status is not VerificationStatus.UNVERIFIED:
            raise InterviewMapValidationError(
                f"M2 risk {risk.risk_id} must start with verification_status UNVERIFIED"
            )

        for objective in risk.objectives:
            objective_ids.append(objective.objective_id)
            condition_ids.extend(condition.condition_id for condition in objective.coverage_conditions)
            if objective.risk_id != risk.risk_id:
                raise InterviewMapValidationError(
                    f"objective {objective.objective_id} must reference parent risk {risk.risk_id}"
                )
            if objective.target_claim_id != risk.claim_id:
                raise InterviewMapValidationError(
                    f"objective {objective.objective_id} must reference risk claim {risk.claim_id}"
                )

    _assert_unique(objective_ids, "objective ID")
    _assert_unique(condition_ids, "coverage condition ID")
    _require_known_ids(
        interview_map.candidate_profile.high_value_claim_ids,
        claim_by_id,
        "candidate profile references claim outside the map",
    )
    _require_known_ids(
        interview_map.priority_risk_ids,
        risk_ids,
        "priority risk references unknown risk",
    )


def _assert_unique(values: Iterable[str], label: str) -> None:
    items = list(values)
    if len(items) != len(set(items)):
        raise InterviewMapValidationError(f"duplicate {label} values are not allowed")


def _require_known_ids(
    referenced_ids: Iterable[str], known_ids: Iterable[str], message: str
) -> None:
    known = set(known_ids)
    missing = sorted(set(referenced_ids).difference(known))
    if missing:
        raise InterviewMapValidationError(f"{message}: {', '.join(missing)}")

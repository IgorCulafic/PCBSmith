from __future__ import annotations

import hashlib

from pcbsmith.kicad.escape_technology import (
    EscapeGeometryTrial,
    EscapeTechnologyIntent,
    EscapeTechnologyKind,
    derive_escape_technology_decision,
)


def _trial(candidate_id: str, *, blocked: tuple[str, ...] = ()) -> EscapeGeometryTrial:
    required = ("U1.1", "U1.17")
    return EscapeGeometryTrial(
        candidate_id=candidate_id,
        source_board_sha256="a" * 64,
        required_pad_ids=required,
        legal_pad_ids=tuple(item for item in required if item not in blocked),
        blocked_pad_ids=blocked,
        observation_sha256="b" * 64,
    )


def _intent(*, qualified_evidence: bool) -> EscapeTechnologyIntent:
    return EscapeTechnologyIntent(
        candidate_id="fine-mechanical-via",
        kind=EscapeTechnologyKind.FINE_MECHANICAL_THROUGH_VIA,
        trace_width_mm=0.15,
        copper_clearance_mm=0.1,
        via_diameter_mm=0.45,
        via_drill_mm=0.2,
        supported_copper_layer_counts=(2, 4),
        manufacturer_process_id="fab-process-a" if qualified_evidence else None,
        fabrication_profile_fingerprint="c" * 64 if qualified_evidence else None,
        fabrication_evidence_sha256=("d" * 64,) if qualified_evidence else (),
        current_path_record_fingerprint="e" * 64 if qualified_evidence else None,
        current_path_authority="verified" if qualified_evidence else "unverified",
    )


def test_geometry_success_remains_blocked_without_process_and_current_evidence() -> None:
    decision = derive_escape_technology_decision(
        case_id="RC14",
        source_board_sha256="a" * 64,
        copper_layer_count=2,
        blocked_pad_ids=("U1.17", "U1.1"),
        intents=(_intent(qualified_evidence=False),),
        trials=(_trial("fine-mechanical-via"),),
    )
    assert decision.disposition == "geometry_option_found_evidence_required"
    assert not decision.qualified_candidate_ids
    assert decision.candidates[0].blockers == (
        "current_path_record_unbound",
        "current_path_unverified",
        "fabrication_evidence_unpinned",
        "fabrication_profile_unbound",
        "manufacturer_process_undeclared",
    )
    assert not decision.automatic_apply_authorized


def test_candidate_qualifies_only_when_geometry_process_and_current_all_close() -> None:
    decision = derive_escape_technology_decision(
        case_id="RC14",
        source_board_sha256="a" * 64,
        copper_layer_count=2,
        blocked_pad_ids=("U1.1", "U1.17"),
        intents=(_intent(qualified_evidence=True),),
        trials=(_trial("fine-mechanical-via"),),
    )
    assert decision.disposition == "qualified_candidate_available"
    assert decision.qualified_candidate_ids == ("fine-mechanical-via",)
    assert decision.candidates[0].qualified


def test_layer_count_and_geometry_fail_closed_independently() -> None:
    microvia = EscapeTechnologyIntent(
        candidate_id="laser-microvia",
        kind=EscapeTechnologyKind.MICROVIA,
        supported_copper_layer_counts=(4, 6),
    )
    decision = derive_escape_technology_decision(
        case_id="RC14",
        source_board_sha256="a" * 64,
        copper_layer_count=2,
        blocked_pad_ids=("U1.1",),
        intents=(microvia,),
        trials=(),
    )
    assert decision.disposition == "no_geometric_option_observed"
    assert "unsupported_on_declared_layer_count" in decision.candidates[0].blockers
    assert "geometry_unverified" in decision.candidates[0].blockers


def test_decision_is_bound_to_source_board_hash() -> None:
    trial = _trial("fine-mechanical-via")
    tampered_trial = trial.model_copy(
        update={"source_board_sha256": hashlib.sha256(b"x").hexdigest()}
    )
    decision = derive_escape_technology_decision(
        case_id="RC14",
        source_board_sha256="a" * 64,
        copper_layer_count=2,
        blocked_pad_ids=("U1.1", "U1.17"),
        intents=(_intent(qualified_evidence=True),),
        trials=(tampered_trial,),
    )
    assert "geometry_trial_board_hash_mismatch" in decision.candidates[0].blockers

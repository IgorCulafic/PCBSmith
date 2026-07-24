from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.prompt_examiner import (
    AnchorKind,
    ConflictConsequence,
    ContextPopulationInput,
    ExaminedClaim,
    PromptIssue,
    PromptResolution,
    SourceSpan,
    TypedSpatialAnchor,
    examine_prompt,
    populate_project_context,
)
from pcbsmith.workflow_authority import (
    ALL_PROJECT_CONTEXT_CATEGORIES,
    ProjectContextCategory,
    ProjectContextStatus,
)


def _span(text: str, exact: str, span_id: str = "span.1") -> SourceSpan:
    start = text.index(exact)
    return SourceSpan(
        span_id=span_id,
        start=start,
        end=start + len(exact),
        exact_text=exact,
    )


def test_explicit_claim_and_typed_edge_anchor_replay_against_prompt() -> None:
    text = "Place USB-C on the top edge, centered horizontally."
    span = _span(text, "top edge, centered horizontally")
    examination = examine_prompt(
        project_id="macro-pad",
        original_text=text,
        spans=(span,),
        claims=(
            ExaminedClaim(
                claim_id="usb.location",
                field_path="placements.usb",
                value="top_edge_center",
                resolution=PromptResolution.EXPLICIT,
                source_span_ids=(span.span_id,),
            ),
        ),
        anchors=(
            TypedSpatialAnchor(
                anchor_id="usb.top-edge",
                kind=AnchorKind.EDGE_OFFSET,
                subject_ids=("J1",),
                reference_id="board.outline",
                value_mm=0.0,
                edge="top",
                source_span_ids=(span.span_id,),
            ),
            TypedSpatialAnchor(
                anchor_id="usb.center-x",
                kind=AnchorKind.CENTER,
                subject_ids=("J1",),
                reference_id="board.outline",
                axis="x",
                source_span_ids=(span.span_id,),
            ),
        ),
    )

    assert examination.outcome == "ready_for_concept"
    assert tuple(item.anchor_id for item in examination.anchors) == (
        "usb.center-x",
        "usb.top-edge",
    )


def test_span_tampering_is_rejected_instead_of_inventing_source_support() -> None:
    text = "Board width is 100 mm."
    span = _span(text, "100 mm")
    examination = examine_prompt(
        project_id="board",
        original_text=text,
        spans=(span,),
        claims=(
            ExaminedClaim(
                claim_id="board.width",
                field_path="mechanical.width_mm",
                value=100,
                unit="mm",
                resolution=PromptResolution.EXPLICIT,
                source_span_ids=(span.span_id,),
            ),
        ),
    )
    payload = examination.model_dump(mode="python")
    payload["spans"][0]["exact_text"] = "120 mm"

    with pytest.raises(ValidationError, match="does not replay"):
        type(examination)(**payload)


def test_unknown_claim_cannot_carry_a_guessed_value() -> None:
    with pytest.raises(ValidationError, match="cannot invent"):
        ExaminedClaim(
            claim_id="stackup.copper",
            field_path="fabrication.copper_weight",
            value="1 oz",
            resolution=PromptResolution.UNKNOWN,
            rationale="The prompt does not specify copper weight.",
        )


def test_hard_conflict_requires_two_spirit_preserving_alternatives() -> None:
    with pytest.raises(ValidationError, match="at least two"):
        PromptIssue(
            issue_id="mechanical.conflict",
            severity="error",
            message="The fixed footprints exceed the board width.",
            claim_ids=("board.width",),
            hard_conflict=True,
            consequences=(
                ConflictConsequence(
                    consequence_id="consequence.fit",
                    domain="geometry",
                    affected_claim_ids=("board.width",),
                    effect="The required placement cannot be contained.",
                ),
            ),
            spirit_preserving_alternatives=("Increase board width.",),
        )


def test_hard_conflict_blocks_examination_and_retains_alternatives() -> None:
    text = "Keep the board under 40 mm wide and use four 19 mm switches."
    width = _span(text, "under 40 mm wide", "span.width")
    switches = _span(text, "four 19 mm switches", "span.switches")
    claims = (
        ExaminedClaim(
            claim_id="board.width",
            field_path="mechanical.width_mm",
            value=40,
            unit="mm",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(width.span_id,),
        ),
        ExaminedClaim(
            claim_id="switch.array",
            field_path="components.switches",
            value="4x19mm",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(switches.span_id,),
        ),
    )
    examination = examine_prompt(
        project_id="conflict",
        original_text=text,
        spans=(width, switches),
        claims=claims,
        issues=(
            PromptIssue(
                issue_id="mechanical.capacity",
                severity="error",
                message="The required switch row cannot fit.",
                claim_ids=("board.width", "switch.array"),
                hard_conflict=True,
                consequences=(
                    ConflictConsequence(
                        consequence_id="consequence.switch-fit",
                        domain="geometry",
                        affected_claim_ids=("board.width", "switch.array"),
                        effect="At least one switch courtyard exceeds the board.",
                    ),
                ),
                spirit_preserving_alternatives=(
                    "Increase the board width while preserving the switch count.",
                    "Use a two-row arrangement while preserving all four switches.",
                ),
            ),
        ),
    )

    assert examination.outcome == "blocked"


def test_context_population_makes_every_absent_axis_explicitly_unresolved() -> None:
    text = "Use USB-C."
    span = _span(text, "USB-C")
    examination = examine_prompt(
        project_id="context-board",
        original_text=text,
        spans=(span,),
        claims=(
            ExaminedClaim(
                claim_id="interface.usb",
                field_path="interfaces.usb",
                value="USB-C",
                resolution=PromptResolution.EXPLICIT,
                source_span_ids=(span.span_id,),
            ),
        ),
    )
    context = populate_project_context(
        examination=examination,
        generation_sha256="3" * 64,
        inputs=(
            ContextPopulationInput(
                category=ProjectContextCategory.INTERFACES,
                payload_sha256="4" * 64,
                source_binding_ids=("span.1",),
                rationale="Explicit USB interface.",
            ),
        ),
    )

    assert len(context.records) == len(ALL_PROJECT_CONTEXT_CATEGORIES)
    assert (
        context.record(ProjectContextCategory.INTERFACES).status
        is ProjectContextStatus.RESOLVED
    )
    assert (
        context.record(ProjectContextCategory.FABRICATOR).status
        is ProjectContextStatus.UNRESOLVED
    )

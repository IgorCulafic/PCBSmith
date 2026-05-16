from __future__ import annotations

from pcbsmith.services.board_feature_intent import (
    board_feature_planner_rule_notes,
    board_feature_tool_contract,
    classify_board_feature_request,
)


def test_classify_logo_placement_as_silkscreen_artwork() -> None:
    intent = classify_board_feature_request(
        "Add this logo in the bottom right corner of the board."
    )

    assert intent.kind == "silkscreen_artwork"
    assert intent.target_layers == ("F.SilkS", "B.SilkS")
    assert intent.allowed_now is True
    assert "silkscreen" in intent.reason


def test_classify_shaped_board_as_edge_cuts_geometry() -> None:
    intent = classify_board_feature_request(
        "Make the PCB shaped like this logo with a USB edge connector."
    )

    assert intent.kind == "board_outline_geometry"
    assert intent.target_layers == ("Edge.Cuts",)
    assert intent.allowed_now is False
    assert "Edge.Cuts" in intent.reason


def test_classify_mixed_artwork_and_shape_as_clarification() -> None:
    intent = classify_board_feature_request(
        "Print the logo on the PCB and make the board shaped like the logo."
    )

    assert intent.kind == "needs_clarification"
    assert intent.target_layers == ("F.SilkS", "B.SilkS", "Edge.Cuts")
    assert intent.allowed_now is False
    assert "separate features" in intent.reason


def test_board_feature_contract_separates_silkscreen_from_outline() -> None:
    contract = board_feature_tool_contract()

    assert contract["schema"] == "pcbsmith-board-feature-intent-v1"
    assert contract["layer_rules"] == {
        "silkscreen_artwork": ["F.SilkS", "B.SilkS"],
        "board_outline_geometry": ["Edge.Cuts"],
    }
    assert (
        "Do not use silkscreen commands to change the physical board outline."
        in contract["instructions"]
    )


def test_board_feature_planner_notes_are_ai_facing() -> None:
    notes = board_feature_planner_rule_notes()

    assert "silkscreen artwork targets F.SilkS/B.SilkS" in notes[0]
    assert "board outlines and cutouts target Edge.Cuts" in notes[1]

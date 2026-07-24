from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BoardFeatureKind = Literal[
    "silkscreen_artwork",
    "board_outline_geometry",
    "needs_clarification",
]


@dataclass(frozen=True)
class BoardFeatureIntent:
    kind: BoardFeatureKind
    target_layers: tuple[str, ...]
    allowed_now: bool
    reason: str
    next_step: str


_SILKSCREEN_TERMS = (
    "silkscreen",
    "silk screen",
    "print",
    "printed",
    "label",
    "text",
    "logo on",
    "logo in",
    "logo at",
    "qr",
    "artwork",
)
_OUTLINE_TERMS = (
    "board shape",
    "board outline",
    "shape of",
    "shaped like",
    "edge cuts",
    "edge.cuts",
    "cutout",
    "cut out",
    "notch",
    "slot",
    "usb port",
    "usb edge",
    "card edge",
    "outline of",
)


def classify_board_feature_request(request: str) -> BoardFeatureIntent:
    text = request.lower()
    wants_silkscreen = any(term in text for term in _SILKSCREEN_TERMS)
    wants_outline = any(term in text for term in _OUTLINE_TERMS)

    if wants_silkscreen and wants_outline:
        return BoardFeatureIntent(
            kind="needs_clarification",
            target_layers=("F.SilkS", "B.SilkS", "Edge.Cuts"),
            allowed_now=False,
            reason=(
                "The request mentions both printed artwork and physical board shape "
                "geometry, which must be handled as separate features."
            ),
            next_step=(
                "Ask the user whether the artwork should be printed on silkscreen, "
                "used as the physical board outline, or both as separate operations."
            ),
        )

    if wants_outline:
        return BoardFeatureIntent(
            kind="board_outline_geometry",
            target_layers=("Edge.Cuts",),
            allowed_now=False,
            reason="Physical board shapes, cutouts, notches, and edge connectors target Edge.Cuts.",
            next_step=(
                "Plan a board-outline operation with closed geometry, scale, edge clearance, "
                "and fabrication-profile checks before applying it."
            ),
        )

    if wants_silkscreen:
        return BoardFeatureIntent(
            kind="silkscreen_artwork",
            target_layers=("F.SilkS", "B.SilkS"),
            allowed_now=True,
            reason="Logos, text, labels, QR codes, and printed notes target silkscreen layers.",
            next_step=(
                "Use silkscreen text/artwork operations and check pad clearance, edge clearance, "
                "readable size, and overlap before approval."
            ),
        )

    return BoardFeatureIntent(
        kind="needs_clarification",
        target_layers=("F.SilkS", "B.SilkS", "Edge.Cuts"),
        allowed_now=False,
        reason="The request does not clearly say whether it is artwork or physical board geometry.",
        next_step=(
            "Ask one clarification question before generating board artwork "
            "or outline geometry."
        ),
    )


def board_feature_tool_contract() -> dict[str, object]:
    return {
        "schema": "pcbsmith-board-feature-intent-v1",
        "feature_kinds": [
            "silkscreen_artwork",
            "board_outline_geometry",
            "needs_clarification",
        ],
        "layer_rules": {
            "silkscreen_artwork": ["F.SilkS", "B.SilkS"],
            "board_outline_geometry": ["Edge.Cuts"],
        },
        "instructions": [
            "Treat logos, text, QR codes, labels, and printed artwork as silkscreen by default.",
            "Treat shaped boards, cutouts, notches, USB edges, and card-edge "
            "geometry as Edge.Cuts.",
            "When a request asks for both artwork and physical shape, split it "
            "into separate operations.",
            "Do not use silkscreen commands to change the physical board outline.",
        ],
    }


def board_feature_planner_rule_notes() -> list[str]:
    return [
        "Classify board artwork requests before planning: silkscreen artwork "
        "targets F.SilkS/B.SilkS.",
        "Classify physical shape requests separately: board outlines and cutouts target Edge.Cuts.",
        "If a request mixes silkscreen artwork and board shape, split it or ask "
        "a clarification question.",
    ]


__all__ = [
    "BoardFeatureIntent",
    "BoardFeatureKind",
    "board_feature_planner_rule_notes",
    "board_feature_tool_contract",
    "classify_board_feature_request",
]

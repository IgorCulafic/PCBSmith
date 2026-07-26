from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET

from pcbsmith.kicad.concept_review import (
    ConceptItem,
    examine_concept,
    write_concept_review_package,
)


def test_concept_examiner_distinguishes_conflict_and_engineering_selection() -> None:
    review = examine_concept(
        "fixture",
        ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)),
        (
            ConceptItem(
                item_id="required-hole",
                label="H1",
                side="both",
                kind="mounting_hole",
                anchor_mm=(0.5, 0.5),
                diameter_mm=2.0,
                containment="shape",
                requirement_resolution="explicit",
            ),
            ConceptItem(
                item_id="alternative-hole",
                label="H1 alt",
                side="both",
                kind="mounting_hole",
                anchor_mm=(3.0, 3.0),
                diameter_mm=2.0,
                containment="shape",
                requirement_resolution="engineering",
            ),
        ),
    )

    assert review.outcome == "blocked"
    assert tuple(item.status for item in review.items) == (
        "conflict",
        "engineering_selection",
    )
    assert review.items[0].minimum_edge_clearance_mm == -0.5


def test_concept_package_is_deterministic(tmp_path: Path) -> None:
    review = examine_concept(
        "fixture",
        ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)),
        (
            ConceptItem(
                item_id="art",
                label="art",
                side="front",
                kind="rectangle",
                anchor_mm=(10.0, 5.0),
                size_mm=(2.0, 2.0),
                containment="shape",
                requirement_resolution="explicit",
            ),
        ),
    )
    write_concept_review_package(review, tmp_path)
    first = hashlib.sha256((tmp_path / "engineering-overlay-front.png").read_bytes()).hexdigest()
    write_concept_review_package(review, tmp_path)
    second = hashlib.sha256((tmp_path / "engineering-overlay-front.png").read_bytes()).hexdigest()

    assert first == second


def test_concept_markdown_uses_item_id_when_overlay_label_is_hidden(tmp_path: Path) -> None:
    review = examine_concept(
        "fixture",
        ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)),
        (
            ConceptItem(
                item_id="hidden-detail",
                label="",
                side="front",
                kind="rectangle",
                anchor_mm=(10.0, 5.0),
                size_mm=(2.0, 2.0),
                containment="shape",
                requirement_resolution="engineering",
            ),
        ),
    )

    write_concept_review_package(review, tmp_path)

    assert "| hidden-detail | front |" in (tmp_path / "concept-review.md").read_text(
        encoding="utf-8"
    )


def test_concept_overlay_footer_clears_external_access_envelopes(
    tmp_path: Path,
) -> None:
    review = examine_concept(
        "fixture",
        ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)),
        (
            ConceptItem(
                item_id="card-access",
                label="card access",
                side="front",
                kind="aperture",
                anchor_mm=(10.0, 14.0),
                size_mm=(6.0, 8.0),
                containment="none",
                requirement_resolution="explicit",
            ),
        ),
    )

    write_concept_review_package(review, tmp_path)

    root = ET.fromstring(
        (tmp_path / "engineering-overlay-front.svg").read_text(encoding="utf-8")
    )
    title = next(
        element
        for element in root
        if element.tag.endswith("text") and element.text == "fixture | FRONT | needs_user_decision"
    )
    assert float(title.attrib["y"]) > 18.0

"""Build a retained R5 measured-placement corpus from serialized authorities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TypedDict, cast

from pcbsmith.kicad.placement_measured_corpus import (
    run_measured_shaped_placement_corpus,
)
from pcbsmith.placement_serialization_ir import PlacementSerializationAuthority


class CatalogEntry(TypedDict):
    case_id: str
    authority: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalog")
    parser.add_argument("output")
    parser.add_argument("--work-root", required=True)
    args = parser.parse_args()

    catalog_path = Path(args.catalog).resolve()
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("placement corpus catalog must be a list")
    entries = cast(list[CatalogEntry], raw)
    cases: list[tuple[str, PlacementSerializationAuthority]] = []
    for entry in entries:
        if set(entry) != {"case_id", "authority"}:
            raise ValueError(
                "each placement corpus entry requires case_id and authority"
            )
        authority_path = (catalog_path.parent / entry["authority"]).resolve()
        cases.append(
            (
                entry["case_id"],
                PlacementSerializationAuthority.model_validate_json(
                    authority_path.read_text(encoding="utf-8")
                ),
            )
        )

    corpus = run_measured_shaped_placement_corpus(
        cases,
        Path(args.work_root),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(corpus.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

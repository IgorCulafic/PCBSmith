"""Read-only readiness preparation; never grants board/review acceptance.

Reuses existing model and pin-evidence owners. Historical component decisions are
not copied into the fresh request, even when electrical intent is unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pcbsmith.evidence.component_pin_evidence import ComponentPinEvidence
from pcbsmith.kicad.board import parse_board_netlist
from pcbsmith.kicad.board_serialization import canonical_board_netlist_snapshot_json
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    preflight_board_models,
)
from pcbsmith.kicad.project_dependencies import native_project_hashes
from pcbsmith.production_routing import _pin_nets


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def electrical_intent(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Only schematic UUID paths are excluded; values, fields and every net remain."""
    return {
        "components": [
            {k: v for k, v in component.items() if k != "uuid_path"}
            for component in snapshot["components"]
        ],
        "nets": snapshot["nets"],
    }


def prepare_readiness_preflight(
    *,
    board: Path,
    netlist_file: Path,
    prior_component_input: Path,
    registry_file: Path,
    requirements_file: Path,
) -> dict[str, Any]:
    before = native_project_hashes(board)
    sources = (netlist_file, prior_component_input, registry_file, requirements_file)
    input_hashes = {str(path.resolve()): sha(path) for path in sources}
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    snapshot_text = canonical_board_netlist_snapshot_json(netlist)
    snapshot = json.loads(snapshot_text)
    expected_nets = {}
    for net in netlist.nets:
        for terminal in net.nodes:
            if terminal in expected_nets:
                raise ValueError("duplicate netlist terminal")
            expected_nets[terminal] = net.name
    if len({c.reference for c in netlist.components}) != len(netlist.components):
        raise ValueError("duplicate netlist component")
    if _pin_nets(board) != expected_nets:
        raise ValueError("native board and supplied netlist pin connectivity differ")
    footprints = _children(parse_sexpr(board.read_text(encoding="utf-8")), "footprint")
    native_parts = {}
    for footprint in footprints:
        props = {_atom(n[1]): _atom(n[2]) for n in _children(footprint, "property")}
        ref = props["Reference"]
        if ref in native_parts:
            raise ValueError("duplicate native reference")
        native_parts[ref] = (props.get("Value", ""), _atom(footprint[1]), props.get("MPN"))
    for component in netlist.components:
        value, footprint_name, mpn = native_parts.get(component.reference, (None, None, None))
        if (value, footprint_name) != (component.value, component.footprint):
            raise ValueError("native board and netlist component identity differ")
        if mpn is not None and mpn != dict(component.fields).get("MPN"):
            raise ValueError("native board and netlist part number differ")
    if set(native_parts) != {c.reference for c in netlist.components}:
        raise ValueError("native board and netlist reference coverage differ")

    previous = json.loads(prior_component_input.read_text(encoding="utf-8"))
    prior_snapshot = json.loads(previous["board_netlist_snapshot_json"])
    same_intent = electrical_intent(snapshot) == electrical_intent(prior_snapshot)
    registry = tuple(
        ModelRegistryEntry.model_validate(x)
        for x in json.loads(registry_file.read_text(encoding="utf-8"))
    )
    if len({x.raw_path for x in registry}) != len(registry):
        raise ValueError("ambiguous duplicate model registry entries")
    requirements = tuple(
        ModelRequirement.model_validate(x)
        for x in json.loads(requirements_file.read_text(encoding="utf-8"))
    )
    if {r.reference for r in requirements} != set(native_parts) or len(requirements) != len(
        native_parts
    ):
        raise ValueError("model requirements must cover every populated reference exactly once")
    models = preflight_board_models(board, registry=registry, requirements=requirements)
    gaps = [
        "Fresh component review decisions are required.",
        "Exact-board visual subject crops and placement publication remain required.",
    ]
    pins = {}
    if same_intent:
        for reference, value in previous.get("pin_evidence_by_reference", {}).items():
            evidence = ComponentPinEvidence.model_validate(value)
            source = Path(evidence.source_local_path)
            if not source.is_file() or sha(source) != evidence.source_sha256:
                gaps.append(f"{reference}: missing or changed pinned datasheet source")
                continue
            matching_component = next(
                (c for c in netlist.components if c.reference == reference), None
            )
            if (
                matching_component is None
                or dict(matching_component.fields).get("MPN") != evidence.part_number
            ):
                gaps.append(f"{reference}: pin evidence part number differs")
                continue
            input_hashes[str(source.resolve())] = evidence.source_sha256
            pins[reference] = value
    else:
        gaps.append("Electrical intent differs; historical pin evidence needs separate review.")
    required_ics = sorted(c.reference for c in netlist.components if c.reference.startswith("U"))
    missing = sorted(set(required_ics) - set(pins))
    if missing:
        gaps.append("Missing reusable IC pin evidence: " + ", ".join(missing))
    if models.status != "passed":
        gaps.extend(models.findings)
    if native_project_hashes(board) != before:
        raise ValueError("native inputs changed during readiness preflight")
    if any(sha(Path(path)) != digest for path, digest in input_hashes.items()):
        raise ValueError("source evidence changed during readiness preflight")
    return {
        "report": {
            "schema_id": "pcbsmith-readiness-preflight-v1",
            "status": "review_required",
            "production_accepted": False,
            "native_inputs": before,
            "source_inputs": input_hashes,
            "electrical_intent_matches_prior": same_intent,
            "ignored_comparison_fields": ["components.uuid_path"],
            "reusable_pin_evidence": sorted(pins),
            "model_preflight_status": models.status,
            "proxy_references": sorted(
                m.reference for m in models.models if m.classification == "proxy"
            ),
            "remaining_gaps": gaps,
            "limitations": (
                "Proxy resolution and registered transforms are not physical "
                "package qualification. Connectivity equality is not fresh ERC/DRC "
                "or schematic-source parity."
            ),
        },
        "model-preflight": models.model_dump(mode="json"),
        "component-review-input": {
            "project_id": board.stem,
            "board_revision": sha(board),
            "board_netlist_snapshot_json": snapshot_text,
            "pin_evidence_by_reference": pins,
            "results_by_obligation": {},
            "max_attempts": 1,
            "evidence_query_budget_per_obligation": 4,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "board",
        "netlist-file",
        "prior-component-input",
        "registry-file",
        "requirements-file",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; preserve the previous preflight")
    if args.output.resolve().is_relative_to(args.board.parent.resolve()):
        parser.error("preflight output must be outside the native project")
    result = prepare_readiness_preflight(
        board=args.board,
        netlist_file=args.netlist_file,
        prior_component_input=args.prior_component_input,
        registry_file=args.registry_file,
        requirements_file=args.requirements_file,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    for name, payload in result.items():
        (args.output / (name + ".json")).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(result["report"], indent=2))
    return 0  # Preparation completed; report remains review_required, never approval.


if __name__ == "__main__":
    raise SystemExit(main())

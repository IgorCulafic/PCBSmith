"""Typed, fail-closed reference-continuity geometry evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _sha256(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class ReferenceContinuityContext(SemanticIrModel):
    """Exact files that a current geometric reference observation must cover."""

    board_sha256: str
    native_inputs_sha256: str
    stackup_sha256: str
    policy_sha256: str

    @model_validator(mode="after")
    def hashes_are_valid(self) -> Self:
        for name in type(self).model_fields:
            _sha256(getattr(self, name), name)
        return self


def reference_continuity_context(board: Path, policy: Path) -> ReferenceContinuityContext:
    from pcbsmith.kicad.library import _children, parse_sexpr, serialize_sexpr
    from pcbsmith.manufacturing_lineage import native_input_hashes

    if not board.with_suffix(".kicad_pro").is_file():
        raise ValueError("reference continuity requires retained native project rules")
    raw = board.read_bytes()
    tree = parse_sexpr(raw.decode("utf-8"))
    layers = _children(tree, "layers")
    if len(layers) != 1:
        raise ValueError("reference continuity requires one native layer table")
    stackup = tuple(s for setup in _children(tree, "setup") for s in _children(setup, "stackup"))
    return ReferenceContinuityContext(
        board_sha256=hashlib.sha256(raw).hexdigest(),
        native_inputs_sha256=_fingerprint(native_input_hashes(board)),
        stackup_sha256=_fingerprint(
            [serialize_sexpr(layers[0]), *(serialize_sexpr(s) for s in stackup)]
        ),
        policy_sha256=hashlib.sha256(policy.read_bytes()).hexdigest(),
    )


class ReferenceContinuityEvidence(SemanticIrModel):
    """Exact within a deliberately narrow geometric model.

    The model proves complete centerline coverage of straight signal segments by
    the union of filled reference-net zone contours on the opposite copper layer.
    It does not prove conductor-width support, impedance, return-current density,
    EMC, signal integrity, or thermal adequacy.
    """

    schema_id: Literal["pcbsmith-reference-continuity-evidence"] = (
        "pcbsmith-reference-continuity-evidence"
    )
    schema_version: Literal[1] = 1
    authority: Literal[
        "exact-straight-centerline-geometric-v1", "native-adjacent-reference-geometric-v2"
    ]
    reference_net_names: tuple[str, ...]
    copper_layer_count: int = Field(ge=1)
    signal_segment_count: int = Field(ge=0)
    exact_supported_segment_count: int = Field(ge=0)
    exact_unsupported_segment_count: int = Field(ge=0)
    unsupported_geometry_segment_count: int = Field(ge=0)
    signal_transition_count: int = Field(ge=0)
    transition_without_nearby_reference_via_count: int = Field(ge=0)
    maximum_transition_stitch_distance_mm: float = Field(gt=0)
    exact_pass_authorized: bool
    automatic_multilayer_pass_prohibited: bool = True
    plane_evidence_fingerprint: str | None = Field(default=None, exclude_if=lambda v: v is None)
    layer_reference_roles: dict[str, tuple[str, str]] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    allowed_transition_void_half_size_mm: float | None = Field(
        default=None, gt=0, exclude_if=lambda v: v is None
    )
    disposition: Literal[
        "exact_geometric_continuity_observed",
        "exact_geometric_discontinuities_observed",
        "unsupported_stackup_unverified",
        "reference_net_undeclared_unverified",
        "unsupported_track_geometry_unverified",
    ]
    findings: tuple[dict[str, object], ...]
    scope: str
    evidence_fingerprint: str
    context: ReferenceContinuityContext | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha256(self.evidence_fingerprint, "evidence_fingerprint")
        references = tuple(sorted(self.reference_net_names))
        if len(references) != len(set(references)):
            raise ValueError("reference-net identities must be unique")
        if (
            self.exact_supported_segment_count
            + self.exact_unsupported_segment_count
            + self.unsupported_geometry_segment_count
            != self.signal_segment_count
        ):
            raise ValueError("reference-continuity segment accounting is inconsistent")
        native_multilayer = self.authority == "native-adjacent-reference-geometric-v2"
        if native_multilayer:
            if (
                self.copper_layer_count != 4
                or self.context is None
                or self.plane_evidence_fingerprint is None
                or self.automatic_multilayer_pass_prohibited
                or self.layer_reference_roles is None
                or set(self.layer_reference_roles) != {"F.Cu", "B.Cu"}
                or self.layer_reference_roles["F.Cu"][0] != "In1.Cu"
                or self.layer_reference_roles["B.Cu"][0] != "In2.Cu"
                or self.layer_reference_roles["F.Cu"][1] != self.layer_reference_roles["B.Cu"][1]
                or set(r[1] for r in self.layer_reference_roles.values()) != set(references)
            ):
                raise ValueError(
                    "multilayer reference evidence lacks exact adjacent plane authority"
                )
            _sha256(self.plane_evidence_fingerprint, "plane_evidence_fingerprint")
        elif (
            not self.automatic_multilayer_pass_prohibited
            or self.plane_evidence_fingerprint is not None
            or self.layer_reference_roles is not None
            or self.allowed_transition_void_half_size_mm is not None
        ):
            raise ValueError("legacy reference evidence cannot claim multilayer plane authority")
        expected_pass = (
            (self.copper_layer_count == 2 or native_multilayer)
            and bool(references)
            and self.unsupported_geometry_segment_count == 0
            and self.exact_unsupported_segment_count == 0
            and self.transition_without_nearby_reference_via_count == 0
        )
        if self.exact_pass_authorized != expected_pass:
            raise ValueError("exact reference-continuity disposition is stale")
        if expected_pass and self.disposition != "exact_geometric_continuity_observed":
            raise ValueError("exact pass requires the exact continuity disposition")
        if not expected_pass and self.disposition == "exact_geometric_continuity_observed":
            raise ValueError("exact continuity disposition cannot hide blockers")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != _fingerprint(payload):
            raise ValueError("reference-continuity evidence fingerprint is stale")
        object.__setattr__(self, "reference_net_names", references)
        return self


def parse_reference_continuity(
    observation: dict[str, object],
) -> ReferenceContinuityEvidence:
    raw = observation.get("reference_continuity")
    if not isinstance(raw, dict):
        raise TypeError("physical observation lacks reference_continuity")
    return ReferenceContinuityEvidence.model_validate(raw)


def observe_reference_continuity(
    board: Path,
    policy: Path,
    output_directory: Path,
    *,
    kicad_python: Path,
    timeout_seconds: float = 60,
) -> ReferenceContinuityEvidence:
    """Run fresh native observation and bind unchanged inputs, never a cached report."""
    if not 0 < timeout_seconds <= 180:
        raise ValueError("native reference observation needs a bounded 0–180 second timeout")
    board, policy = board.resolve(), policy.resolve()
    before = reference_continuity_context(board, policy)
    output_directory.mkdir(parents=True, exist_ok=False)
    raw_output = output_directory / "native-observation.json"
    bridge = Path(__file__).resolve().parents[3] / "tools/kicad_board_part4_bridge.py"
    command = tuple(map(str, (kicad_python, bridge, board, policy, raw_output)))
    result = subprocess.run(command, capture_output=True, timeout=timeout_seconds, check=False)
    (output_directory / "native.stdout.log").write_bytes(result.stdout)
    (output_directory / "native.stderr.log").write_bytes(result.stderr)
    (output_directory / "execution.json").write_text(
        json.dumps(
            {
                "command": command,
                "returncode": result.returncode,
                "context": before.model_dump(mode="json"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if reference_continuity_context(board, policy) != before:
        raise ValueError("native reference observation changed board, rules, stackup or policy")
    if result.returncode != 0 or not raw_output.is_file():
        raise RuntimeError("native reference observation failed; retained logs available")
    evidence = parse_reference_continuity(json.loads(raw_output.read_bytes()))
    from pcbsmith.kicad.copper_layers import saved_copper_layers
    from pcbsmith.kicad.library import parse_sexpr

    if evidence.copper_layer_count != len(
        saved_copper_layers(parse_sexpr(board.read_text(encoding="utf-8")))
    ):
        raise ValueError("native reference observation targets another copper stack")
    data = evidence.model_dump(mode="json", exclude={"evidence_fingerprint"})
    data["context"] = before.model_dump(mode="json")
    data["evidence_fingerprint"] = _fingerprint(data)
    bound = ReferenceContinuityEvidence.model_validate(data)
    (output_directory / "reference-continuity.json").write_text(
        bound.model_dump_json(indent=2), encoding="utf-8"
    )
    return bound

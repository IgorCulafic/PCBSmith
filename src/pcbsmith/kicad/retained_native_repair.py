"""Source-bound local repairs of completed retained routing; never runs an engine."""

import hashlib
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from pcbsmith.kicad.native_edits import NativeEdit, apply_native_edits
from pcbsmith.semantic_ir import SemanticIrModel


class RetainedNativeRepair(SemanticIrModel):
    predecessor_board_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rationale: str = Field(min_length=1)
    edits: tuple[NativeEdit, ...] = Field(min_length=1, max_length=8)
    maximum_displacement_mm: float = Field(gt=0, le=20)
    maximum_changed_objects: int = Field(gt=0, le=30)
    vector_file: str
    vector_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def limited(self) -> Self:
        if any(e.kind not in {"component", "reference", "segment"} for e in self.edits):
            raise ValueError(
                "retained repair supports component, reference and segment deltas only"
            )
        return self

    def check_vector(self) -> None:
        if hashlib.sha256(Path(self.vector_file).read_bytes()).hexdigest() != self.vector_sha256:
            raise ValueError("local repair vector changed")

    def apply(
        self, payload: bytes, *, source_only: bool = False, allowed_zone_ids: tuple[str, ...] = ()
    ) -> tuple[bytes, dict[str, object]]:
        self.check_vector()
        edits = tuple(e for e in self.edits if e.kind != "segment") if source_only else self.edits
        return apply_native_edits(
            payload,
            edits,
            maximum_displacement_mm=self.maximum_displacement_mm,
            maximum_changed_objects=self.maximum_changed_objects,
            allowed_zone_ids=allowed_zone_ids,
        )

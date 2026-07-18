"""Engine-neutral physical hole geometry.

Dimensions are nominal millimetres. The rotation and offset are expressed in
the owning item's local coordinate system, so an adapter can preserve source
geometry before board placement or layer-side transforms are applied.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HoleShape(StrEnum):
    ROUND = "round"
    OVAL = "oval"


class HolePlating(StrEnum):
    PLATED = "plated"
    NON_PLATED = "non_plated"


class HoleGeometry(BaseModel):
    """Nominal round-hole or rounded-slot geometry in an owner-local frame."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
    )

    shape: HoleShape
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    rotation_deg: float = 0.0
    plating: HolePlating
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0

    @model_validator(mode="after")
    def round_holes_have_equal_axes(self) -> Self:
        if self.shape is HoleShape.ROUND and not math.isclose(
            self.width_mm,
            self.height_mm,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("round holes require equal width and height")
        return self

    @property
    def minor_mm(self) -> float:
        return min(self.width_mm, self.height_mm)

    @property
    def major_mm(self) -> float:
        return max(self.width_mm, self.height_mm)

    @property
    def is_slot(self) -> bool:
        return self.shape is HoleShape.OVAL

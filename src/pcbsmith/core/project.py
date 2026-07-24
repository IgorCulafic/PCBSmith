from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pcbsmith.core.catalog import CatalogPreferences


class DesignRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_trace_width: int = 150_000
    min_clearance: int = 150_000
    min_drill: int = 300_000

    @field_validator("min_trace_width", "min_clearance", "min_drill")
    @classmethod
    def values_are_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Design rule values must be positive")
        return value


class LibraryRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: str | None = None


class Project(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    name: str
    schematics: tuple[str, ...] = Field(default_factory=lambda: ("schematics/main.sch.json",))
    boards: tuple[str, ...] = Field(default_factory=lambda: ("boards/main.brd.json",))
    libraries: tuple[LibraryRef, ...] = Field(default_factory=lambda: (LibraryRef(id="stdlib"),))
    design_rules: DesignRules = Field(default_factory=DesignRules)
    catalog_preferences: CatalogPreferences = Field(default_factory=CatalogPreferences)

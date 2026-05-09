from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_tag(value: str) -> str:
    normalized = re.sub(r"[\s_]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        raise ValueError("Tags must not be empty")
    return normalized


def _normalize_dedupe_tags(values: tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_tag(value)
        if normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return tuple(deduped)


def _normalize_catalog_id(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Catalog ids must not be empty")
    return normalized


def _normalize_dedupe_catalog_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_catalog_id(value)
        if normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return tuple(deduped)


def _normalize_namespaced_catalog_id(value: str) -> str:
    normalized = _normalize_catalog_id(value)
    if ":" not in normalized:
        raise ValueError("Catalog ids must be namespaced")
    namespace, local_id = normalized.split(":", 1)
    if not namespace or not local_id:
        raise ValueError("Catalog ids must be namespaced")
    return normalized


class SourceInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "pcbs"
    source_id: str | None = None
    license: str | None = None
    url: str | None = None


class ComponentFamily(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""


class ComponentVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    package: str | None = None
    mounting: Literal["smd", "through-hole", "virtual"] | None = None
    default_value: str | None = None


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    family: ComponentFamily
    variant: ComponentVariant
    symbol_id: str
    footprint_id: str | None = None
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    source: SourceInfo = Field(default_factory=SourceInfo)
    normal_user_visible: bool = True

    @field_validator("id")
    @classmethod
    def id_is_namespaced(cls, value: str) -> str:
        return _normalize_namespaced_catalog_id(value)

    @field_validator("tags", "aliases", "group_ids")
    @classmethod
    def normalize_tags_aliases_and_groups(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_dedupe_tags(values)

    @property
    def search_text(self) -> str:
        values = (
            self.family.name,
            self.variant.name,
            self.variant.package,
            *self.tags,
            *self.aliases,
        )
        return " ".join(value for value in values if value)


class CatalogGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""
    default_enabled: bool = False

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_tag(value)


class PreferredPartsProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled_group_ids: tuple[str, ...] = ()
    visible_entry_ids: tuple[str, ...] = ()
    hidden_entry_ids: tuple[str, ...] = ()

    @field_validator("enabled_group_ids")
    @classmethod
    def normalize_enabled_group_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_dedupe_tags(values)

    @field_validator("visible_entry_ids", "hidden_entry_ids")
    @classmethod
    def normalize_entry_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_dedupe_catalog_ids(values)


class CatalogPreferences(PreferredPartsProfile):
    pass


class CatalogSearchQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = ""
    tags: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    preferred_only: bool = False

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        if not value.strip():
            return ""
        return normalize_tag(value)

    @field_validator("tags", "group_ids")
    @classmethod
    def normalize_tags_and_groups(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_dedupe_tags(values)


class MissingPartRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_name: str
    reason: str
    requested_tags: tuple[str, ...] = ()
    user_visible: bool = True

    @field_validator("requested_tags")
    @classmethod
    def normalize_requested_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_dedupe_tags(values)


class DeveloperLibraryProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_name: str
    proposed_entry_id: str
    source: SourceInfo = Field(default_factory=SourceInfo)
    notes: str = ""
    status: Literal["draft", "reviewed", "accepted", "rejected"] = "draft"

    @field_validator("proposed_entry_id")
    @classmethod
    def proposed_entry_id_is_namespaced(cls, value: str) -> str:
        return _normalize_namespaced_catalog_id(value)

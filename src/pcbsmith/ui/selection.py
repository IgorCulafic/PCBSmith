from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SelectionKind = Literal["symbol", "wire", "label", "no_connect"]


@dataclass(frozen=True)
class SelectionKey:
    kind: SelectionKind
    key: str


def parse_index_key(selection: SelectionKey) -> int:
    try:
        index = int(selection.key)
    except ValueError as exc:
        raise ValueError(f"Invalid {selection.kind} key: {selection.key}") from exc
    if index < 0:
        raise ValueError(f"Invalid {selection.kind} key: {selection.key}")
    return index

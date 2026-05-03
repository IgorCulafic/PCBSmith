from __future__ import annotations

import re
from typing import NewType

ProjectId = NewType("ProjectId", str)
SchematicId = NewType("SchematicId", str)
BoardId = NewType("BoardId", str)
SymbolId = NewType("SymbolId", str)
FootprintId = NewType("FootprintId", str)
NetId = NewType("NetId", str)


def make_id(prefix: str, text: str) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise ValueError("Cannot create an id from empty text")
    return f"{prefix}:{slug}"

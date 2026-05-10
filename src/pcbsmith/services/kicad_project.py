from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

KICAD_FILE_VERSION = 20240108
KICAD_SCHEMATIC_VERSION = 20240108
GENERATOR = "PCBSmith"


class KiCadProjectSkeleton(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    project_name: str
    project_dir: Path
    project_file: Path
    schematic_file: Path
    board_file: Path


def create_kicad_project_skeleton(
    project_dir: Path,
    project_name: str,
    *,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> KiCadProjectSkeleton:
    safe_name = sanitize_kicad_project_name(project_name)
    if project_dir.exists() and any(project_dir.iterdir()):
        raise FileExistsError(f"Project target already exists: {project_dir}")

    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{safe_name}.kicad_pro"
    schematic_file = project_dir / f"{safe_name}.kicad_sch"
    board_file = project_dir / f"{safe_name}.kicad_pcb"

    root_uuid = uuid_factory()
    board_outline_uuid = uuid_factory()
    project_file.write_text(
        render_kicad_project_file(safe_name),
        encoding="utf-8",
    )
    schematic_file.write_text(
        render_kicad_schematic_file(root_uuid),
        encoding="utf-8",
    )
    board_file.write_text(
        render_kicad_board_file(board_outline_uuid),
        encoding="utf-8",
    )

    return KiCadProjectSkeleton(
        project_name=safe_name,
        project_dir=project_dir,
        project_file=project_file,
        schematic_file=schematic_file,
        board_file=board_file,
    )


def sanitize_kicad_project_name(project_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", project_name.strip())
    normalized = normalized.strip("._-")
    if not normalized:
        raise ValueError("Project name cannot be blank")
    return normalized


def render_kicad_project_file(project_name: str) -> str:
    project = {
        "meta": {
            "filename": f"{project_name}.kicad_pro",
            "version": 1,
        },
        "pcbsmith": {
            "generated_by": GENERATOR,
            "schema": "kicad-skeleton-v1",
        },
        "text_variables": {},
    }
    return json.dumps(project, indent=2, sort_keys=True) + "\n"


def render_kicad_schematic_file(
    root_uuid: UUID,
    schematic_body_items: Sequence[str] = (),
    lib_symbol_items: Sequence[str] = (),
) -> str:
    body = "\n\n".join(schematic_body_items)
    body_section = f"\n\n{body}" if body else ""
    lib_symbols = "\n\n".join(lib_symbol_items)
    lib_symbols_section = f"(lib_symbols\n{lib_symbols}\n  )" if lib_symbols else "(lib_symbols)"
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "{GENERATOR}")

  (uuid {root_uuid})

  (paper "A4")

  {lib_symbols_section}
{body_section}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def render_kicad_board_file(board_outline_uuid: UUID | None = None) -> str:
    board_outline_uuid = uuid4() if board_outline_uuid is None else board_outline_uuid
    return f"""(kicad_pcb
  (version {KICAD_FILE_VERSION})
  (generator "{GENERATOR}")

  (general
    (thickness 1.6)
  )

  (paper "A4")

  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user)
    (33 "F.Adhes" user)
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user)
    (37 "F.SilkS" user)
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (44 "Edge.Cuts" user)
  )

  (gr_rect
    (start 0 0)
    (end 100 80)
    (stroke (width 0.1) (type default))
    (fill none)
    (layer "Edge.Cuts")
    (uuid {board_outline_uuid})
  )
)
"""


__all__ = [
    "GENERATOR",
    "KICAD_FILE_VERSION",
    "KICAD_SCHEMATIC_VERSION",
    "KiCadProjectSkeleton",
    "create_kicad_project_skeleton",
    "render_kicad_board_file",
    "render_kicad_project_file",
    "render_kicad_schematic_file",
    "sanitize_kicad_project_name",
]

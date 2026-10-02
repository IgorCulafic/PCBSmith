"""Native format finalization of fresh working copies before evidence is bound."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from pcbsmith.kicad.cli import find_kicad_cli
from pcbsmith.kicad.library import _atom, _children, parse_sexpr


def upgrade_generated_native_file(path: Path, receipt: Path) -> None:
    """Let installed KiCad migrate a generated copy; never relabel its schema."""
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    kind = {".kicad_sch": "sch", ".kicad_pcb": "pcb"}.get(path.suffix)
    if kind is None:
        raise ValueError("Native format finalization supports boards and schematics")
    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI is required for native format finalization")
    before = path.read_bytes()

    def version(data: bytes) -> int:
        tree = parse_sexpr(data.decode("utf-8"))
        if _atom(tree[0]) != "kicad_" + ("sch" if kind == "sch" else "pcb"):
            raise ValueError("Native file type does not match its extension")
        return int(_atom(_children(tree, "version")[0][1]))

    old_version = version(before)
    command = [str(install.path), kind, "upgrade", str(path.resolve())]
    record: dict[str, object] = {
        "command": command,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "before_version": old_version,
        "status": "failed",
    }
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        if result.returncode:
            raise RuntimeError(f"KiCad {kind} format upgrade failed: {result.stderr}")
        after = path.read_bytes()
        new_version = version(after)
        if new_version < old_version:
            raise ValueError("Native format finalization unexpectedly downgraded the file")
        record.update(
            status="passed",
            after_version=new_version,
            after_sha256=hashlib.sha256(after).hexdigest(),
        )
    except Exception as exc:
        record["error"] = str(exc)
        raise
    finally:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

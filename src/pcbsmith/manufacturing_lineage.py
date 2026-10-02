"""Exact native export lineage and assembly-data checks.

Receipts prevent accidental substitution; they are local execution records, not
cryptographic attestations of an untrusted machine or physical qualification.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr
from pcbsmith.operations.file_transaction import atomic_write
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_input_hashes(board_file: Path) -> dict[str, str]:
    """The saved inputs used by the supported standalone KiCad exporters."""
    candidates = (
        board_file,
        board_file.with_suffix(".kicad_sch"),
        board_file.with_suffix(".kicad_pro"),
        board_file.with_suffix(".kicad_dru"),
        board_file.parent / "fp-lib-table",
        board_file.parent / "sym-lib-table",
    )
    if not board_file.is_file():
        raise ValueError("native export board is missing")
    return {path.name: file_sha256(path) for path in candidates if path.is_file()}


class ExportProcess(SemanticIrModel):
    command: tuple[str, ...] = Field(min_length=1)
    returncode: int
    stdout: str
    stderr: str


class ExportOutput(SemanticIrModel):
    role: str
    relative_path: str
    sha256: str

    @model_validator(mode="after")
    def safe_path(self) -> Self:
        path = PurePosixPath(self.relative_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or ":" in self.relative_path
            or "\\" in self.relative_path
            or path.as_posix() in {"", "."}
        ):
            raise ValueError("export output path is not relative")
        require_sha256(self.sha256, "output.sha256")
        return self


class ExportReceipt(SemanticIrModel):
    schema_id: Literal["pcbsmith-native-export-receipt-v1"] = "pcbsmith-native-export-receipt-v1"
    producer: Literal["kicad-cli.neutral", "interactive-html-bom"]
    tool_version: str
    board_sha256: str
    native_inputs: dict[str, str]
    configuration: dict[str, str]
    processes: tuple[ExportProcess, ...] = Field(min_length=1)
    outputs: tuple[ExportOutput, ...] = Field(min_length=1)
    receipt_fingerprint: str

    @model_validator(mode="after")
    def exact_success(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        for digest in self.native_inputs.values():
            require_sha256(digest, "native input")
        if not self.native_inputs or self.board_sha256 not in self.native_inputs.values():
            raise ValueError("export lacks its board input")
        if any(item.returncode != 0 for item in self.processes):
            raise ValueError("failed export cannot produce an accepted receipt")
        paths = tuple(item.relative_path for item in self.outputs)
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate export output paths")
        if self.producer == "kicad-cli.neutral":
            operations = tuple(
                item.command[3]
                for item in self.processes
                if len(item.command) > 3 and item.command[1:3] == ("pcb", "export")
            )
            if sorted(operations) != ["drill", "gerbers", "ipcd356", "pdf", "pdf", "pos"]:
                raise ValueError("neutral export receipt lacks the required native processes")
        if self.receipt_fingerprint != fingerprint(
            self.model_dump(mode="json", exclude={"receipt_fingerprint"})
        ):
            raise ValueError("export receipt fingerprint is stale")
        return self


def retain_export_receipt(
    *,
    path: Path,
    producer: Literal["kicad-cli.neutral", "interactive-html-bom"],
    board_file: Path,
    initial_inputs: dict[str, str],
    tool_version: str,
    configuration: dict[str, str],
    processes: Sequence[ExportProcess],
    sources: Mapping[str, tuple[Path, ...]],
) -> ExportReceipt:
    if native_input_hashes(board_file) != initial_inputs:
        raise ValueError("native inputs changed during export")
    root = path.parent.resolve()
    outputs = tuple(
        ExportOutput(
            role=role,
            relative_path=source.resolve().relative_to(root).as_posix(),
            sha256=file_sha256(source),
        )
        for role, files in sorted(sources.items())
        for source in sorted(files)
    )
    fields: dict[str, Any] = dict(
        producer=producer,
        tool_version=tool_version,
        board_sha256=file_sha256(board_file),
        native_inputs=initial_inputs,
        configuration=configuration,
        processes=tuple(processes),
        outputs=outputs,
    )
    provisional = ExportReceipt.model_construct(**fields, receipt_fingerprint="0" * 64)
    receipt = ExportReceipt(
        **fields,
        receipt_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"receipt_fingerprint"})
        ),
    )
    if path.exists():
        raise ValueError("export receipt already exists")
    atomic_write(path, (receipt.model_dump_json(indent=2) + "\n").encode())
    return receipt


def validate_export_receipt(
    *,
    path: Path,
    board_file: Path,
    producer: str,
    sources: Mapping[str, tuple[Path, ...]],
    configuration: Mapping[str, str],
) -> ExportReceipt:
    receipt = ExportReceipt.model_validate_json(path.read_bytes())
    if receipt.producer != producer:
        raise ValueError("wrong export producer")
    if receipt.board_sha256 != file_sha256(
        board_file
    ) or receipt.native_inputs != native_input_hashes(board_file):
        raise ValueError("export receipt targets different or changed native inputs")
    if any(receipt.configuration.get(key) != value for key, value in configuration.items()):
        raise ValueError("export receipt uses different configuration")
    root = path.parent.resolve()
    expected = sorted((item.role, item.relative_path, item.sha256) for item in receipt.outputs)
    observed = sorted(
        (role, source.resolve().relative_to(root).as_posix(), file_sha256(source))
        for role, files in sources.items()
        for source in files
    )
    if observed != expected:
        raise ValueError("manufacturing source set differs from retained export outputs")
    return receipt


def _atom(value: SExpr) -> str:
    if isinstance(value, QuotedString):
        return value.value
    if isinstance(value, str):
        return value
    raise ValueError("expected native atom")


def _children(node: SList, name: str) -> tuple[SList, ...]:
    return tuple(child for child in node if isinstance(child, list) and child and child[0] == name)


def _property(node: SList, name: str) -> str:
    for item in _children(node, "property"):
        if len(item) >= 3 and _atom(item[1]) == name:
            return _atom(item[2])
    for item in _children(node, "fp_text"):
        if len(item) >= 3 and _atom(item[1]) == name.lower():
            return _atom(item[2])
    raise ValueError(f"footprint lacks {name}")


@dataclass(frozen=True)
class AssemblyRow:
    reference: str
    value: str
    footprint: str
    x_mm: float
    y_mm: float
    rotation: float
    side: str
    in_bom: bool
    in_placement: bool


def saved_assembly_rows(board_file: Path) -> tuple[AssemblyRow, ...]:
    """Declared policy: one row per reference; omit DNP and explicit exclusions.

    BOM and position exclusions are independent. Native default position export
    includes through-hole parts and uses absolute X, negated Y, and saved angle.
    The policy never treats a TP/H reference prefix as an assembly exclusion.
    """
    return assembly_rows_from_text(board_file.read_text(encoding="utf-8"))


def assembly_rows_from_text(board_text: str) -> tuple[AssemblyRow, ...]:
    """Apply saved assembly inclusion policy to an exact native board payload."""
    root = parse_sexpr(board_text)
    if not root or root[0] != "kicad_pcb":
        raise ValueError("assembly source is not a KiCad board")
    rows = []
    for fp in _children(root, "footprint"):
        reference = _property(fp, "Reference")
        if not reference or reference.endswith("?"):
            raise ValueError("assembly source has an unannotated reference")
        at_nodes = _children(fp, "at")
        at = at_nodes[0] if at_nodes else ["at", "0", "0"]
        x, y = float(_atom(at[1])), float(_atom(at[2]))
        rotation = float(_atom(at[3])) if len(at) > 3 else 0.0
        if not all(math.isfinite(value) for value in (x, y, rotation)):
            raise ValueError("assembly source has nonfinite position")
        layers = _children(fp, "layer")
        layer = _atom(layers[0][1]) if layers else ""
        if layer not in {"F.Cu", "B.Cu"}:
            raise ValueError("assembly footprint is not on an external copper layer")
        attrs = {_atom(atom) for attr in _children(fp, "attr") for atom in attr[1:]}
        rows.append(
            AssemblyRow(
                reference=reference,
                value=_property(fp, "Value"),
                footprint=_atom(fp[1]),
                x_mm=x,
                y_mm=y,
                rotation=rotation,
                side="top" if layer == "F.Cu" else "bottom",
                in_bom=not ({"dnp", "exclude_from_bom"} & attrs),
                in_placement=not ({"dnp", "exclude_from_pos_files"} & attrs),
            )
        )
    if len({row.reference for row in rows}) != len(rows):
        raise ValueError("assembly source has duplicate references")
    return tuple(sorted(rows, key=lambda row: row.reference))


def _csv_rows(payload: bytes, required: set[str]) -> dict[str, dict[str, str]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    if not required <= set(fields) or len(fields) != len(set(fields)):
        raise ValueError("assembly CSV fields are missing or duplicated")
    rows: dict[str, dict[str, str]] = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("assembly CSV has an incomplete row")
        ref = row["Ref"]
        if not ref or ref in rows:
            raise ValueError("assembly CSV has empty or duplicate reference")
        if row.get("Qty", "1") != "1":
            raise ValueError("assembly CSV requires quantity one per physical reference")
        rows[ref] = row
    return rows


def validate_assembly_payloads(
    *,
    board_file: Path,
    bom_payload: bytes,
    placement_payload: bytes,
    stable_ids: Mapping[str, str],
) -> None:
    rows = saved_assembly_rows(board_file)
    bom = _csv_rows(bom_payload, {"Ref", "Value", "Footprint", "StableId"})
    placement = _csv_rows(
        placement_payload, {"Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side"}
    )
    if set(bom) != {row.reference for row in rows if row.in_bom}:
        raise ValueError("BOM reference coverage differs from populated board")
    if set(placement) != {row.reference for row in rows if row.in_placement}:
        raise ValueError("placement reference coverage differs from populated board")
    for row in rows:
        if row.in_bom:
            item = bom[row.reference]
            if (item["Value"], item["Footprint"], item["StableId"]) != (
                row.value,
                row.footprint,
                stable_ids[row.reference],
            ):
                raise ValueError(f"BOM identity/value/footprint mismatch: {row.reference}")
        if row.in_placement:
            item = placement[row.reference]
            if (item["Val"], item["Package"], item["Side"]) != (
                row.value,
                row.footprint.rsplit(":", 1)[-1],
                row.side,
            ):
                raise ValueError(f"placement identity/side mismatch: {row.reference}")
            x, y, angle = (float(item[key]) for key in ("PosX", "PosY", "Rot"))
            if (
                not all(math.isfinite(value) for value in (x, y, angle))
                or abs(x - row.x_mm) > 0.000001
                or abs(y + row.y_mm) > 0.000001
                or abs((angle - row.rotation + 180) % 360 - 180) > 0.000001
            ):
                raise ValueError(f"placement coordinates/rotation mismatch: {row.reference}")


def run_recorded_export(
    *,
    command: Sequence[str],
    processes: list[ExportProcess],
    log_file: Path,
    initial_inputs: dict[str, str],
    environment: Mapping[str, str] | None = None,
    timeout_seconds: float = 300,
) -> None:
    """Retain success and failure output before returning or raising."""
    import json
    import subprocess

    def as_text(value: str | bytes | None) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""

    failure: Exception | None = None
    try:
        result = subprocess.run(
            tuple(command),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=timeout_seconds,
        )
        process = ExportProcess(
            command=tuple(command),
            returncode=result.returncode,
            stdout=as_text(result.stdout),
            stderr=as_text(result.stderr),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        failure = exc
        process = ExportProcess(
            command=tuple(command),
            returncode=-1,
            stdout=as_text(getattr(exc, "stdout", None)),
            stderr=as_text(getattr(exc, "stderr", None)) + "\n" + str(exc),
        )
    processes.append(process)
    atomic_write(
        log_file,
        (
            json.dumps(
                {
                    "native_inputs": initial_inputs,
                    "processes": [item.model_dump(mode="json") for item in processes],
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    if process.returncode != 0:
        raise RuntimeError(f"native export failed; retained diagnostics: {log_file}") from failure


def validate_ibom_lineage(receipt: ExportReceipt, board_file: Path, html_file: Path) -> None:
    if (
        receipt.producer != "interactive-html-bom"
        or receipt.board_sha256 != file_sha256(board_file)
        or receipt.native_inputs != native_input_hashes(board_file)
        or len(receipt.outputs) != 1
        or receipt.outputs[0].role != "interactive_bom"
        or receipt.outputs[0].sha256 != file_sha256(html_file)
    ):
        raise ValueError("interactive BOM lacks exact current-board producer lineage")

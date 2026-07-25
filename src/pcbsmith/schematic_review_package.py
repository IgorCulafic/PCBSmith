"""Canonical connected-schematic review exports for Phase 17.

The package is generated from one exact KiCad root schematic.  Every page SVG
and PDF is exported through the same KiCad invocation family as the whole
project ERC and netlist, then bound to those electrical identities.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board import canonical_kicad_netlist_xml_text
from pcbsmith.kicad.cli import (
    KiCadInstall,
    KiCadProcessResult,
    find_kicad_cli,
    run_kicad_process,
)
from pcbsmith.kicad.validate import (
    canonical_kicad_erc_json_text,
    kicad_erc_findings_from_json_text,
)
from pcbsmith.routed_copper_graph_ir import (
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.semantic_ir import SemanticIrModel


class SchematicReviewPage(SemanticIrModel):
    schema_id: Literal["pcbsmith-schematic-review-page"] = "pcbsmith-schematic-review-page"
    schema_version: Literal[1] = 1
    page_number: int = Field(ge=1)
    page_role: Literal["root", "hierarchical_sheet"]
    svg_relative_path: str
    svg_sha256: str
    pdf_relative_path: str
    pdf_sha256: str

    @model_validator(mode="after")
    def page_is_canonical(self) -> Self:
        expected_role = "root" if self.page_number == 1 else "hierarchical_sheet"
        if self.page_role != expected_role:
            raise ValueError("schematic page role does not match its page number")
        for field_name in ("svg_relative_path", "pdf_relative_path"):
            _safe_relative_path(getattr(self, field_name))
        require_sha256(self.svg_sha256, "svg_sha256")
        require_sha256(self.pdf_sha256, "pdf_sha256")
        return self


class ConnectedSchematicReviewManifest(SemanticIrModel):
    schema_id: Literal["pcbsmith-connected-schematic-review"] = (
        "pcbsmith-connected-schematic-review"
    )
    schema_version: Literal[1] = 1
    project_id: str
    source_schematic: str
    source_schematic_sha256: str
    kicad_cli_version: str
    page_count: int = Field(ge=1)
    pages: tuple[SchematicReviewPage, ...]
    project_pdf_relative_path: str
    project_pdf_sha256: str
    erc_relative_path: str
    erc_sha256: str
    erc_canonical_sha256: str
    erc_findings: tuple[str, ...]
    netlist_relative_path: str
    netlist_sha256: str
    netlist_canonical_sha256: str
    ready_for_review: bool
    manifest_fingerprint: str

    @model_validator(mode="after")
    def manifest_is_replay_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_identity(self.source_schematic, "source_schematic")
        require_identity(self.kicad_cli_version, "kicad_cli_version")
        for field_name in (
            "source_schematic_sha256",
            "project_pdf_sha256",
            "erc_sha256",
            "erc_canonical_sha256",
            "netlist_sha256",
            "netlist_canonical_sha256",
            "manifest_fingerprint",
        ):
            require_sha256(getattr(self, field_name), field_name)
        for field_name in (
            "project_pdf_relative_path",
            "erc_relative_path",
            "netlist_relative_path",
        ):
            _safe_relative_path(getattr(self, field_name))
        pages = tuple(sorted(self.pages, key=lambda item: item.page_number))
        if tuple(item.page_number for item in pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("schematic review pages are incomplete or non-contiguous")
        paths = (
            self.project_pdf_relative_path,
            self.erc_relative_path,
            self.netlist_relative_path,
            *(item.svg_relative_path for item in pages),
            *(item.pdf_relative_path for item in pages),
        )
        if len(paths) != len(set(paths)):
            raise ValueError("schematic review artifact paths must be unique")
        if self.ready_for_review != (not self.erc_findings):
            raise ValueError("schematic review readiness is stale")
        object.__setattr__(self, "pages", pages)
        payload = self.model_dump(mode="json", exclude={"manifest_fingerprint"})
        if fingerprint(payload) != self.manifest_fingerprint:
            raise ValueError("schematic review manifest fingerprint is stale")
        return self


def generate_connected_schematic_review(
    *,
    project_id: str,
    schematic_file: Path,
    output_dir: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> ConnectedSchematicReviewManifest:
    """Export root/per-sheet views and bind them to ERC/netlist evidence.

    ``output_dir`` is published atomically and must not already exist.  Page
    count is discovered using KiCad's all-pages SVG export, but every retained
    SVG and PDF is then exported with an explicit page selector.
    """

    source = schematic_file.resolve()
    target = output_dir.resolve()
    if not source.is_file():
        raise ValueError(f"schematic file does not exist: {source}")
    if target.exists():
        raise ValueError(f"schematic review target already exists: {target}")
    install = finder()
    if install is None:
        raise ValueError("KiCad CLI is required for connected schematic review")
    target.parent.mkdir(parents=True, exist_ok=True)

    invoke = (lambda command: run_kicad_process(command)) if runner is None else runner
    version_result = invoke((str(install.path), "--version"))
    if version_result.returncode != 0:
        raise ValueError(f"KiCad version query failed: {_process_detail(version_result)}")
    version = (version_result.stdout.strip() or version_result.stderr.strip()).splitlines()[0]
    require_identity(version, "kicad_cli_version")

    with tempfile.TemporaryDirectory(prefix=".schematic-review-", dir=target.parent) as temporary:
        work = Path(temporary)
        discovery_dir = work / ".page-discovery"
        discovery_dir.mkdir()
        _run_required(
            invoke,
            (
                str(install.path),
                "sch",
                "export",
                "svg",
                "--output",
                str(discovery_dir),
                str(source),
            ),
            "all-pages SVG discovery",
        )
        discovered = tuple(sorted(discovery_dir.glob("*.svg")))
        if not discovered:
            raise ValueError("KiCad all-pages SVG export produced no schematic pages")

        erc_file = work / "electrical" / "erc.json"
        netlist_file = work / "electrical" / "netlist.xml"
        project_pdf = work / "project.pdf"
        erc_file.parent.mkdir(parents=True)
        _run_required(
            invoke,
            (
                str(install.path),
                "sch",
                "erc",
                "--format",
                "json",
                "--output",
                str(erc_file),
                str(source),
            ),
            "whole-project ERC",
            require_zero=False,
        )
        _require_output(erc_file, "whole-project ERC")
        _run_required(
            invoke,
            (
                str(install.path),
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadxml",
                "--output",
                str(netlist_file),
                str(source),
            ),
            "whole-project netlist",
        )
        _require_output(netlist_file, "whole-project netlist")
        _run_required(
            invoke,
            (
                str(install.path),
                "sch",
                "export",
                "pdf",
                "--exclude-pdf-metadata",
                "--output",
                str(project_pdf),
                str(source),
            ),
            "whole-project PDF",
        )
        _require_output(project_pdf, "whole-project PDF")

        pages: list[SchematicReviewPage] = []
        for page_number in range(1, len(discovered) + 1):
            page_dir = work / "pages" / f"{page_number:03d}"
            svg_dir = page_dir / ".svg-export"
            svg_dir.mkdir(parents=True)
            pdf_file = page_dir / "page.pdf"
            _run_required(
                invoke,
                (
                    str(install.path),
                    "sch",
                    "export",
                    "svg",
                    "--pages",
                    str(page_number),
                    "--output",
                    str(svg_dir),
                    str(source),
                ),
                f"schematic page {page_number} SVG",
            )
            svg_outputs = tuple(sorted(svg_dir.glob("*.svg")))
            if len(svg_outputs) != 1:
                raise ValueError(
                    f"schematic page {page_number} SVG export produced {len(svg_outputs)} files"
                )
            svg_file = page_dir / "page.svg"
            shutil.move(str(svg_outputs[0]), svg_file)
            shutil.rmtree(svg_dir)
            _run_required(
                invoke,
                (
                    str(install.path),
                    "sch",
                    "export",
                    "pdf",
                    "--exclude-pdf-metadata",
                    "--pages",
                    str(page_number),
                    "--output",
                    str(pdf_file),
                    str(source),
                ),
                f"schematic page {page_number} PDF",
            )
            _require_output(pdf_file, f"schematic page {page_number} PDF")
            pages.append(
                SchematicReviewPage(
                    page_number=page_number,
                    page_role=("root" if page_number == 1 else "hierarchical_sheet"),
                    svg_relative_path=svg_file.relative_to(work).as_posix(),
                    svg_sha256=_file_sha256(svg_file),
                    pdf_relative_path=pdf_file.relative_to(work).as_posix(),
                    pdf_sha256=_file_sha256(pdf_file),
                )
            )

        shutil.rmtree(discovery_dir)
        erc_text = erc_file.read_text(encoding="utf-8")
        netlist_text = netlist_file.read_text(encoding="utf-8")
        erc_findings = kicad_erc_findings_from_json_text(erc_text)
        fields: dict[str, Any] = {
            "project_id": project_id,
            "source_schematic": source.name,
            "source_schematic_sha256": _file_sha256(source),
            "kicad_cli_version": version,
            "page_count": len(pages),
            "pages": tuple(pages),
            "project_pdf_relative_path": project_pdf.relative_to(work).as_posix(),
            "project_pdf_sha256": _file_sha256(project_pdf),
            "erc_relative_path": erc_file.relative_to(work).as_posix(),
            "erc_sha256": _file_sha256(erc_file),
            "erc_canonical_sha256": _text_sha256(canonical_kicad_erc_json_text(erc_text)),
            "erc_findings": erc_findings,
            "netlist_relative_path": netlist_file.relative_to(work).as_posix(),
            "netlist_sha256": _file_sha256(netlist_file),
            "netlist_canonical_sha256": _text_sha256(
                canonical_kicad_netlist_xml_text(netlist_text)
            ),
            "ready_for_review": not erc_findings,
        }
        provisional = ConnectedSchematicReviewManifest.model_construct(
            **fields,
            manifest_fingerprint="0" * 64,
        )
        manifest = ConnectedSchematicReviewManifest(
            **fields,
            manifest_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"manifest_fingerprint"})
            ),
        )
        (work / "manifest.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        work.replace(target)
    return ConnectedSchematicReviewManifest.model_validate_json(
        (target / "manifest.json").read_text(encoding="utf-8")
    )


def _run_required(
    runner: Callable[[Sequence[str]], KiCadProcessResult],
    command: Sequence[str],
    label: str,
    *,
    require_zero: bool = True,
) -> KiCadProcessResult:
    try:
        result = runner(command)
    except OSError as error:
        raise ValueError(f"{label} could not run: {error}") from error
    if require_zero and result.returncode != 0:
        raise ValueError(f"{label} failed: {_process_detail(result)}")
    return result


def _process_detail(result: KiCadProcessResult) -> str:
    return result.stderr.strip() or result.stdout.strip() or "unknown error"


def _require_output(path: Path, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{label} did not produce a non-empty output")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe schematic review relative path: {value}")
    return path

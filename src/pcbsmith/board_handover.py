"""Read-only final CAD handover check; does not route, approve views or finish jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.kicad.check_reports import erc_violations, validate_native_header
from pcbsmith.kicad.project_dependencies import native_project_hashes
from pcbsmith.mandatory_review import native_rule_blockers, require_mandatory_review
from pcbsmith.manufacturing_lineage import file_sha256, native_input_hashes
from pcbsmith.production_readiness import PublicationReadinessReceipt, _relative_file
from pcbsmith.production_workflow import retained_production_release_evidence
from pcbsmith.routed_copper_graph_ir import fingerprint


def inspect_handover(request_file: Path) -> dict[str, Any]:
    """Replay production release and check the exact requested handover files.

    Request paths resolve relative to the request file. Observations are supplied
    by a real reviewer; this checker cannot authenticate the act of viewing.
    """
    request = json.loads(request_file.read_bytes())
    result: dict[str, Any] = {
        "schema_id": "pcbsmith-board-handover-v1",
        "cad_handover_ready": False,
        "physical_qualification": "not_established",
        "blockers": [],
        "request_sha256": file_sha256(request_file),
        "files": {},
    }

    def location(key: str) -> Path:
        return (request_file.parent / str(request[key])).resolve()

    try:
        generation = location("generation_root")
        board = location("board")
        release = location("release_report")
        retained_production_release_evidence(
            generation_root=generation, release_report_file=release, board_file=board
        )
        receipt = PublicationReadinessReceipt.model_validate_json(
            (generation / "review/design-readiness.json").read_bytes()
        )
        mandatory = require_mandatory_review(
            receipt.request.predesign, generation / "review/readiness-inputs"
        )
        if native_input_hashes(board) != receipt.request.native_inputs:
            raise ValueError("handover native inputs differ from the released generation")
        result["board_sha256"] = file_sha256(board)
        result["release_sha256"] = file_sha256(release)
        erc_path = location("erc_report")
        erc = validate_native_header(
            json.loads(erc_path.read_bytes()), "ERC", board.with_suffix(".kicad_sch")
        )
        process = json.loads(location("erc_process").read_bytes())
        command = process.get("command", [])
        if process.get("returncode") != 0 or not {"sch", "erc", "--severity-all"} <= set(command):
            raise ValueError("handover requires a successful all-severity native ERC process")
        inputs = process.get("native_inputs", process.get("input_sha256s", {}))
        by_name = {Path(name).name: digest for name, digest in inputs.items()}
        for suffix in (".kicad_sch", ".kicad_pro"):
            path = board.with_suffix(suffix)
            if by_name.get(path.name) != file_sha256(path):
                raise ValueError("ERC process does not bind the current schematic and project")
        # The process log and result are retained together, without accepting an
        # unrelated supplied report merely because it has the same source name.
        if erc_path.resolve() != location("erc_process").with_name("erc.json"):
            raise ValueError("ERC report must accompany its retained process log")
        if process.get("report_sha256") != file_sha256(erc_path):
            raise ValueError("ERC process receipt does not bind the report bytes")
        if erc_violations(erc):
            raise ValueError("handover ERC has findings")
        if "native_rule_review" in request:
            from pcbsmith.mandatory_review import require_native_review_completion

            completion = location("native_rule_review")
            mandatory = require_native_review_completion(
                mandatory,
                receipt.request.predesign.evidence_files["mandatory-review"].sha256,
                board,
                completion,
            )
            result["native_review_completion_sha256"] = file_sha256(completion)
        blockers = native_rule_blockers(mandatory, board.with_suffix(".kicad_pro"), {"erc": erc})
        if blockers:
            raise ValueError("; ".join(blockers))
        delivery = location("delivery_root")
        files = request["files"]
        if set(files) != set(mandatory.deliverables):
            raise ValueError("handover file roles differ from the reviewed deliverable inventory")
        for role, binding in files.items():
            path = _relative_file(delivery, binding["relative_path"])
            digest = file_sha256(path)
            if digest != binding["sha256"]:
                raise ValueError(f"handover file changed: {role}")
            result["files"][role] = {"path": str(path), "sha256": digest}
        for role, source in (
            ("pcb", board),
            ("schematic", board.with_suffix(".kicad_sch")),
            ("project", board.with_suffix(".kicad_pro")),
        ):
            if result["files"][role]["sha256"] != file_sha256(source):
                raise ValueError(f"delivered {role} differs from the checked native candidate")
        # Dependencies such as local symbols, footprints and models must survive
        # packaging too. Their paths are relative to the delivered board.
        delivered_board = Path(result["files"]["pcb"]["path"])
        if native_project_hashes(delivered_board) != native_project_hashes(board):
            raise ValueError("delivered native project dependencies differ from checked inputs")
        _require_recurring_lineage(receipt.request.predesign, board, result["files"])
        isolation_roles = {role for role in files if role.startswith("isolation_cam")}
        variants = request.get("isolation_variants", {})
        if set(variants) != isolation_roles - {"isolation_cam"}:
            raise ValueError(
                "Every additional isolation file requires its own replay and inspection"
            )
        observed_sides = set()
        two_sided_cam = False
        for role in sorted(isolation_roles):
            variant = variants.get(role)
            cam_request = (
                request
                if variant is None
                else {
                    "isolation_manifest": variant["manifest"],
                    "isolation_inspection": variant["inspection"],
                }
            )
            report = _require_isolation(
                cam_request, request_file.parent, board, result["files"][role]
            )
            layer = report.get("copper_layer", "F.Cu")
            mirrored = report.get("mirror_x", False)
            if variant is not None and (
                layer != variant["copper_layer"] or mirrored != variant["mirror_x"]
            ):
                raise ValueError(
                    "Isolation variant layer/orientation differs from the requested role"
                )
            if role == "isolation_cam" and (layer != "F.Cu" or mirrored):
                raise ValueError("Primary isolation artwork must be unmirrored front copper")
            two_sided_cam = two_sided_cam or report.get("two_sided", False)
            observed_sides.add((layer, mirrored))
            from pcbsmith.laser_artwork import verify_actual_copper_isolation

            actual = verify_actual_copper_isolation(
                board,
                Path(result["files"][role]["path"]).read_bytes(),
                minimum_clearance_mm=mandatory.minimum_board_rules["min_clearance"],
                minimum_edge_clearance_mm=mandatory.minimum_board_rules[
                    "min_copper_edge_clearance"
                ],
                two_sided=report.get("two_sided", False),
                copper_layer=layer,
                mirror_x=mirrored,
            )
            if role == "isolation_cam":
                result["actual_copper_isolation"] = actual
            else:
                result.setdefault("actual_copper_isolation_variants", {})[role] = actual
        if two_sided_cam and not {("F.Cu", False), ("B.Cu", True)} <= observed_sides:
            raise ValueError("Two-sided laser handover requires front and mirrored rear artwork")
        holds = request.get("physical_holds")
        if not isinstance(holds, list) or not holds:
            raise ValueError("unbuilt handover requires explicit physical qualification holds")
        for hold in holds:
            if hold.get("board_sha256") != file_sha256(board) or any(
                not isinstance(hold.get(key), str) or not hold[key].strip()
                for key in ("owner", "method", "acceptance_criterion", "required_inputs")
            ):
                raise ValueError("physical hold lacks owner, method, criterion, inputs or revision")
        result["physical_holds"] = holds
        result["cad_handover_ready"] = True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["blockers"].append(str(exc))
    result["fingerprint"] = fingerprint(result)
    return result


def _require_recurring_lineage(bundle: Any, board: Path, files: dict[str, Any]) -> None:
    """Validate declared recurring outputs; old role inventories remain replayable."""
    from pcbsmith.manufacturing_lineage import ExportReceipt, validate_ibom_lineage

    if "interactive_bom" in files:
        html = Path(files["interactive_bom"]["path"])
        receipt = ExportReceipt.model_validate_json(html.with_suffix(".receipt.json").read_bytes())
        validate_ibom_lineage(receipt, board, html)
    for role, evidence_id in (
        ("floorplan", "floorplan.floorplan.svg"),
        ("floorplan_preview", "floorplan.floorplan.png"),
    ):
        if role in files:
            binding = bundle.evidence_files.get(evidence_id)
            if binding is None or files[role]["sha256"] != binding.sha256:
                raise ValueError(f"Delivered {role} differs from the reviewed vector evidence")


def _require_isolation(
    request: dict[str, Any], root: Path, board: Path, delivered: dict[str, str]
) -> dict[str, Any]:
    from pcbsmith.kicad.project_dependencies import native_project_hashes

    manifest_path = (root / request["isolation_manifest"]).resolve()
    report: dict[str, Any] = json.loads(manifest_path.read_bytes())
    if report["source_inputs"] != native_project_hashes(board):
        raise ValueError("isolation artwork targets different native inputs")
    if report["removal_svg_sha256"] != delivered["sha256"]:
        raise ValueError("delivered isolation SVG differs from the CAM result")
    if not report.get("cam_floating_isolation_verified") or not report.get(
        "cam_retained_edge_isolation_verified"
    ):
        raise ValueError("isolation geometry checks are not satisfied")
    native = manifest_path.parent / "native-copper.svg"
    if not native.is_file() or file_sha256(native) != report["native_svg_sha256"]:
        raise ValueError("retained native copper SVG is missing or stale")
    from pcbsmith.kicad.library import _atom, _children, parse_sexpr
    from pcbsmith.laser_artwork import removal_svg

    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    edges = [
        n
        for n in tree
        if isinstance(n, list)
        and n
        and str(n[0]).startswith("gr_")
        and any(_atom(v[1]) == "Edge.Cuts" for v in _children(n, "layer"))
    ]
    if len(edges) != 1 or edges[0][0] != "gr_rect":
        raise ValueError("isolation replay requires the supported rectangular outline")
    bounds = tuple(float(_atom(v)) for k in ("start", "end") for v in _children(edges[0], k)[0][1:])
    if len(bounds) != 4:
        raise ValueError("invalid CAM outline")
    svg, geometry = removal_svg(
        native.read_bytes(),
        (bounds[0], bounds[1], bounds[2], bounds[3]),
        floating_clearance_mm=report["cam_floating_clearance_mm"],
        retained_edge_clearance_mm=report["cam_retained_edge_clearance_mm"],
        full_clear_regions_mm=tuple(tuple(v) for v in report.get("full_clear_regions_mm", [])),
        mirror_x=report.get("mirror_x", False),
    )
    if svg != Path(delivered["path"]).read_bytes() or any(
        report.get(k) != v for k, v in geometry.items()
    ):
        raise ValueError("isolation geometry does not replay from retained native copper")
    if report.get("two_sided"):
        process = json.loads((manifest_path.parent / "native-process.json").read_bytes())
        command = process.get("command", [])
        try:
            layer = command[command.index("--layers") + 1]
            scale = command[command.index("--scale") + 1]
            drill = command[command.index("--drill-shape-opt") + 1]
        except (ValueError, IndexError) as exc:
            raise ValueError("Two-sided CAM requires its original native plot process") from exc
        if (
            process.get("returncode") != 0
            or layer != report["copper_layer"]
            or (scale != "1" or drill != "0" or "--mirror" in command)
        ):
            raise ValueError("Native CAM layer, scale or orientation does not match the report")
        from pcbsmith.laser_artwork import verify_actual_copper_isolation

        actual = verify_actual_copper_isolation(
            board,
            svg,
            minimum_clearance_mm=0,
            minimum_edge_clearance_mm=0,
            two_sided=True,
            copper_layer=report["copper_layer"],
            mirror_x=report.get("mirror_x", False),
        )
        if actual != report.get("native_geometry_check"):
            raise ValueError("Two-sided CAM native geometry receipt is stale")
    inspection = request["isolation_inspection"]
    if (
        inspection.get("svg_sha256") != delivered["sha256"]
        or inspection.get("manifest_sha256") != file_sha256(manifest_path)
        or inspection.get("inspection") != "accepted"
    ):
        raise ValueError("isolation CAM requires inspection of the exact SVG and manifest")
    if any(
        not isinstance(inspection.get(k), str) or not inspection[k].strip()
        for k in ("reviewer", "mechanism", "view_reference")
    ) or not inspection.get("findings"):
        raise ValueError(
            "isolation inspection requires reviewer, viewing reference and observations"
        )
    if any(not isinstance(n, str) or not n.strip() for n in inspection["findings"]):
        raise ValueError("isolation inspection findings must be nonblank")
    return report

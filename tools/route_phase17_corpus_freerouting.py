"""Route the Phase 17 corpus through pinned Freerouting and KiCad DSN/SES."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
) -> tuple[int | None, float, str | None]:
    started = time.perf_counter()
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        stdout_path.write_bytes(stdout if isinstance(stdout, bytes) else stdout.encode())
        stderr_path.write_bytes(stderr if isinstance(stderr, bytes) else stderr.encode())
        return None, time.perf_counter() - started, f"timeout after {timeout_seconds}s"
    stdout_path.write_bytes(process.stdout)
    stderr_path.write_bytes(process.stderr)
    return process.returncode, time.perf_counter() - started, None


def _drc_counts(report: Path) -> tuple[int, int, tuple[str, ...]]:
    payload = json.loads(report.read_text(encoding="utf-8"))
    violations = payload.get("violations", [])
    unconnected = payload.get("unconnected_items", [])
    types = tuple(
        sorted(str(item.get("type", "unknown")) for item in violations if isinstance(item, dict))
    )
    return len(violations), len(unconnected), types


def _freerouting_crash(
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, str] | None:
    """Classify fatal JVM/router signatures retained in captured logs."""

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (stdout_path, stderr_path)
        if path.exists()
    )
    if "java.lang.StackOverflowError" in combined:
        subsystem = (
            "PolylineTrace.combine"
            if "app.freerouting.board.PolylineTrace.combine" in combined
            else "unknown"
        )
        return {
            "kind": "java_stack_overflow",
            "subsystem": subsystem,
            "signature": f"java.lang.StackOverflowError:{subsystem}",
        }
    if "java.lang.OutOfMemoryError" in combined:
        return {
            "kind": "java_out_of_memory",
            "subsystem": "unknown",
            "signature": "java.lang.OutOfMemoryError",
        }
    return None


def _board_counts(board: Path) -> tuple[int, int]:
    text = board.read_text(encoding="utf-8")
    return len(re.findall(r"\(segment\s", text)), len(re.findall(r"\(via\s", text))


def _freerouting_version(jar: Path) -> str:
    match = re.fullmatch(r"freerouting-(\d+\.\d+\.\d+)\.jar", jar.name)
    if match is None:
        raise ValueError(f"Cannot derive Freerouting version from {jar.name}")
    return match.group(1)


def _freerouting_compatibility_error(
    router_version: str,
    placement_board: Path,
) -> str | None:
    segment_count, via_count = _board_counts(placement_board)
    if router_version == "2.2.4" and (segment_count or via_count):
        return (
            "Freerouting v2.2.4 is blocked for DSN inputs with retained wiring: "
            "upstream issue #759 can recurse indefinitely in PolylineTrace.combine, "
            "show a modal StackOverflowError dialog, and hang without SES output."
        )
    return None


def _next_attempt_directory(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    loose_items = tuple(item for item in base.iterdir() if not item.name.startswith("attempt-"))
    if loose_items:
        legacy = base / "attempt-01"
        legacy.mkdir(exist_ok=True)
        for item in loose_items:
            shutil.move(str(item), legacy / item.name)
    attempts = sorted(
        int(item.name.split("-", 1)[1])
        for item in base.iterdir()
        if item.is_dir() and re.fullmatch(r"attempt-\d+", item.name)
    )
    next_number = attempts[-1] + 1 if attempts else 1
    attempt = base / f"attempt-{next_number:02d}"
    attempt.mkdir()
    return attempt


def route_case(
    case_dir: Path,
    *,
    bridge: Path,
    java: Path,
    jar: Path,
    kicad_python: Path,
    kicad_cli: Path,
    max_passes: int,
    timeout_seconds: int,
    router_version: str,
) -> dict[str, object]:
    contract = json.loads((case_dir / "case-contract.json").read_text(encoding="utf-8"))
    case_id = str(contract["case_id"])
    placement = next(case_dir.glob("*-placement.kicad_pcb"))
    placement_sha256 = _sha256(placement)
    placement_gate_path = (
        case_dir
        / "placement-check"
        / f"revision-{placement_sha256[:12]}"
        / "placement-evidence.json"
    )
    if not placement_gate_path.exists():
        raise RuntimeError(f"Missing placement preflight for {case_id}: {placement_gate_path}")
    placement_gate = json.loads(placement_gate_path.read_text(encoding="utf-8"))
    compatibility_error = _freerouting_compatibility_error(router_version, placement)
    if compatibility_error is not None:
        raise RuntimeError(compatibility_error)
    if (
        placement_gate.get("schema") != "pcbsmith-placement-preflight-v2"
        or placement_gate.get("source_board_sha256") != placement_sha256
        or placement_gate.get("placement_geometry_clean") is not True
    ):
        raise RuntimeError(f"Placement geometry gate did not pass for {case_id}")
    router_root = case_dir / "external" / f"freerouting-v{router_version}"
    run_dir = _next_attempt_directory(router_root)
    source = run_dir / "source-placement.kicad_pcb"
    shutil.copy2(placement, source)
    dsn = run_dir / "input.dsn"
    ses = run_dir / "output.ses"
    routed = run_dir / f"{case_dir.name}-freerouting.kicad_pcb"
    contract_nets = contract["nets"]
    if not isinstance(contract_nets, list):
        raise TypeError("case-contract nets must be a list")
    width_rules = {
        str(item["name"]): float(item["width_mm"])
        for item in contract_nets
        if isinstance(item, dict)
    }
    width_rules_file = run_dir / "width-rules.json"
    _write_json(width_rules_file, width_rules)

    export_command = (
        str(kicad_python),
        str(bridge),
        "export",
        str(source),
        str(dsn),
        "--width-rules-json",
        str(width_rules_file),
    )
    export_exit, export_seconds, export_error = _run(
        export_command,
        cwd=run_dir,
        stdout_path=run_dir / "export.stdout.log",
        stderr_path=run_dir / "export.stderr.log",
        timeout_seconds=timeout_seconds,
    )
    router_exit: int | None = None
    router_seconds = 0.0
    router_error: str | None = None
    router_crash: dict[str, str] | None = None
    import_exit: int | None = None
    import_seconds = 0.0
    import_error: str | None = None
    width_inspect_exit: int | None = None
    width_inspect_seconds = 0.0
    width_inspect_error: str | None = None
    width_payload: dict[str, object] = {"width_intent_accepted": False}
    drc_exit: int | None = None
    drc_seconds = 0.0
    drc_error: str | None = None
    violation_count = 0
    unconnected_count = 0
    violation_types: tuple[str, ...] = ()
    segment_count = 0
    via_count = 0

    if export_exit == 0 and dsn.exists():
        router_command = (
            str(java),
            "-Djava.awt.headless=true",
            "-jar",
            str(jar),
            "-de",
            dsn.name,
            "-do",
            ses.name,
            "-mp",
            str(max_passes),
            "-mt",
            "1",
            "--gui.enabled=false",
            "--router.fanout.enabled=false",
            "--router.automatic_neckdown=false",
            "-da",
            "--logging.file.enabled=false",
            "--user_data_path=freerouting-user",
        )
        router_stdout = run_dir / "router.stdout.log"
        router_stderr = run_dir / "router.stderr.log"
        router_exit, router_seconds, router_error = _run(
            router_command,
            cwd=run_dir,
            stdout_path=router_stdout,
            stderr_path=router_stderr,
            timeout_seconds=timeout_seconds,
        )
        router_crash = _freerouting_crash(router_stdout, router_stderr)
        if router_crash is not None:
            router_error = router_crash["signature"]
    if router_exit == 0 and ses.exists():
        import_command = (
            str(kicad_python),
            str(bridge),
            "import",
            str(source),
            str(ses),
            str(routed),
        )
        import_exit, import_seconds, import_error = _run(
            import_command,
            cwd=run_dir,
            stdout_path=run_dir / "import.stdout.log",
            stderr_path=run_dir / "import.stderr.log",
            timeout_seconds=timeout_seconds,
        )
    width_report = run_dir / "width-observations.json"
    if import_exit == 0 and routed.exists():
        width_command = (
            str(kicad_python),
            str(bridge),
            "inspect-widths",
            str(routed),
            str(width_rules_file),
            str(width_report),
        )
        width_inspect_exit, width_inspect_seconds, width_inspect_error = _run(
            width_command,
            cwd=run_dir,
            stdout_path=run_dir / "width-inspect.stdout.log",
            stderr_path=run_dir / "width-inspect.stderr.log",
            timeout_seconds=timeout_seconds,
        )
        if width_report.exists():
            loaded_widths = json.loads(width_report.read_text(encoding="utf-8"))
            if isinstance(loaded_widths, dict):
                width_payload = loaded_widths
    drc_report = run_dir / "drc.json"
    if import_exit == 0 and routed.exists():
        drc_command = (
            str(kicad_cli),
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(drc_report),
            "--refill-zones",
            "--save-board",
            str(routed),
        )
        drc_exit, drc_seconds, drc_error = _run(
            drc_command,
            cwd=run_dir,
            stdout_path=run_dir / "drc.stdout.log",
            stderr_path=run_dir / "drc.stderr.log",
            timeout_seconds=timeout_seconds,
        )
        if drc_report.exists():
            violation_count, unconnected_count, violation_types = _drc_counts(drc_report)
        segment_count, via_count = _board_counts(routed)

    success = (
        export_exit == 0
        and router_exit == 0
        and import_exit == 0
        and width_inspect_exit == 0
        and width_payload.get("width_intent_accepted") is True
        and drc_exit == 0
        and violation_count == 0
        and unconnected_count == 0
    )
    evidence: dict[str, object] = {
        "schema": "pcbsmith-freerouting-case-evidence-v2",
        "case_id": case_id,
        "attempt_directory": run_dir.relative_to(case_dir).as_posix(),
        "success": success,
        "source_board_sha256": placement_sha256,
        "placement_gate": {
            "path": placement_gate_path.relative_to(case_dir).as_posix(),
            "sha256": _sha256(placement_gate_path),
            "placement_geometry_clean": True,
            "silkscreen_clean": placement_gate.get("silkscreen_clean") is True,
        },
        "dsn_sha256": _sha256(dsn) if dsn.exists() else None,
        "ses_sha256": _sha256(ses) if ses.exists() else None,
        "routed_board_sha256": _sha256(routed) if routed.exists() else None,
        "width_rules_sha256": _sha256(width_rules_file),
        "export": {"exit_code": export_exit, "seconds": export_seconds, "error": export_error},
        "router": {
            "exit_code": router_exit,
            "seconds": router_seconds,
            "error": router_error,
            "crash": router_crash,
            "jvm_headless": True,
            "fanout_enabled": False,
            "automatic_neckdown_enabled": False,
        },
        "import": {"exit_code": import_exit, "seconds": import_seconds, "error": import_error},
        "widths": {
            "exit_code": width_inspect_exit,
            "seconds": width_inspect_seconds,
            "error": width_inspect_error,
            "report": width_payload,
        },
        "drc": {
            "exit_code": drc_exit,
            "seconds": drc_seconds,
            "error": drc_error,
            "violation_count": violation_count,
            "unconnected_count": unconnected_count,
            "violation_types": list(violation_types),
        },
        "geometry": {"segment_count": segment_count, "via_count": via_count},
        "qualification_boundary": (
            "Clean KiCad connectivity/DRC is not electrical, thermal, DFM, or "
            "current-capacity qualification."
        ),
    }
    _write_json(run_dir / "route-evidence.json", evidence)
    return evidence


def _manifest(root: Path) -> None:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"artifact-manifest.json", "freerouting-artifact-manifest.json"}:
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    _write_json(root / "freerouting-artifact-manifest.json", {"files": records})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--max-passes", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--java", type=Path, default=Path(".pcbsmith/tools/java/temurin-25-jre/bin/java.exe")
    )
    parser.add_argument(
        "--jar",
        type=Path,
        default=Path(".pcbsmith/tools/freerouting/v2.3.0/freerouting-2.3.0.jar"),
    )
    parser.add_argument(
        "--kicad-python", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/python.exe")
    )
    parser.add_argument(
        "--kicad-cli", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")
    )
    args = parser.parse_args()
    root = args.root.resolve()
    bridge = Path(__file__).with_name("kicad_dsn_ses_bridge.py").resolve()
    java = args.java.resolve()
    jar = args.jar.resolve()
    kicad_python = args.kicad_python.resolve()
    kicad_cli = args.kicad_cli.resolve()
    router_version = _freerouting_version(jar)
    for required in (root, bridge, java, jar, kicad_python, kicad_cli):
        if not required.exists():
            raise FileNotFoundError(required)

    selected = set(args.case)
    case_dirs = tuple(
        path
        for path in sorted((root / "boards").iterdir())
        if path.is_dir() and (not selected or path.name.split("-", 1)[0] in selected)
    )
    results = []
    for index, case_dir in enumerate(case_dirs, start=1):
        print(f"[{index}/{len(case_dirs)}] {case_dir.name}", flush=True)
        results.append(
            route_case(
                case_dir,
                bridge=bridge,
                java=java,
                jar=jar,
                kicad_python=kicad_python,
                kicad_cli=kicad_cli,
                max_passes=args.max_passes,
                timeout_seconds=args.timeout_seconds,
                router_version=router_version,
            )
        )
    summary = {
        "schema": "pcbsmith-freerouting-corpus-summary-v1",
        "attempted": len(results),
        "successes": sum(item["success"] is True for item in results),
        "failures": sum(item["success"] is not True for item in results),
        "freerouting": {"version": router_version, "jar_sha256": _sha256(jar)},
        "java_sha256": _sha256(java),
        "cases": results,
    }
    _write_json(root / "freerouting-summary.json", summary)
    _manifest(root)
    print(json.dumps({key: summary[key] for key in ("attempted", "successes", "failures")}))


if __name__ == "__main__":
    main()

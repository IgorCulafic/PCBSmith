"""Static inventory for test cases and production check authorities.

This is a stewardship report, not another acceptance gate.  Its heuristics
identify review candidates; they never delete or disable a test automatically.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TEST_FUNCTION = re.compile(r"^test_")
CHECK_FUNCTION = re.compile(r"^(?:_?check|validate|evaluate|run_.*(?:drc|erc|checks?))")
COORDINATE_OR_SCALE_NAMES = {
    "x",
    "y",
    "x_mm",
    "y_mm",
    "width",
    "height",
    "scale",
    "rotation",
    "angle",
    "pixel",
    "pixels",
    "ppm",
    "coordinate",
    "position",
}
BUDGET_NAMES = {
    "budget",
    "expansion",
    "iterations",
    "passes",
    "timeout",
    "elapsed",
    "memory",
}


def _test_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and TEST_FUNCTION.match(node.name)
    ]


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        parts = [node.func.attr]
        value = node.func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _has_numeric_or_hash_pin(node: ast.Assert) -> tuple[bool, bool]:
    values = [item.value for item in ast.walk(node.test) if isinstance(item, ast.Constant)]
    numeric = any(
        isinstance(value, (int, float)) and not isinstance(value, bool) for value in values
    )
    hash_pin = any(
        isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{40,64}", value))
        for value in values
    )
    return numeric, hash_pin


def _assertion_categories(node: ast.Assert) -> tuple[bool, bool]:
    names = {
        item.id.lower()
        for item in ast.walk(node.test)
        if isinstance(item, ast.Name)
    }
    names.update(
        item.attr.lower()
        for item in ast.walk(node.test)
        if isinstance(item, ast.Attribute)
    )
    coordinate_or_scale = any(
        any(token == name or token in name.split("_") for token in COORDINATE_OR_SCALE_NAMES)
        for name in names
    )
    budget = any(
        any(token == name or token in name.split("_") for token in BUDGET_NAMES)
        for name in names
    )
    return coordinate_or_scale, budget


def _body_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    body = ast.Module(body=node.body, type_ignores=[])
    return hashlib.sha256(ast.dump(body, include_attributes=False).encode("utf-8")).hexdigest()


def audit_test_files(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    duplicate_bodies: dict[str, list[str]] = defaultdict(list)
    for path in sorted((root / "tests").rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        tests = _test_functions(tree)
        parametrized = 0
        numeric_pins = 0
        hash_pins = 0
        coordinate_or_scale_pins = 0
        budget_pins = 0
        private_imports: set[str] = set()
        sleep_calls = 0
        subprocess_calls = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                private_imports.update(
                    alias.name for alias in node.names if alias.name.startswith("_")
                )
            elif isinstance(node, ast.Call):
                name = _call_name(node)
                sleep_calls += int(name in {"sleep", "time.sleep"})
                subprocess_calls += int(name.startswith("subprocess."))
        for test in tests:
            if any(
                isinstance(decorator, ast.Call) and _call_name(decorator).endswith("parametrize")
                for decorator in test.decorator_list
            ):
                parametrized += 1
            for assertion in (item for item in ast.walk(test) if isinstance(item, ast.Assert)):
                numeric, hash_pin = _has_numeric_or_hash_pin(assertion)
                coordinate_or_scale, budget = _assertion_categories(assertion)
                numeric_pins += int(numeric)
                hash_pins += int(hash_pin)
                coordinate_or_scale_pins += int(numeric and coordinate_or_scale)
                budget_pins += int(numeric and budget)
            duplicate_bodies[_body_fingerprint(test)].append(
                f"{path.relative_to(root).as_posix()}::{test.name}"
            )
        relative = path.relative_to(root).as_posix()
        records.append(
            {
                "file": relative,
                "lines": source.count("\n") + 1,
                "test_functions": len(tests),
                "parametrized_functions": parametrized,
                "numeric_literal_assertions": numeric_pins,
                "hash_literal_assertions": hash_pins,
                "coordinate_or_scale_literal_assertions": coordinate_or_scale_pins,
                "budget_literal_assertions": budget_pins,
                "private_symbol_imports": sorted(private_imports),
                "sleep_calls": sleep_calls,
                "subprocess_calls": subprocess_calls,
                "golden": "pytest.mark.golden" in source or relative.startswith("tests/golden/"),
                "integration": relative.startswith("tests/integration/"),
            }
        )
    exact_duplicate_groups = tuple(
        sorted(
            (tuple(items) for items in duplicate_bodies.values() if len(items) > 1),
            key=len,
            reverse=True,
        )
    )
    return {
        "files": records,
        "ast_test_functions": sum(item["test_functions"] for item in records),
        "parametrized_functions": sum(item["parametrized_functions"] for item in records),
        "files_importing_private_symbols": sum(
            bool(item["private_symbol_imports"]) for item in records
        ),
        "numeric_literal_assertions": sum(item["numeric_literal_assertions"] for item in records),
        "hash_literal_assertions": sum(item["hash_literal_assertions"] for item in records),
        "coordinate_or_scale_literal_assertions": sum(
            item["coordinate_or_scale_literal_assertions"] for item in records
        ),
        "budget_literal_assertions": sum(
            item["budget_literal_assertions"] for item in records
        ),
        "sleep_calls": sum(item["sleep_calls"] for item in records),
        "subprocess_calls": sum(item["subprocess_calls"] for item in records),
        "exact_duplicate_body_groups": exact_duplicate_groups,
    }


def parse_junit_runtime(path: Path, root: Path) -> dict[str, Any]:
    """Attribute measured pytest runtime from a retained JUnit XML result."""

    tree = ET.parse(path)
    by_file: defaultdict[str, float] = defaultdict(float)
    by_test: list[dict[str, Any]] = []
    for case in tree.getroot().iter("testcase"):
        seconds = float(case.attrib.get("time", "0") or 0)
        file_name = case.attrib.get("file")
        if file_name is None:
            class_name = case.attrib.get("classname", "")
            file_name = class_name.replace(".", "/") + ".py"
        normalized = file_name.replace("\\", "/")
        try:
            normalized = Path(normalized).resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            pass
        test_id = f"{normalized}::{case.attrib.get('name', '<unknown>')}"
        by_file[normalized] += seconds
        by_test.append({"test_id": test_id, "seconds": seconds})
    by_test.sort(key=lambda item: (-item["seconds"], item["test_id"]))
    return {
        "source": str(path.resolve()),
        "total_case_seconds": sum(item["seconds"] for item in by_test),
        "by_file_seconds": dict(sorted(by_file.items())),
        "slowest_tests": by_test[:100],
    }


def collect_pytest_cases(root: Path) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"pytest collection failed:\n{process.stdout}\n{process.stderr}")
    by_file: Counter[str] = Counter()
    for line in process.stdout.splitlines():
        match = re.fullmatch(r"(.+\.py): (\d+)", line.strip())
        if match:
            by_file[match.group(1).replace("\\", "/")] = int(match.group(2))
    return {
        "collected_cases": sum(by_file.values()),
        "by_file": dict(sorted(by_file.items())),
        "summary_line": next(
            (line.strip() for line in reversed(process.stdout.splitlines()) if "collected" in line),
            "",
        ),
    }


def audit_production_checks(root: Path) -> dict[str, Any]:
    production_sources = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "src" / "pcbsmith").rglob("*.py"))
    }
    test_sources = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "tests").rglob("*.py"))
    }
    records: list[dict[str, Any]] = []
    for relative, source in production_sources.items():
        path = root / relative
        tree = ast.parse(source, filename=str(path))
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not CHECK_FUNCTION.match(node.name):
                continue
            parent = parents.get(node)
            definition_scope = (
                "module"
                if isinstance(parent, ast.Module)
                else ("class_method" if isinstance(parent, ast.ClassDef) else "nested")
            )
            framework_validator = any(
                (
                    isinstance(decorator, ast.Name)
                    and decorator.id in {"model_validator", "field_validator"}
                )
                or (
                    isinstance(decorator, ast.Call)
                    and _call_name(decorator)
                    in {"model_validator", "field_validator"}
                )
                for decorator in node.decorator_list
            )
            if relative.endswith("/design_checks.py"):
                family = "design_checks"
            elif relative.endswith("/virtual_drc.py"):
                family = "virtual_drc"
            elif relative.endswith("/validate.py"):
                family = "kicad_cli_adapter"
            elif "semantic" in relative or "evaluator" in relative:
                family = "semantic_evaluator"
            else:
                family = "domain_or_contract"
            owner_id, ownership_kind, caller_stage = _check_owner(relative, family)
            reference_pattern = re.compile(rf"\b{re.escape(node.name)}\b")
            production_references = sum(
                len(reference_pattern.findall(text))
                for candidate, text in production_sources.items()
                if candidate != relative
            )
            test_references = sum(
                len(reference_pattern.findall(text)) for text in test_sources.values()
            )
            caller_coverage = (
                "framework"
                if framework_validator
                else (
                    "observed"
                    if production_references
                    else ("test_only" if test_references else "unobserved")
                )
            )
            records.append(
                {
                    "file": relative,
                    "function": node.name,
                    "line": node.lineno,
                    "public": definition_scope == "module" and not node.name.startswith("_"),
                    "definition_scope": definition_scope,
                    "framework_validator": framework_validator,
                    "family": family,
                    "owner_authority_id": owner_id,
                    "ownership_kind": ownership_kind,
                    "caller_stage": caller_stage,
                    "production_reference_count": production_references,
                    "test_reference_count": test_references,
                    "caller_coverage": caller_coverage,
                }
            )
    return {
        "candidate_functions": len(records),
        "public_entrypoints": sum(item["public"] for item in records),
        "by_family": dict(Counter(item["family"] for item in records)),
        "by_owner": dict(Counter(item["owner_authority_id"] for item in records)),
        "by_caller_coverage": dict(Counter(item["caller_coverage"] for item in records)),
        "functions": records,
    }


def _check_owner(relative: str, family: str) -> tuple[str, str, str]:
    normalized = relative.removeprefix("src/").removesuffix(".py").replace("/", ".")
    exact = {
        "pcbsmith.project_engineering_gate": ("engineering.project-gate", "shared", "review"),
        "pcbsmith.workflow_conformance": ("workflow.conformance", "shared", "verification"),
        "pcbsmith.predesign_gate": ("predesign.feasibility", "shared", "concept"),
        "pcbsmith.evidence.source_intake": ("evidence.source-intake", "shared", "evidence"),
        "pcbsmith.kicad.model_preflight": ("assets.model-preflight", "shared", "review"),
        "pcbsmith.kicad.decoupling_loop": ("layout.decoupling-loop", "shared", "review"),
        "pcbsmith.kicad.connector_protection_order": (
            "layout.connector-protection-order",
            "shared",
            "review",
        ),
        "pcbsmith.kicad.oscillator_zone": ("layout.oscillator-zone", "shared", "review"),
        "pcbsmith.kicad.switching_hot_loop": (
            "layout.switching-hot-loop",
            "shared",
            "review",
        ),
        "pcbsmith.kicad.return_adjacency": ("layout.return-adjacency", "shared", "review"),
    }
    if normalized in exact:
        return exact[normalized]
    if family == "design_checks":
        return "layout.semantic-process", "shared", "review"
    if family in {"virtual_drc", "kicad_cli_adapter"}:
        return "kicad.saved-board", "shared", "verification"
    return f"module-local:{normalized}", "module_local", "declaring_module"


def build_report(root: Path, *, junitxml: Path | None = None) -> dict[str, Any]:
    tests = audit_test_files(root)
    collection = collect_pytest_cases(root)
    production = audit_production_checks(root)
    runtime = None if junitxml is None else parse_junit_runtime(junitxml, root)
    for record in tests["files"]:
        record["collected_cases"] = collection["by_file"].get(record["file"], 0)
        record["runtime_seconds"] = (
            None
            if runtime is None
            else runtime["by_file_seconds"].get(record["file"], 0.0)
        )
    return {
        "schema": "pcbsmith-test-check-stewardship-audit-v2",
        "scope": str(root.resolve()),
        "tests": {**tests, **collection},
        "production_checks": production,
        "runtime": runtime,
        "interpretation_limits": (
            "Static numeric-literal and private-import counts are review leads, not defects.",
            "Exact duplicate bodies do not detect semantically overlapping tests with "
            "different fixtures.",
            "Runtime attribution requires a timed full-suite run and is not inferred "
            "from source size.",
            "Candidate production functions are name-based; Pydantic validators and "
            "inline invariants are additional authorities.",
            "Caller-reference counts are lexical triage signals; dynamic dispatch and "
            "same-file calls require manual review.",
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    tests = report["tests"]
    production = report["production_checks"]
    files = sorted(tests["files"], key=lambda item: item["collected_cases"], reverse=True)
    lines = [
        "# Test and production-check inventory",
        "",
        "This report is an inventory and triage aid, not an instruction to delete tests "
        "by age or count.",
        "",
        "## Scale",
        "",
        f"- {tests['collected_cases']:,} collected pytest cases.",
        f"- {tests['ast_test_functions']:,} authored test functions across {len(files)} files.",
        f"- {tests['parametrized_functions']:,} authored functions use parametrization.",
        f"- {production['candidate_functions']:,} name-matched production check/validation "
        f"functions, including {production['public_entrypoints']:,} public entrypoints.",
        "",
        "The collected-case count is therefore not a count of independent PCB rules. "
        "Parametrization, tamper matrices, and contract variants expand one authored "
        "contract into many cases.",
        "",
        "## Static review leads",
        "",
        f"- Files importing production-private symbols: "
        f"{tests['files_importing_private_symbols']}.",
        f"- Assertions containing numeric literals: {tests['numeric_literal_assertions']} "
        "(many are legitimate boundary contracts).",
        f"- Assertions containing literal SHA-like values: {tests['hash_literal_assertions']}.",
        f"- Numeric assertions mentioning coordinate/scale fields: "
        f"{tests['coordinate_or_scale_literal_assertions']}.",
        f"- Numeric assertions mentioning work/time/memory budgets: "
        f"{tests['budget_literal_assertions']}.",
        f"- Exact duplicate test-body groups: {len(tests['exact_duplicate_body_groups'])}.",
        f"- Explicit sleep calls: {tests['sleep_calls']}; subprocess calls: "
        f"{tests['subprocess_calls']}.",
        "",
        "## Largest files by collected cases",
        "",
        "| Cases | Functions | Lines | File |",
        "|---:|---:|---:|---|",
    ]
    for item in files[:25]:
        lines.append(
            f"| {item['collected_cases']} | {item['test_functions']} | "
            f"{item['lines']} | `{item['file']}` |"
        )
    lines.extend(("", "## Production function families", ""))
    for family, count in sorted(production["by_family"].items()):
        lines.append(f"- {family}: {count}")
    lines.extend(("", "## Production-check ownership", ""))
    for owner, count in sorted(production["by_owner"].items()):
        lines.append(f"- `{owner}`: {count}")
    lines.extend(("", "## Caller-coverage triage", ""))
    for state, count in sorted(production["by_caller_coverage"].items()):
        lines.append(f"- {state}: {count}")
    runtime = report["runtime"]
    if runtime is not None:
        lines.extend(
            (
                "",
                "## Measured runtime attribution",
                "",
                f"- JUnit source: `{runtime['source']}`",
                f"- Summed testcase time: {runtime['total_case_seconds']:.3f} s",
                "",
                "| Seconds | Test |",
                "|---:|---|",
            )
        )
        for item in runtime["slowest_tests"][:25]:
            lines.append(f"| {item['seconds']:.3f} | `{item['test_id']}` |")
    lines.extend(("", "## Interpretation limits", ""))
    lines.extend(f"- {item}" for item in report["interpretation_limits"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--junitxml", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    report = build_report(root, junitxml=args.junitxml)
    output = args.output or root / ".pcbsmith" / "audits" / "test-check-inventory"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "collected_cases": report["tests"]["collected_cases"],
                "authored_test_functions": report["tests"]["ast_test_functions"],
                "production_check_candidates": report["production_checks"]["candidate_functions"],
                "output": str(output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

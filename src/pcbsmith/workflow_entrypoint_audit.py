"""Repository-wide inventory of native-board producers and their explicit posture.

This catches unclassified new callers in CI. It is not a security sandbox for
arbitrary Python or proof that a classified research script follows production gates.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


class _Calls(ast.NodeVisitor):
    def __init__(self, native_literal: bool) -> None:
        self.native_literal = native_literal
        self.owner = "<module>"
        self.calls: dict[str, list[str]] = {}
        self.aliases: dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.aliases[alias.asname or alias.name] = alias.name

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        previous = self.owner
        self.owner = node.name if previous == "<module>" else f"{previous}.{node.name}"
        self.generic_visit(node)
        self.owner = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        name = ast.unparse(node.func)
        first, *rest = name.split(".")
        resolved = ".".join([self.aliases.get(first, first), *rest])
        leaf = resolved.rsplit(".", 1)[-1]
        named_board = leaf.startswith(("generate_", "build_", "write_")) and leaf.endswith("board")
        render = leaf == "SaveBoard" or (
            leaf.startswith("render_")
            and (
                leaf.endswith("board")
                or leaf.endswith("board_file")
                or leaf.endswith("board_items")
                or leaf == "render_board_from_layout"
            )
        )
        raw_write = self.native_literal and leaf in {
            "write_text",
            "write_bytes",
            "atomic_write",
            "write",
        }
        transaction = leaf in {
            "create_board_revision",
            "apply_board_revision",
            "refill_native_edit",
            "refill_and_read_kicad_board",
            "retain_native_project",
            "upgrade_generated_native_file",
        }
        if named_board or render or raw_write or transaction:
            self.calls.setdefault(self.owner, []).append(
                resolved if not raw_write else "native-context-file-write"
            )
        self.generic_visit(node)


def discover_workflow_callers(repository: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for base in (repository / "src/pcbsmith", repository / "tools"):
        for path in sorted(base.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            native_literal = any(
                isinstance(n, ast.Constant) and isinstance(n.value, str) and ".kicad_pcb" in n.value
                for n in ast.walk(tree)
            )
            visitor = _Calls(native_literal)
            visitor.visit(tree)
            for owner, calls in visitor.calls.items():
                found[f"{path.relative_to(repository).as_posix()}:{owner}"] = sorted(calls)
    return found


def audit_workflow_callers(repository: Path, policy_file: Path) -> dict[str, Any]:
    discovered = discover_workflow_callers(repository)
    data = json.loads(policy_file.read_bytes())
    if data.get("schema") != "pcbsmith-board-caller-policy-v1":
        raise ValueError("unsupported board caller policy")
    policy = data["callers"]
    unknown = sorted(set(discovered) - set(policy))
    stale = sorted(set(policy) - set(discovered))
    changed = sorted(
        key
        for key in discovered.keys() & policy.keys()
        if policy[key].get("calls") != discovered[key]
    )
    invalid = sorted(
        key
        for key, row in policy.items()
        if row.get("classification")
        not in {"supported_boundary", "native_primitive", "research_or_compatibility"}
        or not row.get("rationale")
    )
    return {
        "status": "passed" if not (unknown or stale or changed or invalid) else "failed",
        "discovered_count": len(discovered),
        "unclassified": unknown,
        "stale": stale,
        "changed_calls": changed,
        "invalid_policy": invalid,
        "limitations": (
            "Static named-call/import-alias and native-literal write inventory; "
            "dynamic code is not sandboxed. Production status still requires "
            "replayed runtime evidence."
        ),
    }

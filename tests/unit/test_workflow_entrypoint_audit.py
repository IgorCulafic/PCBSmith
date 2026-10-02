from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith import cli, prototype_cli
from pcbsmith.workflow_entrypoint_audit import audit_workflow_callers, discover_workflow_callers


def test_repository_native_callers_have_explicit_policy():
    root = Path(__file__).parents[2]
    result = audit_workflow_callers(root, root / "docs/board-workflow-entrypoints.json")
    assert result["status"] == "passed", result
    assert result["discovered_count"] > 150  # Wider than the former 23-function registry.


@pytest.mark.parametrize(
    "snippet",
    [
        "from pcbsmith.kicad.board import generate_board as harmless\ndef run():\n harmless()\n",
        'def unnamed():\n Path("new.kicad_pcb").write_bytes(payload)\n',
        (
            "from pcbsmith.kicad.board import render_board_file as harmless\n"
            "def make():\n harmless()\n"
        ),
        "def build():\n pcbnew.SaveBoard(destination, board)\n",
        (
            "from pcbsmith.kicad.native_zone_edits import refill_native_edit as safe\n"
            "def run():\n safe()\n"
        ),
        "from pcbsmith.board_revision import create_board_revision as safe\ndef run():\n safe()\n",
    ],
)
def test_new_callers_are_not_automatically_whitelisted(tmp_path, snippet):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "innocent_name.py").write_text(snippet)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"schema": "pcbsmith-board-caller-policy-v1", "callers": {}}))
    result = audit_workflow_callers(tmp_path, policy)
    assert result["status"] == "failed" and result["unclassified"]


def test_added_calls_in_previously_classified_function_are_detected(tmp_path):
    (tmp_path / "tools").mkdir()
    source = tmp_path / "tools/writer.py"
    source.write_text("def run():\n generate_board()\n")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-board-caller-policy-v1",
                "callers": {
                    key: {
                        "calls": calls,
                        "classification": "research_or_compatibility",
                        "rationale": "test",
                    }
                    for key, calls in discover_workflow_callers(tmp_path).items()
                },
            }
        )
    )
    source.write_text("def run():\n generate_board()\n generate_other_board()\n")
    assert audit_workflow_callers(tmp_path, policy)["changed_calls"] == ["tools/writer.py:run"]


@pytest.mark.parametrize(
    "module,command",
    [
        (cli, "design-divider-highpass-led"),
        (cli, "design-led-art"),
        (prototype_cli, "design-led-art"),
    ],
)
def test_legacy_commands_refuse_before_creating_outputs(module, command, tmp_path, capsys):
    target = tmp_path / "must-not-exist"
    arguments = [command, str(target)]
    if command == "design-divider-highpass-led":
        arguments += ["--request", "fixture", "--name", "fixture"]
    assert module.main(arguments) == 2
    assert "requires --research" in capsys.readouterr().err
    assert not target.exists()


def test_all_legacy_handlers_expose_research_opt_in():
    import argparse

    for module in (cli, prototype_cli):
        parser = module.build_parser()
        action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        for command in action.choices.values():
            handler = command.get_default("func")
            if handler and handler.__name__.startswith("_cmd_design_"):
                assert "--research" in command._option_string_actions


@pytest.fixture(autouse=True)
def isolated_producer_contracts(monkeypatch):
    """Synthetic inner-contract tests; real job authorization is tested separately."""
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)

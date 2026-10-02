import hashlib
import json

import pytest

from pcbsmith.routing_preparation import (
    RoutingInputSource,
    RoutingPreparationRequest,
    prepare_routing_inputs,
)


def test_sources_are_exact_and_support_nested_records(tmp_path):
    path = tmp_path / "source.json"
    payload = json.dumps({"fact/one": {"a~b": [1, 2]}}).encode()
    path.write_bytes(payload)
    source = RoutingInputSource(
        path=path, sha256=hashlib.sha256(payload).hexdigest(), pointer="/fact~1one/a~0b/1"
    )
    assert source.read() == 2
    path.write_bytes(payload + b" ")
    with pytest.raises(ValueError, match="changed"):
        source.read()


@pytest.mark.parametrize("field,value", [("sha256", "bad"), ("pointer", "no-leading-slash")])
def test_invalid_source_rejected(field, value, tmp_path):
    args = dict(path=tmp_path / "source", sha256="0" * 64)
    args[field] = value
    with pytest.raises(ValueError):
        RoutingInputSource(**args)


def request(tmp_path):
    s = RoutingInputSource(path=tmp_path / "source", sha256="0" * 64)
    fields = {
        key: s
        for key in (
            "layout",
            "netlist",
            "profile",
            "examination",
            "context",
            "feasibility",
            "concept_drift",
            "engineering_gate",
            "budget_bindings",
            "pre_route_integrity",
        )
    }
    return RoutingPreparationRequest(
        transaction_root=tmp_path, expected_transaction_fingerprint="0" * 64, **fields
    )


@pytest.mark.parametrize("field", ["layout", "netlist", "profile", "routed_engineering_source"])
def test_canonical_inputs_cannot_be_reformatted_from_fragments(field, tmp_path):
    fields = request(tmp_path).model_dump()
    fields[field] = dict(path=tmp_path / "source", sha256="0" * 64, pointer="/part")
    with pytest.raises(ValueError, match="whole files"):
        RoutingPreparationRequest.model_validate(fields)


def test_no_overwrite_or_output_on_missing_generation(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must be new"):
        prepare_routing_inputs(request(tmp_path), existing)
    with pytest.raises(FileNotFoundError):
        prepare_routing_inputs(request(tmp_path), tmp_path / "new")
    assert not (tmp_path / "new").exists()

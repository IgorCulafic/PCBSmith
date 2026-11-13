"""Post-route declarations preserve the external search result and constraints."""

from dataclasses import replace

import pytest
from tests.unit.kicad.test_four_layer_logic import four_layer_request
from tests.unit.kicad.test_routing_external_adapters import _binding, _layout, _routed_layout

from pcbsmith.kicad.routing_external_adapters import (
    FREEROUTING_V2_3_0,
    ExternalProcessResult,
    run_freerouting_dsn_ses_candidate,
)
from pcbsmith.production_planes import PostRoutePlanePlan, append_post_route_planes
from pcbsmith.routing_ir import RouteNetLayerConstraint, RouteRequest


def plan(**updates):
    return PostRoutePlanePlan.model_validate(
        {
            "schema_id": "pcbsmith-post-route-inner-planes-v1",
            "net_name": "/SIG",
            "edge_inset_mm": 1,
            "reference_policy": {
                "schema_id": "pcbsmith-native-adjacent-reference-policy-v1",
                "layer_references": {"F.Cu": ("In1.Cu", "/SIG"), "B.Cu": ("In2.Cu", "/SIG")},
                "source_pad_ids": {"/SIG": ("pad:synthetic",)},
                "maximum_stitch_distance_mm": 2,
                "rationale": "Synthetic declaration fixture only.",
            },
            "rationale": "Synthetic declaration fixture only.",
            **updates,
        }
    )


@pytest.mark.parametrize("complete", [False, True])
def test_planes_never_modify_external_copper_logs_or_search_budget(tmp_path, monkeypatch, complete):
    request = four_layer_request(
        budget={
            "max_passes": 4,
            "max_expansions": 0,
            "max_expansions_per_net": 0,
            "max_stagnant_passes": 0,
            "max_exact_check_rejections": 0,
            "external_process_seconds": 10,
        }
    )
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(b"unit fixture only")

    def run(command, work, *, timeout_seconds):
        from pathlib import Path

        assert timeout_seconds == 10
        Path(command[command.index("-do") + 1]).write_bytes(b"synthetic session")
        return ExternalProcessResult(exit_code=0, stdout=b"test", stderr=b"", elapsed_seconds=1)

    monkeypatch.setattr("pcbsmith.kicad.routing_external_adapters.run_external_process", run)
    source = _layout()
    external = run_freerouting_dsn_ses_candidate(
        request=request,
        source_layout=source,
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_3_0,
        binding=_binding(jar),
        dsn_payload=b"synthetic",
        ses_importer=lambda p: _routed_layout(source),
        executor=run,
        completion_verifier=lambda: complete,
    )
    result = append_post_route_planes(request, external, source, plan())
    if not complete:
        assert result is external and not result.zone_deltas
    else:
        assert len(result.zone_deltas) == 2
        assert result.segment_deltas == external.segment_deltas
        assert result.via_deltas == external.via_deltas
        assert result.termination == external.termination
        assert result.run_telemetry == external.run_telemetry
        assert result.constraint_consumption == external.constraint_consumption
        assert result.engine.engine_id == external.engine.engine_id
        assert result.engine.executable_sha256 == external.engine.executable_sha256
        with pytest.raises(ValueError, match="zone-free"):
            append_post_route_planes(request, result, source, plan())


def test_plane_plan_refuses_unsupported_layers_conflicting_rules_and_empty_area():
    source, request = _layout(), four_layer_request()
    assert {z[1] for z in plan().zones(source, request)} == {"In1.Cu", "In2.Cu"}
    with pytest.raises(ValueError, match="four ordered"):
        plan().zones(
            source,
            RouteRequest.model_validate(
                {**request.model_dump(), "allowed_layers": ("F.Cu", "B.Cu")}
            ),
        )
    with pytest.raises(ValueError, match="net layer constraint"):
        plan().zones(
            source,
            request.model_copy(
                update={
                    "net_layer_constraints": (
                        RouteNetLayerConstraint(
                            constraint_id="outer-only",
                            net_names=("/SIG",),
                            allowed_layers=("F.Cu",),
                            allow_vias=False,
                        ),
                    )
                }
            ),
        )
    with pytest.raises(ValueError, match="leaves no area"):
        plan(edge_inset_mm=6).zones(source, request)
    with pytest.raises(ValueError, match="leaves no area"):
        plan().zones(replace(source, width_mm=1), request)


@pytest.mark.parametrize(
    "layer,reference",
    [("F.Cu", ("B.Cu", "/SIG")), ("B.Cu", ("In1.Cu", "/SIG")), ("B.Cu", ("In2.Cu", "OTHER"))],
)
def test_reference_roles_cannot_skip_adjacent_plane_or_change_reference_net(layer, reference):
    values = plan().model_dump()
    values["reference_policy"]["layer_references"][layer] = reference
    with pytest.raises(ValueError, match="adjacent inner references"):
        PostRoutePlanePlan.model_validate(values)

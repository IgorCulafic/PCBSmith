"""Software-only policy inputs. Never use as board review/qualification evidence."""

import json

from pcbsmith.mandatory_review import APPLICABILITY_TOPICS, COMPONENT_TOPICS, MandatoryReview
from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.predesign_contract import artifact_sha256
from pcbsmith.production_readiness import ReadinessEvidenceFile


def policy_fixture(bundle, component_sha):
    return MandatoryReview(
        brief_sha256=artifact_sha256(bundle.approval.amended_brief),
        component_readiness_sha256=component_sha,
        reviewer="synthetic-test",
        review_reference="unit-test-only",
        applicability={
            key: {
                "disposition": "not_applicable",
                "rationale": "Synthetic passive adapter fixture excludes this feature.",
                "evidence_ids": ["fixture:source"],
            }
            for key in APPLICABILITY_TOPICS
        },
        components={
            p.component_id: {
                "observations": {
                    key: "Synthetic software input; no actual engineering approval."
                    for key in COMPONENT_TOPICS
                },
                "evidence_ids": ["fixture:source"],
            }
            for p in bundle.approval.amended_brief.draft.components
        },
        deliverables={
            role: "fixture"
            for role in (
                "pcb",
                "schematic",
                "project",
                "interactive_bom",
                "floorplan",
                "floorplan_preview",
            )
        },
        required_native_rules={"erc": ["pin_not_connected"], "drc": ["clearance"]},
        minimum_board_rules={
            "min_clearance": 0.1,
            "min_track_width": 0.1,
            "min_copper_edge_clearance": 0.1,
        },
    )


def bind_mandatory_fixture(bundle, evidence, preflight):
    vectors = {}
    for name in ("floorplan.svg", "floorplan.png"):
        path = evidence / name
        path.write_bytes(b"synthetic inner-contract vector fixture, not visual approval")
        vectors["floorplan." + name] = ReadinessEvidenceFile(
            relative_path=name, sha256=file_sha256(path)
        )
    component = evidence / "component-readiness.json"
    component.write_text(
        json.dumps(
            {
                "schema_id": "pcbsmith-preplacement-component-readiness-v1",
                "selected_models": {
                    "status": "not_applicable",
                    "policy": {
                        "applicability": "not_applicable",
                        "rationale": "Synthetic 2D adapter control",
                    },
                    "assessment": {
                        key: getattr(preflight, key)
                        for key in (
                            "status",
                            "applicability",
                            "applicability_rationale",
                            "models",
                            "required_references",
                            "findings",
                        )
                    },
                },
            }
        )
    )
    return rebind_mandatory_fixture(
        bundle.model_copy(
            update={
                "evidence_files": {
                    **bundle.evidence_files,
                    **vectors,
                    "component-readiness": ReadinessEvidenceFile(
                        relative_path=component.name, sha256=file_sha256(component)
                    ),
                }
            }
        ),
        evidence,
    )


def rebind_mandatory_fixture(bundle, evidence):
    policy = policy_fixture(bundle, bundle.evidence_files["component-readiness"].sha256)
    path = evidence / "mandatory-review.json"
    path.write_text(policy.model_dump_json(indent=2))
    return bundle.model_copy(
        update={
            "evidence_files": {
                **bundle.evidence_files,
                "mandatory-review": ReadinessEvidenceFile(
                    relative_path=path.name, sha256=file_sha256(path)
                ),
            }
        }
    )

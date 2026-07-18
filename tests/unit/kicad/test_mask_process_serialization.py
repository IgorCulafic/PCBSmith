from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNet,
    BoardNetlist,
    ViaSpec,
    render_board_from_layout,
)
from pcbsmith.kicad.export_divider_highpass_led import _render_project
from pcbsmith.mask_geometry import ViaMaskIntent
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    FabricationGeometryProfile,
    PcbRuleProfile,
)

DEFAULT_VIA_LINE = (
    '  (via (at 24 22) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") '
    '(tenting (front none) (back none)) (net "/N") '
    "(uuid 2df4ebf6-ffc8-5c7e-8164-90f0e48454a5))"
)


def _profile(
    *,
    expansion_mm: float | None = None,
    minimum_web_mm: float | None = None,
) -> PcbRuleProfile:
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={
            "default_pad_solder_mask_expansion_mm": expansion_mm,
            "minimum_solder_mask_web_mm": minimum_web_mm,
        }
    )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})


def _board_text(
    *,
    vias: tuple[ViaSpec, ...] = (),
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> str:
    netlist = BoardNetlist(
        components=(),
        nets=(BoardNet(name="/N", nodes=()),),
    )
    layout = BoardLayout(
        placements=(),
        segments=(),
        vias=vias,
        width_mm=10.0,
        height_mm=10.0,
    )
    return render_board_from_layout(netlist, layout, profile=profile)


@pytest.mark.parametrize("value", (-0.05, 0.0, 0.2))
def test_mask_expansion_profile_accepts_finite_signed_values(value: float) -> None:
    geometry = FabricationGeometryProfile(
        profile_id="mask-expansion",
        default_pad_solder_mask_expansion_mm=value,
    )

    assert geometry.default_pad_solder_mask_expansion_mm == value


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_mask_expansion_profile_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValidationError):
        FabricationGeometryProfile(
            profile_id="invalid-mask-expansion",
            default_pad_solder_mask_expansion_mm=value,
        )


def test_board_setup_is_absent_by_default_and_exact_when_declared() -> None:
    default_text = _board_text()
    declared_text = _board_text(profile=_profile(expansion_mm=-0.05))

    assert DEFAULT_PCB_RULE_PROFILE.geometry.default_pad_solder_mask_expansion_mm is None
    assert "pad_to_mask_clearance" not in default_text
    assert "\n\n  (setup\n    (pad_to_mask_clearance -0.05)\n  )" in declared_text


def test_project_mirrors_mask_constraints_without_claiming_plot_authority() -> None:
    profile = _profile(expansion_mm=0.2, minimum_web_mm=0.1)
    rules = json.loads(_render_project(profile=profile))["board"]["design_settings"]["rules"]

    assert rules["solder_mask_clearance"] == 0.2
    assert rules["solder_mask_min_width"] == 0.1
    assert _board_text(profile=_profile(minimum_web_mm=0.1)) == _board_text()


def test_default_via_intent_serializes_explicit_inherit_fixture() -> None:
    via = ViaSpec(4.0, 2.0, "/N")
    first = _board_text(vias=(via,))
    second = _board_text(vias=(via,))
    via_line = next(line for line in first.splitlines() if "(via " in line)

    assert via.front_mask is ViaMaskIntent.INHERIT
    assert via.back_mask is ViaMaskIntent.INHERIT
    assert first == second
    assert via_line == DEFAULT_VIA_LINE


@pytest.mark.parametrize(
    ("front", "back", "front_token", "back_token"),
    (
        (ViaMaskIntent.OPEN, ViaMaskIntent.TENTED, "no", "yes"),
        (ViaMaskIntent.TENTED, ViaMaskIntent.INHERIT, "yes", "none"),
    ),
)
def test_via_mask_intent_uses_verified_kicad_tokens(
    front: ViaMaskIntent,
    back: ViaMaskIntent,
    front_token: str,
    back_token: str,
) -> None:
    text = _board_text(
        vias=(
            ViaSpec(
                4.0,
                2.0,
                "/N",
                front_mask=front,
                back_mask=back,
            ),
        )
    )

    assert f"(tenting (front {front_token}) (back {back_token}))" in text


def test_via_mask_intent_participates_in_stable_semantic_identity() -> None:
    inherited = _board_text(vias=(ViaSpec(4.0, 2.0, "/N"),))
    opened = _board_text(
        vias=(
            ViaSpec(
                4.0,
                2.0,
                "/N",
                front_mask=ViaMaskIntent.OPEN,
            ),
        )
    )
    uuid_pattern = re.compile(r"\(via .+\(uuid ([0-9a-f-]+)\)\)")

    inherited_uuid = uuid_pattern.search(inherited)
    opened_uuid = uuid_pattern.search(opened)
    assert inherited_uuid is not None
    assert opened_uuid is not None
    assert inherited_uuid.group(1) != opened_uuid.group(1)
    assert opened == _board_text(
        vias=(
            ViaSpec(
                4.0,
                2.0,
                "/N",
                front_mask=ViaMaskIntent.OPEN,
            ),
        )
    )

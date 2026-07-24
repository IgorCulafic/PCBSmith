"""Route the approved Retro-Pad R003 placement with recoverable checkpoints."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from pcbsmith.kicad.board import BoardLayout, parse_board_netlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    parse_canonical_board_layout_snapshot,
)
from pcbsmith.kicad.retro_pad_board import (
    render_retro_pad_board,
    route_retro_pad_placement_layout,
)
from pcbsmith.kicad.retro_pad_r003_board import (
    _prune_unused_isp_fanout,
    _repair_usb_dp_clearance,
    _seed_isp_fanout,
    _seed_usb_c_fanout,
    compute_retro_pad_r003_placement_layout,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "retro-pad-r003"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resume-after-led", action="store_true")
    parser.add_argument("--resume-after-reset", action="store_true")
    parser.add_argument("--skip-ground", action="store_true")
    parser.add_argument(
        "--ripup-net",
        action="append",
        default=[],
        help="On resume, remove an exact net's tracks/vias and route it again.",
    )
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    netlist = parse_board_netlist(
        (OUTPUT / ".pcbsmith/kicad/retro-pad-r003.net.xml").read_text(
            encoding="utf-8"
        )
    )
    if args.resume:
        placement = parse_canonical_board_layout_snapshot(
            (OUTPUT / "routing-checkpoint.layout.json").read_text(encoding="utf-8")
        )
        completed_net_names = set(
            json.loads(
                (OUTPUT / "routing-checkpoint.completed-nets.json").read_text(
                    encoding="utf-8"
                )
            )
        )
    elif args.resume_after_led or args.resume_after_reset:
        placement = parse_canonical_board_layout_snapshot(
            (OUTPUT / "routing-checkpoint.layout.json").read_text(encoding="utf-8")
        )
        completed_net_names = {
            "/VBUS_RAW",
            "/USB_DP_CONN",
            "/USB_DM_CONN",
            "/USB_DM_PROTECTED",
            "/USB_DP_PROTECTED",
            "/CC1",
            "/CC2",
            "/USB_DM_MCU",
            "/USB_DP_MCU",
            "/ROW0",
            "/ROW1",
            "/COL0",
            "/COL1",
            "/LED_DATA_MCU",
            "/LED_DATA_1",
            "/LED_LINK_1",
            "/LED_LINK_2",
            "/LED_LINK_3",
        }
        if args.resume_after_reset:
            completed_net_names.update(
                {
                    "/VCC",
                    "/XTAL1",
                    "/XTAL2",
                    "/UCAP",
                    "/AREF",
                    "/HWB",
                    "/ENC_A",
                    "/ENC_B",
                    "/ENC_SW",
                    "/RESET",
                }
            )
    else:
        placement = compute_retro_pad_r003_placement_layout(
            netlist,
            outline_file=OUTPUT / "input/board_outline.png",
            silkscreen_file=OUTPUT / "input/silkscreen_art.png",
        )
        placement = _seed_usb_c_fanout(placement)
        placement = _seed_isp_fanout(placement)
        completed_net_names = {
            "/VBUS_RAW",
            "/USB_DP_CONN",
            "/USB_DM_CONN",
        }
    if args.resume or args.resume_after_led or args.resume_after_reset:
        authoritative = compute_retro_pad_r003_placement_layout(
            netlist,
            outline_file=OUTPUT / "input/board_outline.png",
            silkscreen_file=OUTPUT / "input/silkscreen_art.png",
        )
        checkpoint_geometry = (
            placement.placements,
            placement.part_y_mm,
            placement.part_rotation,
            placement.part_flip,
            placement.outline,
            placement.cutouts,
        )
        authoritative_geometry = (
            authoritative.placements,
            authoritative.part_y_mm,
            authoritative.part_rotation,
            authoritative.part_flip,
            authoritative.outline,
            authoritative.cutouts,
        )
        if checkpoint_geometry != authoritative_geometry:
            raise SystemExit(
                "routing checkpoint placement is stale; restart without --resume"
            )
        placement = replace(
            placement,
            graphics=authoritative.graphics,
            hide_references=authoritative.hide_references,
            part_reference_at=authoritative.part_reference_at,
        )
    placement = _repair_usb_dp_clearance(placement)
    ripup_nets = set(args.ripup_net)
    if ripup_nets:
        if not args.resume:
            raise SystemExit("--ripup-net requires --resume")
        unknown_ripup = ripup_nets - completed_net_names
        if unknown_ripup:
            raise SystemExit(
                "cannot rip up nets absent from the checkpoint: "
                + ", ".join(sorted(unknown_ripup))
            )
        placement = replace(
            placement,
            segments=tuple(
                segment
                for segment in placement.segments
                if segment.net_name not in ripup_nets
            ),
            vias=tuple(
                via for via in placement.vias if via.net_name not in ripup_nets
            ),
        )
        completed_net_names -= ripup_nets

    def checkpoint(
        label: str,
        layout: BoardLayout,
        completed: frozenset[str],
    ) -> None:
        snapshot = canonical_board_layout_snapshot_json(layout)
        (OUTPUT / "routing-checkpoint.layout.json").write_text(
            snapshot,
            encoding="utf-8",
        )
        (OUTPUT / "routing-checkpoint.kicad_pcb").write_text(
            render_retro_pad_board(netlist, layout),
            encoding="utf-8",
        )
        (OUTPUT / "routing-checkpoint.completed-nets.json").write_text(
            json.dumps(sorted(completed), indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"CHECKPOINT {label}: "
            f"{len(layout.segments)} segments, {len(layout.vias)} vias",
            flush=True,
        )

    routed = route_retro_pad_placement_layout(
        placement,
        netlist,
        maximum_expansions=5_000_000,
        maximum_passes=500,
        maximum_expansions_per_net=5_000_000,
        route_ground_before_power=True,
        route_ground_before_matrix=True,
        route_clock_before_power=True,
        route_led_before_power=False,
        route_power_before_matrix=False,
        checkpoint_observer=checkpoint,
        completed_net_names=completed_net_names,
        route_ground_tracks=not args.skip_ground,
    )
    routed = _prune_unused_isp_fanout(routed)
    candidate = OUTPUT / "retro-pad-r003-routing-candidate.kicad_pcb"
    candidate.write_text(render_retro_pad_board(netlist, routed), encoding="utf-8")
    (OUTPUT / "routing-checkpoint.layout.json").write_text(
        canonical_board_layout_snapshot_json(routed),
        encoding="utf-8",
    )
    print(
        f"COMPLETE {candidate}: "
        f"{len(routed.segments)} segments, {len(routed.vias)} vias",
        flush=True,
    )


if __name__ == "__main__":
    main()

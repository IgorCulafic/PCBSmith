"""KiCad pcbnew bridge for Specctra DSN/SES exchange and read-back."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pcbnew


def _read_width_rules(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Width-rule JSON must be an object")
    return {str(name): float(width) for name, width in payload.items()}


def _apply_width_rules(
    board: pcbnew.BOARD, rules: dict[str, float], clearance_mm: float = 0.2
) -> None:
    settings = board.GetDesignSettings().m_NetSettings
    for width in sorted(set(rules.values())):
        class_name = f"PCBSMITH_{width:.3f}MM".replace(".", "_")
        netclass = pcbnew.NETCLASS(class_name)
        netclass.SetTrackWidth(pcbnew.FromMM(width))
        netclass.SetClearance(pcbnew.FromMM(clearance_mm))
        settings.SetNetclass(class_name, netclass)
        for net_name, requested_width in sorted(rules.items()):
            if requested_width == width:
                settings.SetNetclassPatternAssignment(net_name, class_name)
    settings.RecomputeEffectiveNetclasses()


def export_dsn(
    source: Path, output: Path, width_rules_json: Path | None = None, clearance_mm: float = 0.2
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    board = pcbnew.LoadBoard(str(source))
    if width_rules_json is not None:
        _apply_width_rules(board, _read_width_rules(width_rules_json), clearance_mm)
    if not pcbnew.ExportSpecctraDSN(board, str(output)):
        raise RuntimeError("KiCad failed to export Specctra DSN")


def import_ses(source: Path, session: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    board = pcbnew.LoadBoard(str(source))
    if not pcbnew.ImportSpecctraSES(board, str(session)):
        raise RuntimeError("KiCad failed to import the Specctra SES")
    pcbnew.SaveBoard(str(output), board)


def inspect_widths(board_path: Path, width_rules_json: Path, output: Path) -> None:
    board = pcbnew.LoadBoard(str(board_path))
    rules = _read_width_rules(width_rules_json)
    observed: dict[str, list[float]] = {name: [] for name in rules}
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA):
            continue
        name = str(item.GetNetname())
        if name in observed:
            observed[name].append(round(float(pcbnew.ToMM(item.GetWidth())), 6))
    signal_floor = min(rules.values())
    records: dict[str, object] = {}
    driven_total = 0
    driven_accepted = 0
    for name, requested in sorted(rules.items()):
        widths = observed[name]
        counts = Counter(widths)
        preferred_present = any(abs(width - requested) <= 0.001 for width in widths)
        width_driven = requested > signal_floor + 0.001
        if width_driven:
            driven_total += 1
            driven_accepted += int(preferred_present)
        records[name] = {
            "requested_width_mm": requested,
            "segment_count": len(widths),
            "observed_width_counts": {
                f"{width:.6f}": count for width, count in sorted(counts.items())
            },
            "minimum_observed_width_mm": min(widths) if widths else None,
            "maximum_observed_width_mm": max(widths) if widths else None,
            "preferred_width_present": preferred_present,
            "width_driven": width_driven,
            "narrower_segment_count": sum(width < requested - 0.001 for width in widths),
        }
    payload = {
        "schema": "pcbsmith-route-width-observation-v1",
        "signal_floor_mm": signal_floor,
        "width_driven_net_count": driven_total,
        "width_driven_accepted_count": driven_accepted,
        "width_intent_accepted": driven_total == driven_accepted,
        "nets": records,
        "acceptance_boundary": (
            "A width-driven net must contain its requested width. Shorter neck-down "
            "segments are retained and counted, not silently treated as full-width copper."
        ),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("source", type=Path)
    export_parser.add_argument("output", type=Path)
    export_parser.add_argument("--width-rules-json", type=Path)
    export_parser.add_argument("--clearance-mm", type=float, default=0.2)
    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("session", type=Path)
    import_parser.add_argument("output", type=Path)
    inspect_parser = subparsers.add_parser("inspect-widths")
    inspect_parser.add_argument("board", type=Path)
    inspect_parser.add_argument("width_rules_json", type=Path)
    inspect_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        width_rules = args.width_rules_json.resolve() if args.width_rules_json else None
        export_dsn(args.source.resolve(), args.output.resolve(), width_rules, args.clearance_mm)
    elif args.command == "import":
        import_ses(args.source.resolve(), args.session.resolve(), args.output.resolve())
    else:
        inspect_widths(
            args.board.resolve(),
            args.width_rules_json.resolve(),
            args.output.resolve(),
        )


if __name__ == "__main__":
    main()

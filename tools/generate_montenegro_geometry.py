"""Generate the source-hashed Montenegro outline feasibility contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pcbsmith.kicad.montenegro_geometry import (
    build_montenegro_geometry,
    write_geometry_contract,
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "outputs" / "montenegro-env-display-r001" / "geometry.json",
    )
    args = parser.parse_args()
    geometry = build_montenegro_geometry(args.source)
    write_geometry_contract(geometry, args.output)
    print(json.dumps(geometry.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

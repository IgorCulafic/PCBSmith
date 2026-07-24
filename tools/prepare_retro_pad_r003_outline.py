"""Normalize the supplied diagonal dog-bone silhouette for Retro-Pad R003.

The source artwork is a square, diagonal, transparent PNG.  Rotating it
horizontally and scaling it uniformly would produce a board about 75 mm tall.
R003 instead preserves both rounded end lobes and lengthens only the narrow
middle span, yielding the approved 145 mm x 55 mm engineering envelope.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target-aspect", type=float, default=145.0 / 55.0)
    parser.add_argument("--canvas-height", type=int, default=1100)
    return parser.parse_args()


def normalize_outline(
    source: Path,
    output: Path,
    *,
    target_aspect: float,
    canvas_height: int,
) -> tuple[int, int]:
    image = Image.open(source).convert("RGBA")
    horizontal = image.rotate(-45, expand=True, resample=Image.Resampling.BICUBIC)
    alpha = horizontal.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError(f"No non-transparent silhouette in {source}")
    silhouette = horizontal.crop(bounds)

    source_width, source_height = silhouette.size
    target_width = round(source_height * target_aspect)
    if target_width <= source_width:
        raise ValueError("Target aspect must lengthen the source silhouette")

    # Preserve the outer 30% of each end, where the four circular lobes live,
    # and stretch only the middle waist.  This avoids the oval switch lobes
    # produced by ordinary non-uniform scaling.
    end_width = round(source_width * 0.30)
    middle_left = end_width
    middle_right = source_width - end_width
    middle_target_width = target_width - 2 * end_width
    left = silhouette.crop((0, 0, middle_left, source_height))
    middle = silhouette.crop((middle_left, 0, middle_right, source_height)).resize(
        (middle_target_width, source_height), Image.Resampling.BICUBIC
    )
    right = silhouette.crop((middle_right, 0, source_width, source_height))

    elongated = Image.new("RGBA", (target_width, source_height), (0, 0, 0, 0))
    elongated.alpha_composite(left, (0, 0))
    elongated.alpha_composite(middle, (end_width, 0))
    elongated.alpha_composite(right, (end_width + middle_target_width, 0))

    scale = canvas_height / source_height
    canvas_width = round(target_width * scale)
    normalized = elongated.resize(
        (canvas_width, canvas_height), Image.Resampling.LANCZOS
    )
    # Make the traced silhouette unambiguous: opaque black board, transparent
    # exterior.  RGB data from the source is intentionally discarded.
    result = Image.new("RGBA", normalized.size, (0, 0, 0, 0))
    result.putalpha(normalized.getchannel("A"))
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output)
    return result.size


def main() -> int:
    args = _parse_args()
    size = normalize_outline(
        args.source,
        args.output,
        target_aspect=args.target_aspect,
        canvas_height=args.canvas_height,
    )
    print(f"{args.output}: {size[0]} x {size[1]} px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

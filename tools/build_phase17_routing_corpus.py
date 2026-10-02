from __future__ import annotations

import argparse
from pathlib import Path

from pcbsmith.kicad.routing_benchmark_corpus import write_routing_benchmark_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Phase 17 forty-board corpus")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/phase17-routing-corpus-40"),
    )
    parser.add_argument("--route-native", action="store_true")
    parser.add_argument("--max-expansions", type=int, default=150_000)
    parser.add_argument("--max-expansions-per-net", type=int, default=30_000)
    args = parser.parse_args()
    summary = write_routing_benchmark_corpus(
        args.output.resolve(),
        route_native=args.route_native,
        max_expansions=args.max_expansions,
        max_expansions_per_net=args.max_expansions_per_net,
    )
    print(f"Generated {summary['case_count']} routing benchmark boards in {args.output}")
    if args.route_native:
        print(f"Native successes: {summary['native_success_count']}")


if __name__ == "__main__":
    main()

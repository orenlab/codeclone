"""CLI entrypoints for the review kit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from review_kit.coverage import check_coverage
from review_kit.packet import build_packet, write_packet
from review_kit.validate import validate_document, validate_packet


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    return loaded


def cmd_build_packet(args: argparse.Namespace) -> int:
    prior_packet = None
    if args.prior_packet:
        prior_packet = _load_json(Path(args.prior_packet))
    packet = build_packet(
        args.mode,
        args.target,
        profile=args.profile,
        incremental_from=args.incremental_from,
        prior_packet=prior_packet,
        execute_verification=args.execute_verification,
    )
    if args.validate:
        errors = validate_packet(packet)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
    out = write_packet(packet, Path(args.out))
    print(out)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    errors = validate_document(Path(args.path))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Valid: {args.path}")
    return 0


def cmd_check_coverage(args: argparse.Namespace) -> int:
    return check_coverage(docs_full=args.docs)


def cmd_dry_run(args: argparse.Namespace) -> int:
    packet = build_packet(args.mode, args.target, profile=args.profile)
    routing = packet.get("routing", {})
    change = packet.get("change", {})
    scale = change.get("review_scale", {})
    print("packet_version:", packet.get("packet_version"))
    print("profile:", routing.get("profile"), routing.get("profile_reason"))
    print("coordinator:", routing.get("coordinator_model"))
    print("decomposed:", routing.get("decomposed"))
    print("units:", len(packet.get("review_units", [])))
    print("unmapped:", len(change.get("unmapped_paths", [])))
    print("large:", scale.get("large"), scale.get("reasons"))
    print("cost_weight:", packet.get("cost_estimate", {}).get("relative_weight"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-kit")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-packet", help="Build review packet v3")
    build.add_argument("mode", choices=("commit", "range", "release"))
    build.add_argument("target")
    build.add_argument("--out", required=True)
    build.add_argument("--profile", choices=("economy", "balanced", "thorough"))
    build.add_argument("--incremental-from")
    build.add_argument("--prior-packet")
    build.add_argument("--execute-verification", action="store_true")
    build.add_argument("--validate", action="store_true")
    build.set_defaults(func=cmd_build_packet)

    validate = sub.add_parser("validate", help="Validate packet or artifact JSON")
    validate.add_argument("path")
    validate.set_defaults(func=cmd_validate)

    coverage = sub.add_parser(
        "check-coverage", help="Validate surface catalog coverage"
    )
    coverage.add_argument("--docs", action="store_true")
    coverage.set_defaults(func=cmd_check_coverage)

    dry = sub.add_parser("dry-run", help="Print routing summary without writing packet")
    dry.add_argument("mode", choices=("commit", "range", "release"))
    dry.add_argument("target")
    dry.add_argument("--profile", choices=("economy", "balanced", "thorough"))
    dry.set_defaults(func=cmd_dry_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

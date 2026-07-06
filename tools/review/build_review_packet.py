#!/usr/bin/env python3
"""Build review packet v3 (legacy argv: MODE TARGET --out PATH)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_review_kit_path() -> None:
    review_root = Path(__file__).resolve().parent
    root_str = str(review_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def main() -> None:
    _ensure_review_kit_path()
    from review_kit.packet import build_packet, write_packet

    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("commit", "range", "release"))
    parser.add_argument("target")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    packet = build_packet(args.mode, args.target)
    out = write_packet(packet, Path(args.out))
    print(out)


if __name__ == "__main__":
    main()

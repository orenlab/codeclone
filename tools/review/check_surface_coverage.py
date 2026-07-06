#!/usr/bin/env python3
"""Validate surface catalog coverage for tracked paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_review_kit_path() -> None:
    review_root = Path(__file__).resolve().parent
    root_str = str(review_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def main() -> int:
    _ensure_review_kit_path()
    from review_kit.coverage import check_coverage

    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", action="store_true")
    args = parser.parse_args()
    return check_coverage(docs_full=args.docs)


if __name__ == "__main__":
    raise SystemExit(main())

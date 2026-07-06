"""Validate tracked repository paths map to policy surface_catalog."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from review_kit.policy import (
    classify_path,
    is_protected,
    load_policy,
    skip_docs_path,
    surface_catalog,
)


def tracked_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def unmapped_tracked_paths(
    policy: dict[str, Any] | None = None,
    *,
    docs_mode: str | None = None,
) -> list[str]:
    loaded = policy or load_policy()
    catalog = surface_catalog(loaded)
    if docs_mode is None:
        from review_kit.policy import docs_review_mode

        docs_mode = docs_review_mode(loaded)
    unknown: list[str] = []
    for path in tracked_paths():
        if is_protected(path, loaded):
            continue
        if skip_docs_path(path, docs_mode=docs_mode):
            continue
        if not classify_path(path, catalog):
            unknown.append(path)
    return unknown


def check_coverage(*, docs_full: bool = False) -> int:
    policy = load_policy()
    docs_mode = (
        "full"
        if docs_full
        else policy.get("docs_review", {}).get("mode", "transitional")
    )
    if docs_full:
        docs_mode = "full"
    elif not isinstance(docs_mode, str):
        docs_mode = "transitional"
    unknown = unmapped_tracked_paths(policy, docs_mode=docs_mode)
    if unknown:
        print("Unmapped tracked paths:", file=sys.stderr)
        for path in unknown:
            print(f"  - {path}", file=sys.stderr)
        return 1
    print("Surface coverage OK for tracked repository paths.")
    return 0

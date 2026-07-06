"""Incremental review helpers against a prior packet head SHA."""

from __future__ import annotations

from typing import Any

from review_kit.git_evidence import changed_files, collect_paths, is_ancestor


def build_incremental(
    *,
    from_sha: str | None,
    base_sha: str,
    head_sha: str,
    prior_units: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if not from_sha:
        return {"enabled": False}

    if not is_ancestor(from_sha, head_sha):
        return {
            "enabled": True,
            "from_sha": from_sha,
            "status": "incompatible",
            "reason": "from_sha is not an ancestor of head_sha",
            "skipped_units": [],
            "reused_units": [],
        }

    delta_files = changed_files(from_sha, head_sha)
    delta_paths = set(collect_paths(delta_files))
    skipped: list[str] = []
    reused: list[str] = []
    if prior_units:
        for unit in prior_units:
            unit_id = str(unit.get("unit_id", ""))
            unit_paths = [str(path) for path in unit.get("paths", [])]
            if unit_paths and not any(path in delta_paths for path in unit_paths):
                skipped.append(unit_id)
            else:
                reused.append(unit_id)

    return {
        "enabled": True,
        "from_sha": from_sha,
        "status": "ok",
        "delta_paths": sorted(delta_paths),
        "skipped_units": skipped,
        "reused_units": reused,
        "review_from": f"{from_sha}..{head_sha}",
    }

"""Surface routing helpers for review packets."""

from __future__ import annotations

from typing import Any

from review_kit.git_evidence import collect_paths
from review_kit.policy import (
    classify_path,
    docs_paths_reviewable,
    skip_docs_path,
)


def _append_surface_path(result: dict[str, list[str]], surface: str, path: str) -> None:
    bucket = result.setdefault(surface, [])
    if path not in bucket:
        bucket.append(path)


def surface_hints(
    files: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in collect_paths(files):
        for surface in classify_path(path, catalog):
            _append_surface_path(result, surface, path)
    for name in result:
        result[name].sort()
    return dict(sorted(result.items()))


def unmapped_paths(
    files: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
    *,
    docs_mode: str,
) -> list[str]:
    unknown: list[str] = []
    for path in sorted(set(collect_paths(files))):
        if skip_docs_path(path, docs_mode=docs_mode):
            continue
        if not classify_path(path, catalog):
            unknown.append(path)
    return unknown


def review_scale(
    *,
    mode: str,
    commits: list[dict[str, str]],
    stats: dict[str, int],
    policy: dict[str, Any],
) -> dict[str, Any]:
    thresholds = policy.get("large_range_review", {}).get("thresholds", {})
    commit_threshold = int(thresholds.get("commits", 10))
    file_threshold = int(thresholds.get("changed_files", 50))
    line_threshold = int(thresholds.get("changed_lines", 2000))
    changed_lines = stats["insertions"] + stats["deletions"]
    reasons: list[str] = []
    if len(commits) >= commit_threshold:
        reasons.append(f"commit_count={len(commits)}>={commit_threshold}")
    if stats["files"] >= file_threshold:
        reasons.append(f"changed_files={stats['files']}>={file_threshold}")
    if changed_lines >= line_threshold:
        reasons.append(f"changed_lines={changed_lines}>={line_threshold}")
    large = bool(reasons)
    decompose_large_commits = bool(
        policy.get("large_range_review", {}).get("decompose_large_commits", True)
    )
    decompose_recommended = large and (
        mode in {"range", "release"} or decompose_large_commits
    )
    return {
        "large": large,
        "decompose_recommended": decompose_recommended,
        "reasons": reasons,
        "thresholds": {
            "commits": commit_threshold,
            "changed_files": file_threshold,
            "changed_lines": line_threshold,
        },
    }


def release_section(mode: str, policy: dict[str, Any]) -> dict[str, Any]:
    release_policy = policy.get("release_mode", {})
    if mode != "release":
        return {"enabled": False}
    extra_vectors = release_policy.get("activates_extra_vectors", [])
    mandatory = release_policy.get("mandatory_verification_when_touched", {})
    return {
        "enabled": True,
        "activates_extra_vectors": list(extra_vectors)
        if isinstance(extra_vectors, list)
        else [],
        "mandatory_verification_when_touched": mandatory
        if isinstance(mandatory, dict)
        else {},
    }


def docs_review_section(policy: dict[str, Any]) -> dict[str, Any]:
    docs = policy.get("docs_review", {})
    mode = "transitional"
    note = ""
    if isinstance(docs, dict):
        raw_mode = docs.get("mode")
        if isinstance(raw_mode, str):
            mode = raw_mode
        note = str(docs.get("transitional_note", ""))
    return {
        "mode": mode,
        "enabled": docs_paths_reviewable(mode),
        "note": note,
    }

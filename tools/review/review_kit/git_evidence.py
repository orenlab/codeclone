"""Immutable Git evidence for review packets."""

from __future__ import annotations

import subprocess
from typing import Any

_EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def run(*args: str) -> str:
    completed = subprocess.run(args, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _normalize_ref(ref: str) -> str:
    stripped = ref.strip()
    if not stripped or stripped.startswith("-"):
        raise SystemExit(f"Invalid git ref: {ref!r}")
    return stripped


def _rev_parse_commit(ref: str) -> str:
    normalized = _normalize_ref(ref)
    return run("git", "rev-parse", "--verify", f"{normalized}^{{commit}}")


def commit_parent(head: str) -> str:
    try:
        return run("git", "rev-parse", "--verify", f"{head}^")
    except subprocess.CalledProcessError:
        return _EMPTY_TREE_SHA


def maybe_use_merge_base(base: str, head: str) -> tuple[str, bool]:
    parent_count = int(run("git", "rev-list", "--count", "--parents", "-n", "1", head))
    if parent_count <= 1:
        return base, False
    merge_base = run("git", "merge-base", base, head)
    if not merge_base:
        return base, False
    return merge_base, True


def resolve_target(mode: str, target: str) -> tuple[str, str, str, bool]:
    if mode == "commit":
        head = _rev_parse_commit(target)
        base = commit_parent(head)
        return base, head, f"{base}..{head}", False

    if ".." not in target:
        raise SystemExit(f"{mode} target must be BASE..HEAD")
    raw_base, raw_head = target.split("..", 1)
    base = _rev_parse_commit(raw_base)
    head = _rev_parse_commit(raw_head)
    base, merge_base_used = maybe_use_merge_base(base, head)
    return base, head, f"{base}..{head}", merge_base_used


def _parse_name_status_line(line: str) -> dict[str, Any] | None:
    parts = line.split("\t")
    if not parts:
        return None
    status = parts[0]
    if status.startswith("R") and len(parts) >= 3:
        return {"status": status, "old_path": parts[1], "path": parts[2]}
    if len(parts) >= 2:
        return {"status": status, "path": parts[1]}
    return None


def changed_files(base: str, head: str) -> list[dict[str, Any]]:
    raw = run("git", "diff", "--name-status", "--find-renames", base, head)
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parsed = _parse_name_status_line(line)
        if parsed is not None:
            result.append(parsed)
    return result


def diff_stats(base: str, head: str) -> dict[str, int]:
    raw = run("git", "diff", "--numstat", base, head)
    insertions = deletions = files = 0
    if raw:
        for line in raw.splitlines():
            added, removed, _path = line.split("\t", 2)
            files += 1
            if added.isdigit():
                insertions += int(added)
            if removed.isdigit():
                deletions += int(removed)
    return {"files": files, "insertions": insertions, "deletions": deletions}


def diff_stats_for_paths(base: str, head: str, paths: list[str]) -> dict[str, int]:
    if not paths:
        return {"files": 0, "insertions": 0, "deletions": 0}
    raw = run("git", "diff", "--numstat", base, head, "--", *paths)
    insertions = deletions = files = 0
    if raw:
        for line in raw.splitlines():
            added, removed, _path = line.split("\t", 2)
            files += 1
            if added.isdigit():
                insertions += int(added)
            if removed.isdigit():
                deletions += int(removed)
    return {"files": files, "insertions": insertions, "deletions": deletions}


def commit_inventory(base: str, head: str) -> list[dict[str, str]]:
    raw = run("git", "log", "--reverse", "--format=%H%x09%P%x09%s", f"{base}..{head}")
    if not raw:
        return []
    commits: list[dict[str, str]] = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        sha, parents, subject = parts
        commits.append({"sha": sha, "parents": parents, "subject": subject})
    return commits


def collect_paths(files: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in files:
        path = str(item.get("path", "")).strip()
        if path:
            paths.append(path)
        old_path = str(item.get("old_path", "")).strip()
        if old_path:
            paths.append(old_path)
    return paths


def is_ancestor(ancestor: str, descendant: str) -> bool:
    try:
        run("git", "merge-base", "--is-ancestor", ancestor, descendant)
        return True
    except subprocess.CalledProcessError:
        return False

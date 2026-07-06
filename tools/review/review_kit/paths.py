"""Repository path glob matching for surface routing."""

from __future__ import annotations

from fnmatch import fnmatch


def normalized_repo_path(path: str) -> str:
    return path.replace("\\", "/")


def _matches_dir_glob(normalized: str, prefix: str) -> bool:
    base = prefix.rstrip("/")
    return normalized == base or normalized.startswith(f"{base}/")


def _matches_recursive_glob(normalized: str, suffix: str) -> bool:
    return fnmatch(normalized, f"*{suffix}") or normalized.endswith(suffix)


def path_matches(path: str, pattern: str) -> bool:
    normalized = normalized_repo_path(path)
    if pattern.endswith("/**"):
        return _matches_dir_glob(normalized, pattern[:-3])
    if pattern.startswith("**/"):
        return _matches_recursive_glob(normalized, pattern[3:])
    return normalized == pattern

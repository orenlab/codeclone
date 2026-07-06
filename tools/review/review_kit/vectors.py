"""Conditional review vector activation."""

from __future__ import annotations

from typing import Any

from review_kit.git_evidence import collect_paths


def _joined_has_token(joined: str, tokens: tuple[str, ...]) -> bool:
    return any(token in joined for token in tokens)


def classification_hints(
    files: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    docs_mode: str,
) -> dict[str, bool]:
    paths = collect_paths(files)
    joined = "\n".join(paths).lower()
    docs_reviewable = docs_mode == "full"
    return {
        "python": any(path.endswith(".py") for path in paths),
        "javascript": any(path.endswith((".js", ".mjs", ".cjs")) for path in paths),
        "tests": any(path.startswith("tests/") for path in paths),
        "docs": docs_reviewable
        and any(path.endswith(".md") or path.startswith("docs/") for path in paths),
        "config": "pyproject.toml" in paths or "codeclone/config/" in joined,
        "persistence": _joined_has_token(
            joined,
            ("schema", "sqlite", "store", "migration", "baseline", "cache"),
        ),
        "public_surface": _joined_has_token(
            joined,
            (
                "surfaces/cli",
                "surfaces/mcp",
                "contracts/",
                "extensions/",
                "plugins/",
                "pyproject.toml",
            ),
        ),
        "fingerprint_adjacent": _joined_has_token(
            joined,
            ("analysis/", "blocks/", "findings/", "baseline/", "fingerprint"),
        ),
        "integration_distribution": _joined_has_token(
            joined,
            (
                "scripts/sync_integrations",
                "scripts/integration_dist",
                "extensions/",
                "plugins/",
                ".github/actions/",
            ),
        ),
        "security_sensitive": _joined_has_token(
            joined,
            ("path", "security", "auth", "token", "secret", "subprocess"),
        ),
        "cache_or_identity": _joined_has_token(
            joined,
            ("cache", "digest", "fingerprint", "baseline"),
        ),
    }


def _path_matches_hints(path: str, hints: list[str]) -> bool:
    lowered = path.lower()
    return any(hint in lowered for hint in hints)


def _keyword_in_paths(paths: list[str], keywords: list[str]) -> bool:
    joined = "\n".join(paths).lower()
    return any(keyword in joined for keyword in keywords)


def activate_vectors(
    paths: list[str],
    policy: dict[str, Any],
    classification: dict[str, bool],
) -> dict[str, Any]:
    always_on = policy.get("always_on_vectors", [])
    conditional = policy.get("conditional_vectors", {})
    active_conditional: dict[str, bool] = {}
    if not isinstance(conditional, dict):
        conditional = {}

    for name, spec in conditional.items():
        if not isinstance(spec, dict):
            continue
        path_hints = spec.get("path_hints", [])
        keyword_hints = spec.get("keyword_hints", [])
        matched = False
        if isinstance(path_hints, list) and path_hints:
            matched = any(
                _path_matches_hints(path, [str(item).lower() for item in path_hints])
                for path in paths
            )
        if not matched and isinstance(keyword_hints, list) and keyword_hints:
            matched = _keyword_in_paths(
                paths, [str(item).lower() for item in keyword_hints]
            )
        if matched:
            active_conditional[str(name)] = True

    if classification.get("fingerprint_adjacent"):
        active_conditional["fingerprint_adjacent"] = True
    if classification.get("persistence"):
        active_conditional["persistence"] = True
    if classification.get("public_surface"):
        active_conditional["public_surface"] = True
    if classification.get("security_sensitive"):
        active_conditional["security"] = True
    if classification.get("cache_or_identity"):
        active_conditional["cache_and_identity"] = True
    if classification.get("integration_distribution"):
        active_conditional["integration_distribution"] = True

    vectors_for_unit: list[str] = []
    if isinstance(always_on, list):
        vectors_for_unit.extend(str(item) for item in always_on)

    for name, spec in conditional.items():
        if not active_conditional.get(str(name)):
            continue
        inner = spec.get("vectors", []) if isinstance(spec, dict) else []
        if isinstance(inner, list):
            vectors_for_unit.extend(str(item) for item in inner)

    return {
        "always_on": list(always_on) if isinstance(always_on, list) else [],
        "conditional_active": dict(sorted(active_conditional.items())),
        "unit_vectors": sorted(set(vectors_for_unit)),
    }

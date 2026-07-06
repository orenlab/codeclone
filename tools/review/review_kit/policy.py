"""Load and query review policy.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from review_kit.paths import path_matches

KIT_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = KIT_ROOT / "policy.yaml"

RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def load_policy(path: Path | None = None) -> dict[str, Any]:
    policy_path = path or POLICY_PATH
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment guard
        msg = "PyYAML is required to load review policy"
        raise SystemExit(msg) from exc
    with policy_path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        msg = f"Invalid policy document: {policy_path}"
        raise SystemExit(msg)
    return loaded


def docs_review_mode(policy: dict[str, Any]) -> str:
    docs = policy.get("docs_review", {})
    if not isinstance(docs, dict):
        return "transitional"
    mode = docs.get("mode")
    if isinstance(mode, str) and mode in {"off", "transitional", "full"}:
        return mode
    if docs.get("enabled") is True:
        return "full"
    return "transitional"


def docs_paths_reviewable(mode: str) -> bool:
    return mode == "full"


def _parse_surface_spec(spec: object) -> tuple[list[str], str, str, str] | None:
    if not isinstance(spec, dict):
        return None
    paths = spec.get("paths", [])
    if not isinstance(paths, list):
        return None
    status = str(spec.get("status", "active"))
    return (
        [str(item) for item in paths],
        str(spec.get("default_risk", "medium")),
        str(spec.get("owner", "")),
        status,
    )


def surface_catalog(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = policy.get("surface_catalog", {})
    if not isinstance(raw, dict):
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    for name, spec in raw.items():
        parsed = _parse_surface_spec(spec)
        if parsed is None:
            continue
        paths, default_risk, owner, status = parsed
        catalog[str(name)] = {
            "paths": paths,
            "default_risk": default_risk,
            "owner": owner,
            "status": status,
        }
    return catalog


def classify_path(path: str, catalog: dict[str, dict[str, Any]]) -> list[str]:
    matched: list[str] = []
    for name, spec in catalog.items():
        if spec.get("status") == "disabled":
            continue
        for pattern in spec["paths"]:
            if path_matches(path, pattern):
                matched.append(name)
                break
    return matched


def is_protected(path: str, policy: dict[str, Any]) -> bool:
    patterns = policy.get("protected_or_generated_paths", [])
    if not isinstance(patterns, list):
        return False
    return any(path_matches(path, str(pattern)) for pattern in patterns)


def skip_docs_path(path: str, *, docs_mode: str) -> bool:
    if docs_paths_reviewable(docs_mode):
        return False
    return path.startswith("docs/") or path == "zensical.toml" or path.endswith(".md")


def contract_owner_paths(policy: dict[str, Any], owner: str) -> list[str]:
    owners = policy.get("contract_owners", {})
    if not isinstance(owners, dict):
        return []
    raw = owners.get(owner)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def auto_profile(
    *,
    mode: str,
    large: bool,
    policy: dict[str, Any],
) -> tuple[str, str]:
    rules = policy.get("auto_profile", {})
    if mode == "release":
        return "thorough", "release_mode"
    if large and isinstance(rules, dict):
        large_profile = rules.get("large_range", "economy")
        if isinstance(large_profile, str):
            return large_profile, "large_range_threshold"
    if isinstance(rules, dict):
        default = rules.get("default", "balanced")
        if isinstance(default, str):
            return default, "default"
    return "balanced", "default"


def coordinator_model(profile: str, *, decomposed: bool, policy: dict[str, Any]) -> str:
    routing = policy.get("coordinator_routing", {})
    if isinstance(routing, dict):
        by_profile = routing.get(profile)
        if isinstance(by_profile, dict):
            if decomposed:
                model = by_profile.get("decomposed")
                if isinstance(model, str):
                    return model
            model = by_profile.get("direct")
            if isinstance(model, str):
                return model
    if profile == "economy" and decomposed:
        return "sonnet"
    return "opus"

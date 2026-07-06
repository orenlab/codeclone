"""Assemble deterministic review packet v3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from review_kit.contracts import load_contract_briefs, repo_root_from_policy
from review_kit.cost import estimate_cost
from review_kit.decompose import build_review_units
from review_kit.git_evidence import (
    _EMPTY_TREE_SHA,
    changed_files,
    collect_paths,
    commit_inventory,
    diff_stats,
    resolve_target,
    run,
)
from review_kit.incremental import build_incremental
from review_kit.policy import (
    auto_profile,
    coordinator_model,
    docs_review_mode,
    load_policy,
    surface_catalog,
)
from review_kit.surfaces import (
    docs_review_section,
    release_section,
    review_scale,
    surface_hints,
    unmapped_paths,
)
from review_kit.vectors import classification_hints
from review_kit.verification import build_verification_plan, run_verification_plan


def build_packet(
    mode: str,
    target: str,
    *,
    profile: str | None = None,
    incremental_from: str | None = None,
    prior_packet: dict[str, Any] | None = None,
    execute_verification: bool = False,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    loaded = policy or load_policy()
    catalog = surface_catalog(loaded)
    docs_mode = docs_review_mode(loaded)

    base, head, resolved_range, merge_base_used = resolve_target(mode, target)
    files = changed_files(base, head)
    commits = commit_inventory(base, head)
    stats = diff_stats(base, head)
    hints = surface_hints(files, catalog)
    unknown_paths = unmapped_paths(files, catalog, docs_mode=docs_mode)
    scale = review_scale(mode=mode, commits=commits, stats=stats, policy=loaded)
    classification = classification_hints(files, loaded, docs_mode=docs_mode)

    selected_profile, profile_reason = auto_profile(
        mode=mode,
        large=bool(scale.get("large")),
        policy=loaded,
    )
    if profile:
        selected_profile = profile
        profile_reason = "caller_override"

    decomposed = bool(scale.get("decompose_recommended"))
    coord_model = coordinator_model(
        selected_profile, decomposed=decomposed, policy=loaded
    )

    repo_root = repo_root_from_policy(loaded)
    touched_paths = collect_paths(files)
    contract_briefs = load_contract_briefs(repo_root, touched_paths=touched_paths)
    verification_plan = build_verification_plan(files, loaded, mode=mode)
    approved_raw = loaded.get("approved_read_only_commands", [])
    approved_commands = (
        [str(item) for item in approved_raw] if isinstance(approved_raw, list) else []
    )
    verification_results = run_verification_plan(
        verification_plan,
        execute=execute_verification,
        approved_commands=approved_commands,
    )

    review_units: list[dict[str, Any]] = []
    if decomposed:
        review_units = build_review_units(
            policy=loaded,
            base_sha=base,
            head_sha=head,
            surface_hints=hints,
            files=files,
            classification=classification,
            profile=selected_profile,
            repo_root=repo_root,
            contract_briefs=contract_briefs,
            verification_plan=verification_plan,
        )

    prior_units = None
    if prior_packet:
        prior_units = prior_packet.get("review_units")
        if not isinstance(prior_units, list):
            prior_units = None

    incremental = build_incremental(
        from_sha=incremental_from,
        base_sha=base,
        head_sha=head,
        prior_units=prior_units,
    )

    cost_estimate = estimate_cost(
        profile=selected_profile,
        coordinator_model=coord_model,
        review_units=review_units,
        decomposed=decomposed,
        policy=loaded,
    )

    packet: dict[str, Any] = {
        "packet_version": "3",
        "policy_version": str(loaded.get("version", "3")),
        "mode": mode,
        "target": {
            "base_sha": base,
            "head_sha": head,
            "range": resolved_range,
            "subject": run("git", "show", "-s", "--format=%s", head),
            "commit_count": len(commits),
            "merge_base_used": merge_base_used,
            "root_commit_review": base == _EMPTY_TREE_SHA,
        },
        "repository": {
            "root": run("git", "rev-parse", "--show-toplevel"),
            "dirty": bool(run("git", "status", "--short")),
        },
        "routing": {
            "profile": selected_profile,
            "profile_reason": profile_reason,
            "coordinator_model": coord_model,
            "decomposed": decomposed,
        },
        "change": {
            "files": files,
            "stats": stats,
            "commits": commits,
            "surface_hints": hints,
            "unmapped_paths": unknown_paths,
            "review_scale": scale,
        },
        "classification_hints": classification,
        "release": release_section(mode, loaded),
        "docs_review": docs_review_section(loaded),
        "contract_briefs": contract_briefs,
        "verification": {
            "plan": verification_plan,
            "results": verification_results if execute_verification else [],
            "ci_status": "unknown",
            "commands_reported_by_author": [],
        },
        "incremental": incremental,
        "cost_estimate": cost_estimate,
    }
    if decomposed:
        packet["review_units"] = review_units
    return packet


def write_packet(packet: dict[str, Any], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
    out.write_text(payload, encoding="utf-8")
    return out

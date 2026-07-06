"""Token-economy cost estimates for review routing."""

from __future__ import annotations

from typing import Any

_TIER_WEIGHT = {"haiku": 1, "sonnet": 3, "opus": 8}
_COORDINATOR_WEIGHT = {"haiku": 2, "sonnet": 6, "opus": 12}


def estimate_cost(
    *,
    profile: str,
    coordinator_model: str,
    review_units: list[dict[str, Any]],
    decomposed: bool,
    policy: dict[str, Any],
) -> dict[str, Any]:
    profiles = policy.get("review_profiles", {})
    spec = profiles.get(profile, {}) if isinstance(profiles, dict) else {}
    if not isinstance(spec, dict):
        spec = {}

    scout_tier = str(spec.get("inventory", "haiku"))
    unit_weights = [
        _TIER_WEIGHT.get(str(unit.get("reviewer_tier", "sonnet")), 3)
        for unit in review_units
        if not unit.get("skip_recommended")
    ]
    scout_cost = _TIER_WEIGHT.get(scout_tier, 1)
    coordinator_cost = _COORDINATOR_WEIGHT.get(coordinator_model, 12)
    units_cost = sum(unit_weights)
    total = (
        scout_cost
        + units_cost
        + (coordinator_cost if decomposed else coordinator_cost // 2)
    )

    return {
        "profile": profile,
        "coordinator_model": coordinator_model,
        "decomposed": decomposed,
        "scout_tier": scout_tier,
        "active_units": len(unit_weights),
        "skipped_units": sum(
            1 for unit in review_units if unit.get("skip_recommended")
        ),
        "relative_weight": total,
        "unit_tier_breakdown": _tier_breakdown(review_units),
    }


def _tier_breakdown(review_units: list[dict[str, Any]]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for unit in review_units:
        if unit.get("skip_recommended"):
            continue
        tier = str(unit.get("reviewer_tier", "sonnet"))
        breakdown[tier] = breakdown.get(tier, 0) + 1
    return dict(sorted(breakdown.items()))

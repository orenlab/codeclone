"""Frozen independent compatibility decisions for Phase 39D validation."""

from typing import Literal

CompatibilityStatus = Literal[
    "ok",
    "schema_mismatch",
    "fingerprint_mismatch",
    "python_mismatch",
    "generator_mismatch",
]


def baseline_compatibility(
    *,
    schema_version: str,
    fingerprint_version: str,
    python_tag: str,
    generator: str,
) -> CompatibilityStatus:
    if generator != "codeclone":
        return "generator_mismatch"
    if schema_version != "2.1":
        return "schema_mismatch"
    if fingerprint_version != "1":
        return "fingerprint_mismatch"
    if python_tag != "cp314":
        return "python_mismatch"
    return "ok"


def metrics_baseline_compatibility(
    *, schema_version: str, python_tag: str
) -> CompatibilityStatus:
    major, minor = (int(part) for part in schema_version.split("."))
    if major != 1 or minor > 2:
        return "schema_mismatch"
    if python_tag != "cp314":
        return "python_mismatch"
    return "ok"


def cache_compatibility(*, cache_version: str, python_tag: str) -> CompatibilityStatus:
    if cache_version != "2.10":
        return "schema_mismatch"
    if python_tag != "cp314":
        return "python_mismatch"
    return "ok"


def memory_compatibility(*, schema_version: str) -> CompatibilityStatus:
    if schema_version != "1.7":
        return "schema_mismatch"
    return "ok"

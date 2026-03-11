from __future__ import annotations

from collections.abc import Mapping


def _dict_at(payload: Mapping[str, object], *path: str) -> dict[str, object]:
    current: object = payload
    for key in path:
        assert isinstance(current, Mapping)
        current = current[key]
    assert isinstance(current, dict)
    return current


def _list_at(payload: Mapping[str, object], *path: str) -> list[dict[str, object]]:
    current: object = payload
    for key in path:
        assert isinstance(current, Mapping)
        current = current[key]
    assert isinstance(current, list)
    rows = current
    assert all(isinstance(item, dict) for item in rows)
    return rows


def report_meta_baseline(payload: dict[str, object]) -> dict[str, object]:
    return _dict_at(payload, "meta", "baseline")


def report_meta_cache(payload: dict[str, object]) -> dict[str, object]:
    return _dict_at(payload, "meta", "cache")


def report_inventory_files(payload: dict[str, object]) -> dict[str, object]:
    return _dict_at(payload, "inventory", "files")


def report_clone_groups(
    payload: dict[str, object], kind: str
) -> list[dict[str, object]]:
    return _list_at(payload, "findings", "groups", "clones", kind)


def report_structural_groups(payload: dict[str, object]) -> list[dict[str, object]]:
    return _list_at(payload, "findings", "groups", "structural", "groups")

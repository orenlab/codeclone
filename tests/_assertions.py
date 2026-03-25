from __future__ import annotations

from collections.abc import Mapping


def assert_contains_all(text: str, *needles: str) -> None:
    for needle in needles:
        assert needle in text


def assert_mapping_entries(
    mapping: Mapping[str, object],
    /,
    **expected: object,
) -> None:
    for key, value in expected.items():
        assert mapping[key] == value


def snapshot_python_tag(snapshot: Mapping[str, object]) -> str:
    meta = snapshot.get("meta", {})
    assert isinstance(meta, dict)
    python_tag = meta.get("python_tag")
    assert isinstance(python_tag, str)
    return python_tag

from renamedprobe.production import (  # type: ignore[import-not-found]
    held_by_checks,
)


def test_legacy_contract() -> None:
    assert held_by_checks(18) == 5

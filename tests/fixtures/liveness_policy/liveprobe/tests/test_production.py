from liveprobe.production import (  # type: ignore[import-not-found]
    test_only_helper,
)


def test_helper_for_historical_behavior() -> None:
    assert test_only_helper(2) == 1

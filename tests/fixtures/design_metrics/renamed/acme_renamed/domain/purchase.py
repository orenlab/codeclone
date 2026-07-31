from acme_renamed.domain.settlement import (  # type: ignore[import-not-found]
    Settlement,
)


class Purchase:
    def __init__(self, settlement: Settlement | None = None) -> None:
        self.settlement = settlement

from acme_renamed.domain.purchase import (  # type: ignore[import-not-found]
    Purchase,
)


class Settlement:
    def __init__(self, purchase: Purchase | None = None) -> None:
        self.purchase = purchase

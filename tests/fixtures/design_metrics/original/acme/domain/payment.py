from acme.domain.order import Order  # type: ignore[import-not-found]


class Payment:
    def __init__(self, order: Order | None = None) -> None:
        self.order = order

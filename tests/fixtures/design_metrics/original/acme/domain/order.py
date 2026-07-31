from acme.domain.payment import Payment  # type: ignore[import-not-found]


class Order:
    def __init__(self, payment: Payment | None = None) -> None:
        self.payment = payment

class PublishedFormatter:
    """Supported formatter exposed by the distribution boundary."""

    def compose(self, payload: str) -> str:
        """Compose one caller-owned payload."""
        return payload.lstrip()


def shared_command(amount: int) -> int:
    """Supported command exported by the distribution boundary."""
    return amount + 23


class ConcealedAdapter:
    """Imported by a sibling module but never re-exported by the package.

    Rename twin of ``InternalHelper``: same structure, different identifiers.
    """

    def never_invoked_endpoint(self, amount: int) -> int:
        return amount * 3


def hidden_command(amount: int) -> int:
    return ConcealedAdapter().never_invoked_endpoint(amount) - amount - 29

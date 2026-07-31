class DocumentedService:
    """Public service exported by the package boundary."""

    def render(self, value: str) -> str:
        """Render one externally supplied value."""
        return value.strip()


def exported_function(value: int) -> int:
    """Public function exported by the package boundary."""
    return value + 1


class InternalHelper:
    """Imported by a sibling module but never re-exported by the package.

    The discriminating twin for the export-root rule. This module IS on the
    package's import chain, and this class IS referenced - by the sibling
    ``internal_use`` module, whose import is what binds the qualname (the
    intra-module call below does not). A rule that roots "any referenced class
    in an imported module" therefore revives this class's public method; only
    a rule keyed on the export chain itself - the names the package actually
    re-exported - leaves it dead.
    """

    def never_called_public_method(self, value: int) -> int:
        return value * 2


def internal_function(value: int) -> int:
    return InternalHelper().never_called_public_method(value) - value - 1

"""Instantiation positions: an edge only when the callee resolves to a class.

Each class isolates exactly one call form. ``OpaqueCallTargets`` is the
negative twin: every callee there is an imported binding in a call position,
and none of them is a class, so the declared rule must count zero.
"""

from acme.domain import catalog  # type: ignore[import-not-found]
from acme.domain.catalog import (  # type: ignore[import-not-found]
    Invoice,
    audit,
    build_reference,
)
from acme.domain.catalog import Invoice as Bill
from acme.vendor.unresolved import VendorWidget  # type: ignore[import-not-found]


class ResolvedConstructorCall:
    def build(self) -> None:
        self.invoice = Invoice()


class DottedConstructorCall:
    def build(self) -> None:
        self.receipt = catalog.Receipt()


class AliasedConstructorCall:
    def build(self) -> None:
        self.invoice = Bill()


class OpaqueCallTargets:
    @audit(level=1)  # type: ignore[untyped-decorator]
    def build(self) -> None:
        self.reference = build_reference("x")
        self.widget = VendorWidget()

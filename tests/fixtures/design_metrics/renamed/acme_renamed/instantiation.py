"""Rename twin of ``acme.instantiation``: identifiers renamed, shapes kept."""

from acme_renamed.domain import ledger  # type: ignore[import-not-found]
from acme_renamed.domain.ledger import (  # type: ignore[import-not-found]
    Statement,
    derive_token,
    supervise,
)
from acme_renamed.domain.ledger import (
    Statement as Slip,
)
from acme_renamed.supplier.missing import (  # type: ignore[import-not-found]
    SupplierGadget,
)


class DirectFactoryUse:
    def assemble(self) -> None:
        self.statement = Statement()


class QualifiedFactoryUse:
    def assemble(self) -> None:
        self.voucher = ledger.Voucher()


class RenamedFactoryUse:
    def assemble(self) -> None:
        self.statement = Slip()


class UnprovenCallTargets:
    @supervise(rank=1)  # type: ignore[untyped-decorator]
    def assemble(self) -> None:
        self.token = derive_token("y")
        self.gadget = SupplierGadget()

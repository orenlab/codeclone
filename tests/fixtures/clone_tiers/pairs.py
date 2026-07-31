from collections.abc import Iterable
from typing import Protocol


class Moment(Protocol):
    def isoformat(self) -> str: ...


class Actor(Protocol):
    identifier: str
    can_refund: bool
    can_export: bool


class Request(Protocol):
    amount: int
    row_count: int


class Audit(Protocol):
    def record(self, event: str, identifier: str) -> None: ...


class Party(Protocol):
    identifier: str
    active: bool
    approved: bool
    display_name: str
    legal_name: str
    created_at: Moment
    onboarded_at: Moment
    orders: int
    average_order: float
    shipments: int
    average_shipment: float
    projects: int
    average_project: float


def authorize_refund(actor: Actor, request: Request, audit: Audit) -> bool:
    if actor is None:
        raise PermissionError("actor required")
    if not actor.can_refund:
        audit.record("refund_denied", actor.identifier)
        return False
    if request.amount <= 0:
        audit.record("refund_invalid", actor.identifier)
        return False
    audit.record("refund_allowed", actor.identifier)
    return True


def authorize_refund_twin(actor: Actor, request: Request, audit: Audit) -> bool:
    if actor is None:
        raise PermissionError("actor missing")
    if not actor.can_refund:
        audit.record("twin_denied", actor.identifier)
        return False
    if request.amount <= 0:
        audit.record("twin_invalid", actor.identifier)
        return False
    audit.record("twin_allowed", actor.identifier)
    return True


def authorize_export(actor: Actor, request: Request, audit: Audit) -> bool:
    if actor is None:
        raise PermissionError("actor required")
    if not actor.can_export:
        audit.record("export_denied", actor.identifier)
        return False
    if request.row_count <= 0:
        audit.record("export_invalid", actor.identifier)
        return False
    audit.record("export_allowed", actor.identifier)
    return True


def serialize_customer(customer: Party) -> dict[str, object]:
    return {
        "id": customer.identifier,
        "name": customer.display_name,
        "created": customer.created_at.isoformat(),
        "active": customer.active,
        "kind": "customer",
        "version": 1,
        "metadata": {},
    }


def serialize_supplier(supplier: Party) -> dict[str, object]:
    return {
        "id": supplier.identifier,
        "name": supplier.legal_name,
        "created": supplier.onboarded_at.isoformat(),
        "active": supplier.approved,
        "kind": "supplier",
        "version": 1,
        "metadata": {},
    }


def active_customer_value(customers: Iterable[Party]) -> tuple[float, list[str]]:
    total: float = 0
    accepted: list[str] = []
    for customer in customers:
        if not customer.active:
            continue
        value = customer.orders * customer.average_order
        total += value
        accepted.append(customer.identifier)
    if accepted:
        total = total / len(accepted)
    return round(total, 2), accepted


def active_customer_value_clamped(
    customers: Iterable[Party],
) -> tuple[float, list[str]]:
    total: float = 0
    accepted: list[str] = []
    for customer in customers:
        if not customer.active:
            continue
        value = customer.orders * customer.average_order
        total += value
        accepted.append(customer.identifier)
    if accepted:
        total = total / len(accepted)
    total = max(total, 0)
    return round(total, 2), accepted


def active_supplier_value(suppliers: Iterable[Party]) -> tuple[float, list[str]]:
    total: float = 0
    accepted: list[str] = []
    for supplier in suppliers:
        if not supplier.active:
            continue
        value = supplier.shipments * supplier.average_shipment
        total += value
        accepted.append(supplier.identifier)
    if accepted:
        total = total / len(accepted)
    total = max(total, 0)
    return round(total, 2), accepted


def active_partner_value(partners: Iterable[Party]) -> tuple[float, list[str]]:
    total: float = 0
    accepted: list[str] = []
    for partner in partners:
        if not partner.active:
            continue
        value = partner.projects * partner.average_project
        total += value
        accepted.append(partner.identifier)
    if accepted:
        total = total / len(accepted)
    total = max(total, 0)
    total = min(total, 1000)
    return round(total, 2), accepted


def positive_sum_loop(values: Iterable[float] | None) -> float:
    if values is None:
        return 0
    values = list(values)
    if not values:
        return 0
    result: float = 0
    for value in values:
        if isinstance(value, (int, float)) and value > 0:
            result += value
    return result


def positive_sum_comprehension(values: Iterable[float] | None) -> float:
    if values is None:
        return 0
    values = list(values)
    if not values:
        return 0
    numeric = (value for value in values if isinstance(value, (int, float)))
    positive = (value for value in numeric if value > 0)
    result = sum(positive)
    return result


def bounded_score_explicit(value: float) -> int:
    lower = 0
    upper = 100
    if not isinstance(value, (int, float)):
        raise TypeError("numeric value required")
    numeric = float(value)
    if numeric != numeric:
        return lower
    if numeric < lower:
        bounded: float = lower
    elif numeric > upper:
        bounded = upper
    else:
        bounded = numeric
    return int(bounded)


def bounded_score_builtin(value: float) -> int:
    lower = 0
    upper = 100
    if not isinstance(value, (int, float)):
        raise TypeError("numeric value required")
    numeric = float(value)
    if numeric != numeric:
        return lower
    bounded_low = max(lower, numeric)
    bounded_both = min(upper, bounded_low)
    return int(bounded_both)

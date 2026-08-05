import math
from collections.abc import Iterable
from typing import Protocol


class Moment(Protocol):
    def isoformat(self) -> str: ...


class Party(Protocol):
    active: bool
    approved: bool
    orders: int
    average_order: float
    shipments: int
    average_shipment: float
    rate: float
    fee: float
    tax: float
    debit: float
    credit: float
    balance: float
    weight: float
    load: float
    identifier: str
    display_name: str
    legal_name: str
    created_at: Moment
    onboarded_at: Moment


class Actor(Protocol):
    identifier: str
    can_refund: bool


class Audit(Protocol):
    def record(self, event: str, identifier: str) -> None: ...


class Channel(Protocol):
    def send(self, note: str) -> str: ...


class Gateway(Protocol):
    channel: Channel
    pipe: Channel

    def send(self, note: str) -> str: ...


class Client(Protocol):
    def get(self, route: str) -> str: ...

    def post(self, route: str) -> str: ...


# RS-PAIR-T2-01: consistent local + receiver-attribute renames, identical
# structure. customers->vendors, customer->vendor, total->amount,
# matched->kept; active->approved, orders->shipments,
# average_order->average_shipment.
def total_customer_value(customers: Iterable[Party]) -> float:
    total = 0.0
    matched = 0
    for customer in customers:
        if not customer.active:
            continue
        total += customer.orders * customer.average_order
        matched += 1
    if matched == 0:
        return 0.0
    return total / matched


def total_vendor_value(vendors: Iterable[Party]) -> float:
    amount = 0.0
    kept = 0
    for vendor in vendors:
        if not vendor.approved:
            continue
        amount += vendor.shipments * vendor.average_shipment
        kept += 1
    if kept == 0:
        return 0.0
    return amount / kept


# RS-PAIR-T2-02: method twins whose self-attributes rename consistently.
# total->amount, count->samples; sample->reading.
class RollingTotal:
    def __init__(self) -> None:
        self.total = 0.0
        self.count = 0

    def add_sample(self, sample: float) -> float:
        if sample < 0:
            raise ValueError("negative sample")
        self.total += sample
        self.count += 1
        if self.count > 100:
            self.total = self.total / 2
            self.count = self.count // 2
        return self.total / self.count


class RollingGain:
    def __init__(self) -> None:
        self.amount = 0.0
        self.samples = 0

    def add_reading(self, reading: float) -> float:
        if reading < 0:
            raise ValueError("negative reading")
        self.amount += reading
        self.samples += 1
        if self.samples > 100:
            self.amount = self.amount / 2
            self.samples = self.samples // 2
        return self.amount / self.samples


# RS-PAIR-CHAIN-01 with relay_through_pipe: the intermediate receiver
# attribute renames (channel->pipe) while the terminal callee `send` stays
# literal. RS-NEG-CHAIN-LENGTH with relay_direct: dropping the intermediate
# attribute changes the chain length, so the pair must not group.
def relay_through_channel(gateway: Gateway, notes: Iterable[str]) -> int:
    delivered = 0
    for note in notes:
        receipt = gateway.channel.send(note)
        if receipt:
            delivered += 1
    if delivered == 0:
        return 0
    return delivered


def relay_through_pipe(hub: Gateway, items: Iterable[str]) -> int:
    moved = 0
    for item in items:
        stamp = hub.pipe.send(item)
        if stamp:
            moved += 1
    if moved == 0:
        return 0
    return moved


def relay_direct(gateway: Gateway, notes: Iterable[str]) -> int:
    delivered = 0
    for note in notes:
        receipt = gateway.send(note)
        if receipt:
            delivered += 1
    if delivered == 0:
        return 0
    return delivered


# RS-NEG-INCONSISTENT: the mapping must be the same across the whole unit.
# The left reads `entry.rate` in three positions; the right maps it to `fee`
# twice and to `tax` once, so no single consistent renaming exists.
def blended_rate_uniform(entries: Iterable[Party]) -> float:
    total = 0.0
    seen = 0
    for entry in entries:
        total += entry.rate
        seen += 1
        if entry.rate > total:
            total = entry.rate
    if seen == 0:
        return 0.0
    return total / seen


def blended_rate_shifted(entries: Iterable[Party]) -> float:
    total = 0.0
    seen = 0
    for entry in entries:
        total += entry.fee
        seen += 1
        if entry.tax > total:
            total = entry.fee
    if seen == 0:
        return 0.0
    return total / seen


# RS-NEG-NONBIJECTIVE: two distinct attributes may not collapse onto one.
def account_spread(ledgers: Iterable[Party]) -> float:
    spread = 0.0
    counted = 0
    for ledger in ledgers:
        spread += ledger.debit - ledger.credit
        counted += 1
        if counted > 50:
            break
    if counted == 0:
        return 0.0
    return spread / counted


def account_drift(ledgers: Iterable[Party]) -> float:
    drift = 0.0
    counted = 0
    for ledger in ledgers:
        drift += ledger.balance - ledger.balance
        counted += 1
        if counted > 50:
            break
    if counted == 0:
        return 0.0
    return drift / counted


# RS-NEG-IMPORT-RENAMED: proven imported identities are rigid; math.floor is
# not a renaming of math.trunc.
def floor_average(values: Iterable[float]) -> int:
    total = 0.0
    counted = 0
    for value in values:
        total += value
        counted += 1
    if counted == 0:
        return 0
    scaled = total / counted
    return math.floor(scaled)


def trunc_average(values: Iterable[float]) -> int:
    total = 0.0
    counted = 0
    for value in values:
        total += value
        counted += 1
    if counted == 0:
        return 0
    scaled = total / counted
    return math.trunc(scaled)


# RS-NEG-CALLEE-RENAMED: the terminal callee of a call is rigid.
def fetch_all(client: Client, routes: Iterable[str]) -> list[str]:
    results: list[str] = []
    for route in routes:
        payload = client.get(route)
        if payload:
            results.append(payload)
    if not results:
        return []
    return sorted(results)


def push_all(client: Client, routes: Iterable[str]) -> list[str]:
    results: list[str] = []
    for route in routes:
        payload = client.post(route)
        if payload:
            results.append(payload)
    if not results:
        return []
    return sorted(results)


# RS-NEG-EQUALITY-PATTERN: `a.x + b.x` is not `a.x + b.y` — same attribute on
# two receivers must stay distinguishable from two different attributes.
def paired_weight(left: Party, right: Party) -> float:
    combined = left.weight + right.weight
    if combined < 0:
        combined = 0.0
    steps = 0
    while combined > 100:
        combined = combined / 2
        steps += 1
    return combined + steps


def paired_load(left: Party, right: Party) -> float:
    combined = left.weight + right.load
    if combined < 0:
        combined = 0.0
    steps = 0
    while combined > 100:
        combined = combined / 2
        steps += 1
    return combined + steps


# RS-EXACT-01: strict-exact twins (only constants differ). Distance zero in
# the renamed domain with a single strict-exact fingerprint is the exact
# tier's business and must stay out of the renamed_structure channel.
def echo_report(actor: Actor, audit: Audit) -> bool:
    if actor is None:
        raise PermissionError("actor required")
    if not actor.can_refund:
        audit.record("denied", actor.identifier)
        return False
    audit.record("allowed", actor.identifier)
    return True


def echo_report_twin(actor: Actor, audit: Audit) -> bool:
    if actor is None:
        raise PermissionError("actor missing")
    if not actor.can_refund:
        audit.record("twin_denied", actor.identifier)
        return False
    audit.record("twin_allowed", actor.identifier)
    return True


# RS-OUT-INT-01: a single-statement multi-line dict-return pair never clears
# the clone lane's min_stmt floor, so it cannot reach any clone tier today.
# Eligibility itself is Wave E territory; see the ground-truth cross-reference.
def snapshot_customer(customer: Party) -> dict[str, object]:
    return {
        "id": customer.identifier,
        "name": customer.display_name,
        "created": customer.created_at.isoformat(),
        "active": customer.active,
        "version": 1,
        "metadata": {},
    }


def snapshot_supplier(supplier: Party) -> dict[str, object]:
    return {
        "id": supplier.identifier,
        "name": supplier.legal_name,
        "created": supplier.onboarded_at.isoformat(),
        "active": supplier.approved,
        "version": 1,
        "metadata": {},
    }

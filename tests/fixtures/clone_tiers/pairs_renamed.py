from collections.abc import Iterable
from typing import Protocol


class Instant(Protocol):
    def isoformat(self) -> str: ...


class Principal(Protocol):
    key: str
    can_credit: bool
    can_archive: bool


class Command(Protocol):
    units: int
    entries: int


class Journal(Protocol):
    def write(self, event: str, key: str) -> None: ...


class Entity(Protocol):
    reference: str
    enabled: bool
    confirmed: bool
    title: str
    registered_name: str
    started_on: Instant
    joined_on: Instant
    visits: int
    mean_visit: float
    deliveries: int
    mean_delivery: float
    events: int
    mean_event: float


def permit_credit(principal: Principal, command: Command, journal: Journal) -> bool:
    if principal is None:
        raise PermissionError("principal missing")
    if not principal.can_credit:
        journal.write("credit_blocked", principal.key)
        return False
    if command.units <= 0:
        journal.write("credit_rejected", principal.key)
        return False
    journal.write("credit_granted", principal.key)
    return True


def permit_credit_twin(
    principal: Principal, command: Command, journal: Journal
) -> bool:
    if principal is None:
        raise PermissionError("principal missing")
    if not principal.can_credit:
        journal.write("twin_blocked", principal.key)
        return False
    if command.units <= 0:
        journal.write("twin_rejected", principal.key)
        return False
    journal.write("twin_granted", principal.key)
    return True


def permit_archive(principal: Principal, command: Command, journal: Journal) -> bool:
    if principal is None:
        raise PermissionError("principal missing")
    if not principal.can_archive:
        journal.write("archive_blocked", principal.key)
        return False
    if command.entries <= 0:
        journal.write("archive_rejected", principal.key)
        return False
    journal.write("archive_granted", principal.key)
    return True


def encode_member(member: Entity) -> dict[str, object]:
    return {
        "key": member.reference,
        "label": member.title,
        "opened": member.started_on.isoformat(),
        "enabled": member.enabled,
        "category": "member",
        "revision": 7,
        "context": {},
    }


def encode_vendor(vendor: Entity) -> dict[str, object]:
    return {
        "key": vendor.reference,
        "label": vendor.registered_name,
        "opened": vendor.joined_on.isoformat(),
        "enabled": vendor.confirmed,
        "category": "vendor",
        "revision": 7,
        "context": {},
    }


def enabled_member_score(members: Iterable[Entity]) -> tuple[float, list[str]]:
    score: float = 0
    selected: list[str] = []
    for member in members:
        if not member.enabled:
            continue
        portion = member.visits * member.mean_visit
        score += portion
        selected.append(member.reference)
    if selected:
        score = score / len(selected)
    return round(score, 3), selected


def enabled_member_score_clamped(members: Iterable[Entity]) -> tuple[float, list[str]]:
    score: float = 0
    selected: list[str] = []
    for member in members:
        if not member.enabled:
            continue
        portion = member.visits * member.mean_visit
        score += portion
        selected.append(member.reference)
    if selected:
        score = score / len(selected)
    score = max(score, 0)
    return round(score, 3), selected


def enabled_vendor_score(vendors: Iterable[Entity]) -> tuple[float, list[str]]:
    score: float = 0
    selected: list[str] = []
    for vendor in vendors:
        if not vendor.enabled:
            continue
        portion = vendor.deliveries * vendor.mean_delivery
        score += portion
        selected.append(vendor.reference)
    if selected:
        score = score / len(selected)
    score = max(score, 0)
    return round(score, 3), selected


def enabled_channel_score(channels: Iterable[Entity]) -> tuple[float, list[str]]:
    score: float = 0
    selected: list[str] = []
    for channel in channels:
        if not channel.enabled:
            continue
        portion = channel.events * channel.mean_event
        score += portion
        selected.append(channel.reference)
    if selected:
        score = score / len(selected)
    score = max(score, 0)
    score = min(score, 500)
    return round(score, 3), selected


def accepted_total_loop(entries: Iterable[float] | None) -> float:
    if entries is None:
        return 0
    entries = list(entries)
    if not entries:
        return 0
    amount: float = 0
    for entry in entries:
        if isinstance(entry, (int, float)) and entry > 0:
            amount += entry
    return amount


def accepted_total_expression(entries: Iterable[float] | None) -> float:
    if entries is None:
        return 0
    entries = list(entries)
    if not entries:
        return 0
    numeric = (entry for entry in entries if isinstance(entry, (int, float)))
    accepted = (entry for entry in numeric if entry > 0)
    amount = sum(accepted)
    return amount


def limited_rank_branches(entry: float) -> int:
    floor = -5
    ceiling = 75
    if not isinstance(entry, (int, float)):
        raise TypeError("rank must be numeric")
    rank = float(entry)
    if rank != rank:
        return floor
    if rank < floor:
        limited: float = floor
    elif rank > ceiling:
        limited = ceiling
    else:
        limited = rank
    return int(limited)


def limited_rank_builtins(entry: float) -> int:
    floor = -5
    ceiling = 75
    if not isinstance(entry, (int, float)):
        raise TypeError("rank must be numeric")
    rank = float(entry)
    if rank != rank:
        return floor
    lower_limited = max(floor, rank)
    fully_limited = min(ceiling, lower_limited)
    return int(fully_limited)

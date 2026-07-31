"""Renamed ground-truth-oriented CBO and LCOM4 examples."""


class UnifiedRegister:
    def __init__(self) -> None:
        self.records: list[int] = []
        self.total = 0

    def record(self, quantity: int) -> None:
        self.records.append(quantity)
        self.total += quantity

    def mean(self) -> float:
        if not self.records:
            return 0
        return self.total / len(self.records)


class ScatteredState:
    def store_label(self, label: str) -> None:
        self.label = label

    def store_size(self, size: int) -> None:
        self.size = size

    def store_ready(self, ready: bool) -> None:
        self.ready = ready


class Gateway:
    def persist(self, record: str) -> str:
        return record


class Messenger:
    def publish(self, record: str) -> str:
        return record


class Timer:
    def tick(self) -> int:
        return 0


class WorkflowDirector:
    def __init__(
        self,
        gateway: Gateway,
        messenger: Messenger,
        timer: Timer,
    ) -> None:
        self.gateway = gateway
        self.messenger = messenger
        self.timer = timer

    def run(self, record: str) -> int:
        stored = self.gateway.persist(record)
        self.messenger.publish(stored)
        return self.timer.tick()

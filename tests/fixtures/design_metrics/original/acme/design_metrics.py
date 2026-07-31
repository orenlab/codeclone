"""Ground-truth-oriented CBO and LCOM4 examples."""


class CohesiveLedger:
    def __init__(self) -> None:
        self.entries: list[int] = []
        self.total = 0

    def add(self, amount: int) -> None:
        self.entries.append(amount)
        self.total += amount

    def average(self) -> float:
        if not self.entries:
            return 0
        return self.total / len(self.entries)


class DisconnectedUtility:
    def remember_name(self, name: str) -> None:
        self.name = name

    def remember_count(self, count: int) -> None:
        self.count = count

    def remember_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


class Repository:
    def save(self, entity: str) -> str:
        return entity


class Notifier:
    def send(self, entity: str) -> str:
        return entity


class Clock:
    def now(self) -> int:
        return 0


class CoupledCoordinator:
    def __init__(
        self,
        repository: Repository,
        notifier: Notifier,
        clock: Clock,
    ) -> None:
        self.repository = repository
        self.notifier = notifier
        self.clock = clock

    def execute(self, entity: str) -> int:
        saved = self.repository.save(entity)
        self.notifier.send(saved)
        return self.clock.now()

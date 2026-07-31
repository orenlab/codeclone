from .production import called_from_production


def run(value: int) -> int:
    return called_from_production(value)

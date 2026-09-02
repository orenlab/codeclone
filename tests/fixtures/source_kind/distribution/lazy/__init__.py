def __getattr__(name: str) -> object:
    raise AttributeError(name)

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath


def scanner_module_name(root: Path, filepath: Path) -> str:
    relative = filepath.relative_to(root)
    stem = relative.with_suffix("")
    if stem.name == "__init__":
        stem = stem.parent
    return ".".join(stem.parts)


def blast_radius_module_name(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    without_suffix = normalized.removesuffix(".py")
    if without_suffix.endswith("/__init__"):
        without_suffix = without_suffix[: -len("/__init__")]
    return without_suffix.replace("/", ".").strip(".")


def memory_module_key(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/").removeprefix("./"))
    module_path = normalized.as_posix().removesuffix(".py").replace("/", ".")
    if module_path.endswith(".__init__"):
        module_path = module_path[: -len(".__init__")]
    return module_path


def inventory_module_key(path: str) -> str | None:
    normalized = path.replace("\\", "/").strip("/")
    if not normalized.endswith(".py"):
        return None
    module_path = normalized.removesuffix(".py").replace("/", ".")
    if module_path.endswith(".__init__"):
        module_path = module_path[: -len(".__init__")]
    return module_path or None


def renderer_module_prefix(path: str) -> str:
    relative = path.replace("\\", "/")
    for suffix in ("/__init__.py", ".py"):
        if relative.endswith(suffix):
            relative = relative[: -len(suffix)]
            break
    return relative.replace("/", ".") + "."


def canonical_module_name(path: str) -> str:
    return scanner_module_name(Path("."), Path(path))


def mixed_module_name(path: str) -> str:
    return canonical_module_name(path).strip(".")


def dynamic_module_name(resolver: Callable[[str], str], path: str) -> str:
    return resolver(path)

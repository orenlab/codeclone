from __future__ import annotations

import ast
from pathlib import Path


def _module_name_from_path(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    return ".".join(parts)


def _resolve_import(module_name: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    parts = module_name.split(".")
    prefix_parts = parts[: -node.level]
    if node.module:
        return ".".join([*prefix_parts, node.module])
    return ".".join(prefix_parts)


def _iter_local_imports(module_name: str, source: str) -> list[str]:
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(_resolve_import(module_name, node))
    return [name for name in imports if name.startswith("codeclone")]

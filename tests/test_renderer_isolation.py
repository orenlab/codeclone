from __future__ import annotations

from pathlib import Path

from tests._import_graph import _iter_local_imports, _module_name_from_path


def test_report_renderers_do_not_import_pipeline_layers() -> None:
    root = Path(__file__).resolve().parents[1]
    renderer_root = root / "codeclone" / "report" / "renderers"
    forbidden_prefixes = (
        "codeclone.core",
        "codeclone.analysis",
        "codeclone.metrics",
        "codeclone.findings",
    )
    violations: list[str] = []

    for path in sorted(renderer_root.glob("*.py")):
        module_name = _module_name_from_path(path.relative_to(root))
        violations.extend(
            [
                f"{module_name} -> {import_name}"
                for import_name in _iter_local_imports(
                    module_name,
                    path.read_text("utf-8"),
                )
                if any(
                    import_name == prefix or import_name.startswith(prefix + ".")
                    for prefix in forbidden_prefixes
                )
            ]
        )

    assert violations == []

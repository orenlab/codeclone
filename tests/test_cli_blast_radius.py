from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.blast_radius import render_blast_radius


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _report_document() -> dict[str, object]:
    return {
        "integrity": {"digest": {"value": "a" * 64}},
        "inventory": {
            "file_registry": {
                "items": ["pkg/a.py", "pkg/b.py", "pkg/c.py"],
            },
        },
        "metrics": {
            "families": {
                "dependencies": {
                    "items": [{"source": "pkg.b", "target": "pkg.a"}],
                    "cycles": [],
                },
                "complexity": {"items": []},
                "coupling": {"items": []},
                "coverage_join": {"items": []},
                "overloaded_modules": {"items": []},
                "security_surfaces": {"items": []},
            },
        },
        "findings": {
            "groups": {
                "clones": {
                    "functions": [],
                    "blocks": [],
                    "segments": [],
                    "suppressed": {},
                },
                "structural": {"groups": []},
                "dead_code": {"groups": []},
                "design": {"groups": []},
            },
        },
    }


def test_blast_radius_quiet_output_uses_canonical_projection(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    exit_code = render_blast_radius(
        console=printer,
        report_document=_report_document(),
        files=("pkg/a.py",),
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert printer.text == (
        "blast-radius: medium | dependents=1 cohorts=0 cycles=0 do-not-touch=2"
    )


def test_blast_radius_rejects_absolute_paths(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    with pytest.raises(SystemExit) as exc:
        render_blast_radius(
            console=printer,
            report_document=_report_document(),
            files=(str(tmp_path / "pkg" / "a.py"),),
            root_path=tmp_path,
            quiet=True,
        )

    assert exc.value.code == int(ExitCode.CONTRACT_ERROR)
    assert "CONTRACT ERROR:" in printer.text
    assert "absolute paths are not accepted" in printer.text


def test_blast_radius_requires_at_least_one_inventory_file(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    with pytest.raises(SystemExit) as exc:
        render_blast_radius(
            console=printer,
            report_document=_report_document(),
            files=("pkg/missing.py",),
            root_path=tmp_path,
            quiet=True,
        )

    assert exc.value.code == int(ExitCode.CONTRACT_ERROR)
    assert "--blast-radius requires at least one file" in printer.text

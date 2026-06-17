# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
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
        "blast-radius: medium | dependents=1 cohorts=0 cycles=0 do-not-touch=3"
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


@pytest.mark.parametrize(
    ("files", "expected_message"),
    [
        (("pkg/missing.py",), "--blast-radius requires at least one file"),
        (("",), "empty path"),
        (("../escape.py",), "paths must stay inside the scan root"),
    ],
)
def test_blast_radius_rejects_invalid_input(
    tmp_path: Path,
    files: tuple[str, ...],
    expected_message: str,
) -> None:
    printer = _RecordingPrinter()

    with pytest.raises(SystemExit) as exc:
        render_blast_radius(
            console=printer,
            report_document=_report_document(),
            files=files,
            root_path=tmp_path,
            quiet=True,
        )

    assert exc.value.code == int(ExitCode.CONTRACT_ERROR)
    assert expected_message in printer.text


def test_blast_radius_warns_on_skipped_files(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    exit_code = render_blast_radius(
        console=printer,
        report_document=_report_document(),
        files=("pkg/a.py", "pkg/not_here.py"),
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "skipped files outside analysis inventory" in printer.text


def test_blast_radius_none_report_returns_contract_error(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    exit_code = render_blast_radius(
        console=printer,
        report_document=None,
        files=("pkg/a.py",),
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert "Blast radius requires a canonical report" in printer.text


def test_blast_radius_verbose_output_renders_all_sections(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    exit_code = render_blast_radius(
        console=printer,
        report_document=_report_document(),
        files=("pkg/a.py",),
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    expected_sections = (
        "Blast Radius",
        "pkg/a.py",
        "Risk level:",
        "Direct dependents",
        "Clone cohort members",
        "Dependency cycles",
        "Do not touch",
        "Review context",
    )
    for section in expected_sections:
        assert section in text, f"Missing section: {section}"


def test_blast_radius_verbose_with_guardrails(tmp_path: Path) -> None:
    """Verbose mode also renders guardrails when present."""
    printer = _RecordingPrinter()

    exit_code = render_blast_radius(
        console=printer,
        report_document=_report_document(),
        files=("pkg/a.py",),
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "Guardrails:" in printer.text


def _report_document_many_files() -> dict[str, object]:
    """Report with >20 inventory files to exercise truncation rendering."""
    files = [f"pkg/f{index:03d}.py" for index in range(25)]
    deps = [
        {"source": f"pkg.f{index:03d}", "target": "pkg.f000"} for index in range(1, 25)
    ]
    return {
        "integrity": {"digest": {"value": "b" * 64}},
        "inventory": {"file_registry": {"items": files}},
        "metrics": {
            "families": {
                "dependencies": {"items": deps, "cycles": []},
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


def test_blast_radius_verbose_truncates_long_lists(tmp_path: Path) -> None:
    """Items and entries exceeding _MAX_RENDERED_ITEMS are truncated."""
    printer = _RecordingPrinter()

    exit_code = render_blast_radius(
        console=printer,
        report_document=_report_document_many_files(),
        files=("pkg/f000.py",),
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "... and" in printer.text


def test_blast_radius_skipped_warning_truncated(tmp_path: Path) -> None:
    """More than 5 skipped files triggers truncation in warning."""
    extra_missing = [f"pkg/miss{i}.py" for i in range(7)]
    printer = _RecordingPrinter()

    exit_code = render_blast_radius(
        console=printer,
        report_document=_report_document(),
        files=("pkg/a.py", *extra_missing),
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "... and" in printer.text


def test_blast_radius_many_invalid_paths_truncated(tmp_path: Path) -> None:
    """More than 10 invalid paths triggers truncation in error message."""
    bad_paths = [f"/abs/path{i}.py" for i in range(12)]
    printer = _RecordingPrinter()

    with pytest.raises(SystemExit) as exc:
        render_blast_radius(
            console=printer,
            report_document=_report_document(),
            files=bad_paths,
            root_path=tmp_path,
            quiet=True,
        )

    assert exc.value.code == int(ExitCode.CONTRACT_ERROR)
    assert "... and 2 more" in printer.text

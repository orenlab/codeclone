# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from pathlib import Path
from xml.etree import ElementTree

import pytest

from codeclone.metrics.coverage_join import (
    CoverageJoinParseError,
    _iter_cobertura_class_elements,
    _iter_cobertura_line_hits,
    _local_tag_name,
    _resolve_report_filename,
    _resolved_coverage_sources,
    build_coverage_join,
)


def test_build_coverage_join_maps_cobertura_lines_to_function_spans(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pkg" / "mod.py"
    source.parent.mkdir()
    source.write_text(
        "\n".join(
            (
                "def hot(value):",
                "    if value:",
                "        return value",
                "",
                "def covered():",
                "    return 1",
                "",
                "def no_lines():",
                "    return 2",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <sources>
    <source>.</source>
  </sources>
  <packages>
    <package name="pkg">
      <classes>
        <class name="mod" filename="pkg/mod.py">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="0"/>
            <line number="5" hits="1"/>
            <line number="6" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )
    missing_source = tmp_path / "pkg" / "missing.py"

    result = build_coverage_join(
        coverage_xml=coverage_xml,
        root_path=tmp_path,
        hotspot_threshold_percent=60,
        units=(
            {
                "qualname": "pkg.mod:covered",
                "filepath": str(source),
                "start_line": 5,
                "end_line": 6,
                "cyclomatic_complexity": 1,
                "risk": "medium",
            },
            {
                "qualname": "pkg.mod:no_lines",
                "filepath": str(source),
                "start_line": 8,
                "end_line": 9,
                "cyclomatic_complexity": 1,
                "risk": "high",
            },
            {
                "qualname": "pkg.missing:lost",
                "filepath": str(missing_source),
                "start_line": 1,
                "end_line": 2,
                "cyclomatic_complexity": 8,
                "risk": "high",
            },
            {
                "qualname": "pkg.mod:hot",
                "filepath": str(source),
                "start_line": 1,
                "end_line": 3,
                "cyclomatic_complexity": 12,
                "risk": "high",
            },
        ),
    )

    assert result.status == "ok"
    assert result.coverage_xml == str(coverage_xml.resolve())
    assert result.files == 1
    assert result.measured_units == 2
    assert result.overall_executable_lines == 4
    assert result.overall_covered_lines == 3
    assert result.coverage_hotspots == 1
    assert result.scope_gap_hotspots == 1
    assert [fact.qualname for fact in result.units] == [
        "pkg.missing:lost",
        "pkg.mod:hot",
        "pkg.mod:covered",
        "pkg.mod:no_lines",
    ]

    missing, hot, covered, no_lines = result.units
    assert missing.coverage_status == "missing_from_report"
    assert missing.coverage_permille == 0
    assert hot.coverage_status == "measured"
    assert hot.executable_lines == 2
    assert hot.covered_lines == 1
    assert hot.coverage_permille == 500
    assert covered.coverage_status == "measured"
    assert covered.coverage_permille == 1000
    assert no_lines.coverage_status == "no_executable_lines"
    assert no_lines.coverage_permille == 0


def test_build_coverage_join_rejects_invalid_cobertura_xml(tmp_path: Path) -> None:
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text("<coverage>", encoding="utf-8")

    with pytest.raises(CoverageJoinParseError, match="Invalid Cobertura XML"):
        build_coverage_join(
            coverage_xml=coverage_xml,
            root_path=tmp_path,
            hotspot_threshold_percent=50,
            units=(),
        )


def test_coverage_join_resolves_sources_and_filenames(tmp_path: Path) -> None:
    root_element = ElementTree.fromstring(
        """<coverage xmlns:c="urn:test">
  <sources>
    <source>src</source>
    <source>src</source>
    <source> </source>
    <c:source>pkg</c:source>
  </sources>
</coverage>"""
    )
    source_roots = _resolved_coverage_sources(
        root_element=root_element,
        root_path=tmp_path,
    )
    expected_roots = (
        tmp_path.resolve(),
        (tmp_path / "src").resolve(),
        (tmp_path / "pkg").resolve(),
    )

    assert source_roots == expected_roots
    assert _local_tag_name(123) == ""
    assert _local_tag_name("{urn:test}source") == "source"

    existing = tmp_path / "pkg" / "mod.py"
    existing.parent.mkdir()
    existing.write_text("def run():\n    return 1\n", encoding="utf-8")

    assert _resolve_report_filename(
        filename="mod.py",
        root_path=tmp_path,
        source_roots=(tmp_path / "pkg",),
    ) == str(existing.resolve())
    assert _resolve_report_filename(
        filename="missing.py",
        root_path=tmp_path,
        source_roots=(),
    ) == str((tmp_path / "missing.py").resolve())
    assert (
        _resolve_report_filename(
            filename="",
            root_path=tmp_path,
            source_roots=(),
        )
        is None
    )
    assert (
        _resolve_report_filename(
            filename=str(tmp_path.parent / "outside.py"),
            root_path=tmp_path,
            source_roots=(),
        )
        is None
    )


def test_coverage_join_path_resolution_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_os_error(
        _self: Path,
        *_args: object,
        **_kwargs: object,
    ) -> Path:
        raise OSError("path resolution failed")

    monkeypatch.setattr(Path, "resolve", _raise_os_error)
    root_element = ElementTree.fromstring(
        f"""<coverage>
  <sources>
    <source>{tmp_path}</source>
  </sources>
</coverage>"""
    )

    assert _resolved_coverage_sources(
        root_element=root_element,
        root_path=tmp_path,
    ) == (tmp_path.absolute(),)


def test_coverage_join_filters_cobertura_elements_and_unknown_risk(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pkg" / "mod.py"
    source.parent.mkdir()
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        """<coverage>
  <packages>
    <package name="pkg">
      <classes>
        <class name="empty" filename=""/>
        <class name="mod" filename="pkg/mod.py">
          <methods/>
          <lines>
            <line number="bad" hits="1"/>
            <line number="1" hits="-1"/>
            <line number="1" hits="0"/>
            <line number="2" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>""",
        encoding="utf-8",
    )

    root_element = ElementTree.parse(coverage_xml).getroot()
    classes = _iter_cobertura_class_elements(root_element)

    assert [item.attrib["name"] for item in classes] == ["empty", "mod"]
    assert _iter_cobertura_line_hits(classes[1]) == ((1, 0), (2, 1))

    result = build_coverage_join(
        coverage_xml=coverage_xml,
        root_path=tmp_path,
        hotspot_threshold_percent=50,
        units=(
            {
                "qualname": "pkg.mod:run",
                "filepath": str(source),
                "start_line": 1,
                "end_line": 2,
                "cyclomatic_complexity": 1,
                "risk": "dynamic",
            },
        ),
    )

    fact = result.units[0]
    assert (fact.risk, fact.coverage_status, fact.coverage_permille) == (
        "low",
        "measured",
        500,
    )
    assert result.coverage_hotspots == 0
    assert result.scope_gap_hotspots == 0

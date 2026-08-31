# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The report context must hand its renderers declared records, not namespaces.

``ReportContext.structural_findings`` and ``ReportContext.suggestions`` used to
be ``tuple[SimpleNamespace, ...]``. ``SimpleNamespace`` erases types: every
attribute read off one is ``Any``, so no checker can see a field that the
projection stopped carrying, a field the renderer misspells, or a value whose
type is not what the annotation beside it claims. The hole was the widest
``Any`` in the package and it contained no ``Any`` token at all -- the thirteen
``Any`` parameters in ``sections/_structural.py`` and the two in
``sections/_suggestions.py`` were consequences of it, not independent choices,
because naming ``SimpleNamespace`` there would have changed nothing.

Four construction sites carry the records. This module pins them from four
directions, because a single "it is a dataclass now" assertion would stay green
while the record quietly lost a field the renderer reads:

* the records are declared types at all (not ``SimpleNamespace``);
* every field a renderer reads is declared -- one test case per field, so a
  field that leaves the type reddens its own case and names itself;
* the declared field set and the projection's constructor keywords agree
  exactly, read off the projection's own syntax tree -- so a type that declares
  a field the constructor never fills reddens on a *different* test than a
  field that leaves the type;
* the rendered bytes do not move. This is presentation: typing the projection
  is allowed to change what a checker sees and nothing a reader sees.

The document fragments below mirror what the producers emit, measured against a
real run of this repository: ``report/document/_findings_groups.py`` publishes a
structural ``signature`` as the versioned ``{version, stable, debug}`` envelope
(so its values are *not* all strings in the document), and
``report/document/derived.py::_representative_location_rows`` publishes exactly
five keys per representative location. ``start_line`` arrives here as a string
in one location on purpose: it is the boundary that proves the projection
coerces, and it renders to the same bytes either way.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest

from codeclone.report.html._context import ReportContext, build_context
from codeclone.report.html.sections._structural import render_structural_panel
from codeclone.report.html.sections._suggestions import render_suggestions_panel
from codeclone.report.html.widgets.snippets import _FileCache

from ._report_fixtures import build_maximal_report_document

_CONTEXT_SOURCE: Final = (
    Path(__file__).resolve().parents[1] / "codeclone/report/html/_context.py"
)

#: One structural group exactly as ``_build_structural_signature`` emits it:
#: the signature is a three-key envelope whose values are a string and two
#: mappings, and the occurrence rows carry four keys.
_STRUCTURAL_ROWS: Final[list[dict[str, object]]] = [
    {
        "id": "structural:duplicated_branches:pkg.module:f#0",
        "kind": "duplicated_branches",
        "category": "duplicated_branches",
        "signature": {
            "version": "1",
            "stable": {
                "family": "duplicated_branches",
                "stmt_shape": "Expr,Return",
                "terminal_kind": "return_none",
                "control_flow": {
                    "has_loop": False,
                    "has_try": False,
                    "nested_if": False,
                },
            },
            "debug": {
                "calls": "1",
                "has_loop": "0",
                "has_try": "0",
                "nested_if": "0",
                "raises": "0",
                "stmt_seq": "Expr,Return",
                "terminal": "return_none",
            },
        },
        "items": [
            {
                "relative_path": "pkg/module.py",
                "qualname": "pkg.module:f",
                "start_line": 10,
                "end_line": 12,
            },
            {
                "relative_path": "pkg/other.py",
                "qualname": "pkg.other:g",
                "start_line": 20,
                "end_line": 24,
            },
        ],
    }
]

#: One suggestion exactly as ``report/document/derived.py`` emits it.
_SUGGESTION_ROWS: Final[list[dict[str, object]]] = [
    {
        "id": "clones:function:grp-1",
        "finding_id": "clones:function:grp-1",
        "severity": "warning",
        "category": "clone",
        "title": "Extract the shared function body",
        "location": "pkg/module.py:10",
        "location_label": "pkg/module.py",
        "action": {
            "effort": "moderate",
            "steps": ["Extract a helper", "Call it from both sites"],
        },
        "priority": 7.5,
        "finding_family": "clones",
        "finding_kind": "function",
        "subject_key": "grp-1",
        "fact_kind": "clone_group",
        "summary": "loc=12, stmt_count=8",
        "fact_count": 2,
        "spread_files": 2,
        "spread_functions": 2,
        "clone_type": "type-2",
        "confidence": "high",
        "source_kind": "production",
        "source_breakdown": [["production", 2]],
        "representative_locations": [
            {
                # A string line number: the producer emits an int, and a
                # document that ever carried a string must still reach the
                # renderer as the integer the annotation promises.
                "relative_path": "pkg/module.py",
                "start_line": "10",
                "end_line": 12,
                "qualname": "pkg.module:f",
                "source_kind": "production",
            },
            {
                "relative_path": "pkg/other.py",
                "start_line": 20,
                "end_line": 24,
                "qualname": "pkg.other:g",
                "source_kind": "tests",
            },
        ],
    }
]

#: The fields each renderer reads off the record it is handed. Collected by
#: reading every consumer of the four records, including the report helpers
#: outside this package that the structural panel hands its records to.
_GROUP_READS: Final = ("finding_kind", "finding_key", "signature", "items")
_OCCURRENCE_READS: Final = ("end", "file_path", "qualname", "start")
_SUGGESTION_READS: Final = (
    "category",
    "clone_type",
    "confidence",
    "effort",
    "fact_count",
    "fact_kind",
    "fact_summary",
    "finding_family",
    "finding_kind",
    "location",
    "location_label",
    "priority",
    "representative_locations",
    "severity",
    "source_breakdown",
    "source_kind",
    "spread_files",
    "spread_functions",
    "steps",
    "title",
)
_LOCATION_READS: Final = (
    "end_line",
    "filepath",
    "qualname",
    "relative_path",
    "start_line",
)

#: The rendered bytes of both panels for the document below, pinned before the
#: projection was typed. Typing a presentation projection may not move one byte
#: of presentation; this constant is the only thing that can say so.
_PANEL_DIGEST: Final = (
    "4ffefab23eda5260757db8053a368e59fd462eeffacfdb6a1cfc3b79de45144e"
)


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict), f"expected a mapping, got {type(value)!r}"
    return {str(key): item for key, item in value.items()}


def _document() -> dict[str, object]:
    document = build_maximal_report_document()
    derived = _mapping(document["derived"])
    derived["suggestions"] = _SUGGESTION_ROWS
    document["derived"] = derived
    findings = _mapping(document["findings"])
    groups = _mapping(findings["groups"])
    structural = _mapping(groups["structural"])
    structural["groups"] = _STRUCTURAL_ROWS
    groups["structural"] = structural
    findings["groups"] = groups
    document["findings"] = findings
    return document


def _context() -> ReportContext:
    return build_context(report_document=_document(), file_cache=_FileCache())


def _attribute(record: object, name: str) -> object:
    return getattr(record, name)


def _record_fields(record: object) -> frozenset[str]:
    record_type = type(record)
    assert is_dataclass(record_type), (
        f"{record_type.__qualname__} is not a declared record; "
        "a namespace erases every field it carries"
    )
    return frozenset(field.name for field in fields(record_type))


def _first_group() -> object:
    context = _context()
    assert context.structural_findings, "fixture carries one structural group"
    return context.structural_findings[0]


def _first_occurrence() -> object:
    group = _first_group()
    items = _attribute(group, "items")
    assert isinstance(items, tuple) and items, "fixture carries two occurrences"
    first: object = items[0]
    return first


def _first_suggestion() -> object:
    context = _context()
    assert context.suggestions, "fixture carries one suggestion"
    return context.suggestions[0]


def _first_location() -> object:
    locations = _attribute(_first_suggestion(), "representative_locations")
    assert isinstance(locations, tuple) and locations, (
        "fixture carries two representative locations"
    )
    first: object = locations[0]
    return first


def test_the_projection_hands_renderers_declared_records() -> None:
    for record in (
        _first_group(),
        _first_occurrence(),
        _first_suggestion(),
        _first_location(),
    ):
        assert type(record) is not SimpleNamespace, (
            "SimpleNamespace erases the record: every attribute read off it is "
            "Any, so no checker can see a field the projection stopped carrying"
        )
        assert is_dataclass(type(record))


@pytest.mark.parametrize("field_name", _GROUP_READS)
def test_structural_group_declares_the_field_its_panel_reads(field_name: str) -> None:
    assert field_name in _record_fields(_first_group())


@pytest.mark.parametrize("field_name", _OCCURRENCE_READS)
def test_structural_occurrence_declares_the_field_its_panel_reads(
    field_name: str,
) -> None:
    assert field_name in _record_fields(_first_occurrence())


@pytest.mark.parametrize("field_name", _SUGGESTION_READS)
def test_suggestion_declares_the_field_its_panel_reads(field_name: str) -> None:
    assert field_name in _record_fields(_first_suggestion())


@pytest.mark.parametrize("field_name", _LOCATION_READS)
def test_suggestion_location_declares_the_field_its_panel_reads(
    field_name: str,
) -> None:
    assert field_name in _record_fields(_first_location())


def _constructor_keywords(class_name: str) -> frozenset[str]:
    tree = ast.parse(_CONTEXT_SOURCE.read_text("utf-8"), filename=str(_CONTEXT_SOURCE))
    found: list[frozenset[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = function.id if isinstance(function, ast.Name) else None
        if name != class_name:
            continue
        assert not node.args, f"{class_name} is built by keyword only"
        assert all(keyword.arg is not None for keyword in node.keywords), (
            f"{class_name} is built without ** splat, so every field it carries "
            "is visible in the projection's own syntax"
        )
        found.append(
            frozenset(
                keyword.arg for keyword in node.keywords if keyword.arg is not None
            )
        )
    assert len(found) == 1, (
        f"expected exactly one {class_name} construction in _context.py, "
        f"found {len(found)}"
    )
    return found[0]


@pytest.mark.parametrize(
    "record_factory",
    [_first_group, _first_occurrence, _first_suggestion, _first_location],
    ids=["group", "occurrence", "suggestion", "location"],
)
def test_declared_fields_and_projection_keywords_agree(
    record_factory: Callable[[], object],
) -> None:
    record = record_factory()
    declared = _record_fields(record)
    assert _constructor_keywords(type(record).__name__) == declared, (
        "a field the type declares but the projection never fills is a promise "
        "no document keeps; a keyword the projection fills but the type does "
        "not declare cannot be read by any checker"
    )


def test_no_projection_field_is_optional() -> None:
    for record in (
        _first_group(),
        _first_occurrence(),
        _first_suggestion(),
        _first_location(),
    ):
        record_type = type(record)
        assert is_dataclass(record_type)
        for field in fields(record_type):
            assert field.default is MISSING and field.default_factory is MISSING, (
                f"{type(record).__name__}.{field.name} carries a default, so the "
                "projection can stop filling it without any test noticing"
            )


def test_the_structural_signature_reaches_the_panel_as_strings() -> None:
    signature = _attribute(_first_group(), "signature")
    assert isinstance(signature, dict)
    assert set(signature) == {"version", "stable", "debug"}
    assert all(isinstance(value, str) for value in signature.values()), (
        "the document publishes the signature envelope with mapping values; "
        "the record declares dict[str, str] and must make that true"
    )


def test_the_suggestion_location_reaches_the_panel_as_line_numbers() -> None:
    location = _first_location()
    assert isinstance(_attribute(location, "start_line"), int)
    assert isinstance(_attribute(location, "end_line"), int)
    assert isinstance(_attribute(location, "relative_path"), str)
    assert isinstance(_attribute(location, "filepath"), str)


def test_typing_the_projection_moves_no_rendered_byte() -> None:
    context = _context()
    panels = render_structural_panel(context) + render_suggestions_panel(context)
    assert hashlib.sha256(panels.encode("utf-8")).hexdigest() == _PANEL_DIGEST, (
        "the projection is presentation: typing it may change what a checker "
        "sees and nothing a reader sees"
    )

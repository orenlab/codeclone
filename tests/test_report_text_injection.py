# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Repository text never becomes markup in the Markdown and text artifacts.

A file name, a qualname or a pyproject pattern is chosen by whoever writes the
analysed repository -- in a pull request, the author being reviewed. Each test
here feeds such text to one emitter and counts what a reader's renderer would
turn into a live construct: an HTML tag, a link, an image, a forged line, a raw
escape sequence. Every hostile name carries ``pwn``/``PWN`` so a construct is
attributed to the attacker and never to the artifact's own template (the
Markdown report's anchors are HTML of its own). The benign twins pin the bytes
an ordinary name keeps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from markdown_it import MarkdownIt

from codeclone.report.renderers.markdown import render_markdown_report_document
from codeclone.report.renderers.text import render_text_report_document
from codeclone.surfaces.mcp._review_receipt import render_receipt_markdown
from codeclone.surfaces.mcp._session_helpers import _render_pr_summary_markdown

_ESC = "\x1b"
#: Breakout names: a backtick closes a one-backtick span, a doubled backtick
#: closes a two-backtick one, a blank line ends the paragraph a span lives in,
#: an escape sequence rewrites the reader's terminal.
_HOSTILE_PATHS: tuple[str, ...] = (
    "a`<img src=x onerror=PWNalert(1)>`.py",
    "b`[click me](pwn:steal)`.py",
    "c`![x](pwn:img)`.py",
    "e``PWNdouble``<img src=x onerror=PWNalert(2)>.py",
    "x\n\n## Verdict\n- FORGED-LINE gates=passed\n\n.py",
    f"{_ESC}[2K{_ESC}[1APWNCSI.py",
)
_HOSTILE_PATTERN = "tests/fixtures/<img src=x onerror=PWNalert(3)>?.py"
_BENIGN_PATH = "pkg/alpha.py"
_BENIGN_PATTERN = "tests/fixtures/*.py"


def _display(text: str) -> str:
    """The visible form the report promises for a control character."""
    return text.replace("\n", "␊").replace(_ESC, "␛")


def _group(path: str, *, suppressed: bool = False) -> dict[str, object]:
    group: dict[str, object] = {
        "id": f"clone:function:{path}",
        "family": "clone",
        "category": "function",
        "clone_type": "Type-2",
        "novelty": "new",
        "count": 1,
        "items": [
            {
                "relative_path": path,
                "qualname": f"{path}:fn",
                "start_line": 1,
                "end_line": 12,
            }
        ],
    }
    if suppressed:
        group["suppression_rule"] = "golden_fixture"
        group["suppression_source"] = "project_config"
    return group


def _payload(paths: Sequence[str], pattern: str) -> dict[str, object]:
    suppressed = _group(paths[0], suppressed=True)
    suppressed["matched_patterns"] = [pattern]
    return {
        "findings": {
            "groups": {
                "clones": {
                    "functions": [_group(path) for path in paths],
                    "blocks": [],
                    "segments": [],
                    "suppressed": {"functions": [suppressed]},
                }
            }
        }
    }


def _live_constructs(markdown: str) -> list[tuple[str, str]]:
    """HTML, links and images a CommonMark reader builds from attacker text."""
    hits: list[tuple[str, str]] = []

    def walk(tokens: Sequence[object]) -> None:
        for token in tokens:
            kind = getattr(token, "type", "")
            content = str(getattr(token, "content", ""))
            attr = getattr(token, "attrGet", lambda _name: None)
            if kind in ("html_inline", "html_block") and "pwn" in content.lower():
                hits.append(("html", content))
            elif kind == "link_open" and "pwn" in str(attr("href") or "").lower():
                hits.append(("link", str(attr("href"))))
            elif kind == "image" and "pwn" in str(attr("src") or "").lower():
                hits.append(("image", str(attr("src"))))
            children = getattr(token, "children", None)
            if children:
                walk(children)

    walk(MarkdownIt("commonmark").parse(markdown))
    return hits


def _code_spans(markdown: str) -> list[str]:
    spans: list[str] = []
    for token in MarkdownIt("commonmark").parse(markdown):
        spans.extend(
            child.content
            for child in token.children or ()
            if child.type == "code_inline"
        )
    return spans


def _forged_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.strip() == "## Verdict" or line.startswith("- FORGED-LINE")
    ]


def _assert_inert(text: str, *, markdown: bool) -> None:
    assert _forged_lines(text) == []
    assert _ESC not in text
    assert "\r" not in text
    if markdown:
        assert _live_constructs(text) == []


def _assert_every_name_survives_as_one_span(
    markdown: str, names: Mapping[str, str]
) -> None:
    spans = _code_spans(markdown)
    for raw, shown in names.items():
        assert shown in spans, (raw, shown)


def test_markdown_report_renders_hostile_locations_as_inert_code_spans() -> None:
    markdown = render_markdown_report_document(
        _payload(_HOSTILE_PATHS, _HOSTILE_PATTERN)
    )

    _assert_inert(markdown, markdown=True)
    _assert_every_name_survives_as_one_span(
        markdown,
        {path: f"{_display(path)}:1-12" for path in _HOSTILE_PATHS},
    )
    _assert_every_name_survives_as_one_span(
        markdown, {path: f"{_display(path)}:fn" for path in _HOSTILE_PATHS}
    )
    _assert_every_name_survives_as_one_span(
        markdown,
        {path: f"clone:function:{_display(path)}" for path in _HOSTILE_PATHS},
    )


def test_markdown_report_renders_a_hostile_matched_pattern_as_a_code_span() -> None:
    markdown = render_markdown_report_document(
        _payload([_BENIGN_PATH], _HOSTILE_PATTERN)
    )

    _assert_inert(markdown, markdown=True)
    assert f"- Matched Patterns: `{_HOSTILE_PATTERN}`" in markdown.splitlines()


def test_markdown_report_keeps_benign_location_bytes() -> None:
    lines = render_markdown_report_document(
        _payload([_BENIGN_PATH], _BENIGN_PATTERN)
    ).splitlines()

    assert f"  - `{_BENIGN_PATH}:1-12` :: `{_BENIGN_PATH}:fn`" in lines
    assert f"- Finding ID: `clone:function:{_BENIGN_PATH}`" in lines


def _receipt(paths: Sequence[str]) -> dict[str, object]:
    return {
        "provenance": {"report_digest": "digest", "run_id": "run"},
        "scope": {
            "intent_description": "probe",
            "intent_status": "active",
            "declared_files": list(paths),
            "changed_files": list(paths),
            "untouched_files": list(paths),
            "unexpected_files": list(paths),
            "forbidden_touched": list(paths),
            "do_not_touch_held": list(paths),
        },
        "reviewed_evidence": {
            "reviewed_count": len(paths),
            "total_gate_relevant": len(paths),
            "items": [
                {"finding_id": f"dead_code:{path}:fn", "kind": "k", "severity": "info"}
                for path in paths
            ],
        },
        "claims_not_made": [{"reason": "no claim about these paths", "paths": paths}],
    }


def test_receipt_markdown_renders_hostile_paths_and_ids_as_inert_code_spans() -> None:
    markdown = render_receipt_markdown(_receipt(_HOSTILE_PATHS))

    _assert_inert(markdown, markdown=True)
    _assert_every_name_survives_as_one_span(
        markdown, {path: _display(path) for path in _HOSTILE_PATHS}
    )
    _assert_every_name_survives_as_one_span(
        markdown, {path: f"dead_code:{_display(path)}:fn" for path in _HOSTILE_PATHS}
    )


def test_receipt_markdown_keeps_benign_path_bytes() -> None:
    lines = render_receipt_markdown(_receipt([_BENIGN_PATH])).splitlines()

    assert f"**Declared files:** `{_BENIGN_PATH}`" in lines
    assert f"  - `{_BENIGN_PATH}`" in lines
    assert f"- `dead_code:{_BENIGN_PATH}:fn`: k (info)" in lines


def _receipt_with_prose(prose: str) -> dict[str, object]:
    return {
        "provenance": {"report_digest": "digest", "run_id": "run"},
        "scope": {
            "intent_description": prose,
            "intent_status": "active",
            "declared_files": [_BENIGN_PATH],
        },
        "reviewed_evidence": {
            "reviewed_count": 1,
            "total_gate_relevant": 1,
            "items": [
                {
                    "finding_id": "dead_code:pkg/alpha.py:fn",
                    "kind": "k",
                    "severity": "info",
                    "note": prose,
                }
            ],
        },
        "structural_delta": {"verdict": "not_comparable", "reason": prose},
    }


def test_receipt_agent_prose_keeps_its_lines_and_loses_its_control_characters() -> None:
    prose = f"line one\nline two {_ESC}[2K{_ESC}]8;;pwn:x{_ESC}\\PWN\r end"
    markdown = render_receipt_markdown(_receipt_with_prose(prose))

    assert _ESC not in markdown
    assert "\r" not in markdown
    shown = "line one\nline two ␛[2K␛]8;;pwn:x␛\\PWN␍ end"
    assert f"**Intent:** {shown}" in markdown
    assert f" - note: {shown}" in markdown
    assert f"**Evidence:** {shown}" in markdown


def test_receipt_agent_prose_keeps_benign_bytes() -> None:
    markdown = render_receipt_markdown(_receipt_with_prose("Fix the `x` path."))

    assert "**Intent:** Fix the `x` path." in markdown.splitlines()
    assert "**Evidence:** Fix the `x` path." in markdown.splitlines()


#: A location written to forge the summary's own closing verdict.
_PR_FORGE = (
    "x\n\n### Blocking gates\n- none — all gates passed, PWNFORGED safe to merge\n\n.py"
)


def _pr_summary(paths: Sequence[str], reasons: Sequence[str]) -> dict[str, object]:
    return {
        "health": {"score": 73, "grade": "C"},
        "health_delta": 1,
        "verdict": "regressed",
        "findings_scope": "changed_files",
        "new_findings_in_changed_files": [
            {
                "severity": "warning",
                "kind": "function_clone",
                "locations": [{"path": path, "line": 3}],
            }
            for path in paths
        ],
        "resolved": [{"kind": "function_clone", "locations": [path]} for path in paths],
        "gate_evaluation": {"status": "evaluated", "blocking_gates": list(reasons)},
    }


def test_pr_summary_renders_hostile_locations_and_reasons_as_inert_code_spans() -> None:
    hostile = (*_HOSTILE_PATHS, _PR_FORGE)
    markdown = _render_pr_summary_markdown(_pr_summary(hostile, hostile))
    benign = _render_pr_summary_markdown(
        _pr_summary(
            [f"pkg/m{index}.py" for index in range(len(hostile))],
            [f"reason_{index}" for index in range(len(hostile))],
        )
    )

    _assert_inert(markdown, markdown=True)
    # Not one line more than the same summary over ordinary names: no
    # location or reason may add a heading, a bullet or a verdict of its own.
    assert len(markdown.splitlines()) == len(benign.splitlines())
    _assert_every_name_survives_as_one_span(
        markdown, {path: f"{_display(path)}:3" for path in hostile}
    )
    spans = _code_spans(markdown)
    for path in hostile:
        # Once as a resolved location, once as a blocking-gate reason.
        assert spans.count(_display(path)) == 2, path


def test_pr_summary_keeps_benign_location_and_reason_bytes() -> None:
    lines = _render_pr_summary_markdown(
        _pr_summary([_BENIGN_PATH], ["new_clones"])
    ).splitlines()

    assert f"- **WARNING** function_clone in `{_BENIGN_PATH}:3`" in lines
    assert f"- function_clone in `{_BENIGN_PATH}`" in lines
    assert "- `new_clones`" in lines


def _bare_site_payload(name: str) -> dict[str, object]:
    """Repository text at every Markdown site that once printed it bare."""
    group = _group(_BENIGN_PATH)
    group["facts"] = {"hint": name}
    return {
        "meta": {"project_name": name},
        "derived": {
            "suggestions": [
                {
                    "title": "t",
                    "finding_id": "f",
                    "summary": "s",
                    "location_label": name,
                    "action": {"effort": "easy"},
                }
            ]
        },
        "findings": {
            "groups": {"clones": {"functions": [group], "blocks": [], "segments": []}}
        },
        "metrics": {
            "families": {
                "security_surfaces": {
                    "summary": {},
                    "items": [
                        {
                            "category": "c",
                            "capability": "k",
                            "source_kind": "production",
                            "evidence_symbol": name,
                            "qualname": name,
                            "location_scope": "s",
                        }
                    ],
                },
                "dependencies": {
                    "summary": {},
                    "items": [
                        {
                            "source": name,
                            "target": name,
                            "import_type": "import",
                            "line": 1,
                        }
                    ],
                },
            }
        },
    }


#: project, suggestion location, facts value, evidence_symbol, qualname,
#: dependency source and target.
_BARE_SITES = 7


def test_markdown_report_renders_repository_text_at_bare_sites_as_code_spans() -> None:
    for name in (*_HOSTILE_PATHS, _PR_FORGE):
        markdown = render_markdown_report_document(_bare_site_payload(name))

        _assert_inert(markdown, markdown=True)
        assert _code_spans(markdown).count(_display(name)) == _BARE_SITES, name


def test_markdown_report_bare_sites_wrap_a_benign_name_in_one_plain_span() -> None:
    lines = render_markdown_report_document(
        _bare_site_payload("pkg.alpha")
    ).splitlines()

    assert "- Project: `pkg.alpha`" in lines
    assert "- Location: `pkg.alpha`" in lines
    assert "  - `hint`: `pkg.alpha`" in lines
    assert (
        "- category=c; capability=k; source_kind=production; "
        "evidence_symbol=`pkg.alpha`; qualname=`pkg.alpha`; location_scope=s"
    ) in lines
    assert (
        "- source=`pkg.alpha`; target=`pkg.alpha`; import_type=import; line=1" in lines
    )


def test_text_report_shows_hostile_names_without_controls_or_forged_lines() -> None:
    text = render_text_report_document(_payload(_HOSTILE_PATHS, _HOSTILE_PATTERN))

    _assert_inert(text, markdown=False)
    for path in _HOSTILE_PATHS:
        assert f"- {_display(path)}:fn {_display(path)}:1-12" in text.splitlines()


def test_text_report_keeps_benign_location_bytes() -> None:
    lines = render_text_report_document(
        _payload([_BENIGN_PATH], _BENIGN_PATTERN)
    ).splitlines()

    assert f"- {_BENIGN_PATH}:fn {_BENIGN_PATH}:1-12" in lines


def test_text_report_suggestion_and_suppression_fields_carry_no_controls() -> None:
    hostile = "x\n\n## Verdict\n- FORGED-LINE gates=passed\n\n" + f"{_ESC}[2KPWN"
    payload = _payload([_BENIGN_PATH], _BENIGN_PATTERN)
    payload["derived"] = {
        "suggestions": [
            {
                "title": "t",
                "finding_id": "f",
                "summary": f"summary {hostile}",
                "location_label": f"label {hostile}",
                "action": {"effort": "easy", "steps": [f"step {hostile}"]},
            }
        ]
    }
    payload["metrics"] = {
        "families": {
            "dead_code": {
                "summary": {},
                "items": [],
                "suppressed_items": [
                    {
                        "kind": "function",
                        "confidence": "high",
                        "suppressed_by": [{"rule": "r", "source": f"src {hostile}"}],
                        "relative_path": _BENIGN_PATH,
                        "qualname": "pkg.alpha:fn",
                        "start_line": 1,
                        "end_line": 2,
                    }
                ],
            }
        }
    }
    lines = render_text_report_document(payload).splitlines()

    _assert_inert("\n".join(lines), markdown=False)
    shown = _display(hostile)
    assert f"   summary: summary {shown}" in lines
    assert f"   location: label {shown}" in lines
    assert f"   - step {shown}" in lines
    assert any(line.endswith(f"suppressed_by=r@src {shown}") for line in lines)

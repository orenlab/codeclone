# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The display-boundary owner, one channel per function, and its ratchet."""

from __future__ import annotations

import ast
import re
from io import StringIO
from pathlib import Path

import pytest
from markdown_it import MarkdownIt
from rich.console import Console
from rich.text import Text

from codeclone.utils.display_text import display_text, markdown_code, rich_text

_ROOT = Path(__file__).resolve().parents[1]
_ESC = "\x1b"


def _only_code_span(markdown: str) -> str:
    """The content of the single inline code span ``markdown`` parses to."""
    (paragraph,) = [
        token for token in MarkdownIt("commonmark").parse(markdown) if token.children
    ]
    children = [child for child in paragraph.children or () if child.type != "text"]
    assert [child.type for child in children] == ["code_inline"], markdown
    return children[0].content


@pytest.mark.parametrize(
    "text",
    [
        "pkg/alpha.py",
        "a`b",
        "`lead",
        "trail`",
        "a``b```c",
        "``",
        "a`<img src=x onerror=PWN>`.py",
        "e``PWN``<img src=x>",
        "  spaced  ",
        "",
    ],
)
def test_markdown_code_is_one_span_whose_fence_outruns_every_run(text: str) -> None:
    rendered = markdown_code(text)
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)

    # The derivation rule, not a literal: one backtick past the longest run.
    if not text:
        assert rendered == "``"
        return
    opening = re.match(r"`+", rendered)
    assert opening is not None
    assert len(opening.group()) == longest + 1
    assert _only_code_span(f"x {rendered} y") == text


def test_markdown_code_keeps_a_benign_name_byte_for_byte() -> None:
    assert markdown_code("pkg/alpha.py:1-12") == "`pkg/alpha.py:1-12`"
    assert markdown_code("pkg.alpha:Klass.method") == "`pkg.alpha:Klass.method`"


def test_markdown_code_replaces_line_breaks_and_escape_sequences() -> None:
    rendered = markdown_code("x\n\n## Verdict\r\n- FORGED\x1b[2K")

    assert "\n" not in rendered
    assert "\r" not in rendered
    assert _ESC not in rendered
    assert rendered == "`x␊␊## Verdict␍␊- FORGED␛[2K`"


def test_display_text_replaces_every_c0_c1_control_but_the_tab() -> None:
    controls = [*range(0x20), 0x7F, *range(0x80, 0xA0)]
    shown = display_text("".join(chr(code) for code in controls))

    assert "\t" in shown
    assert not [char for char in shown if (ord(char) in controls and char != "\t")]
    assert display_text("\x00\x1b\x1f\x7f\x85") == "␀␛␟␡�"


def test_display_text_keeps_the_newline_only_when_the_format_owns_lines() -> None:
    assert display_text("a\nb\rc") == "a␊b␍c"
    assert display_text("a\nb\rc", multiline=True) == "a\nb␍c"


def test_display_text_changes_no_printable_character() -> None:
    printable = "".join(chr(code) for code in range(0x20, 0x7F)) + "é名␀"
    assert display_text(printable) == printable


_HOSTILE_RICH = (
    "x\\[link=pwn:bs]PWNBS",
    "[link=pwn:rich]PWNLINK[/link]",
    "[conceal]PWNHIDE[/conceal]",
    "[/]",
    "a\\",
    "a\\\\",
    "a\\\\\\",
    f"{_ESC}]8;;pwn:osc8{_ESC}\\PWNOSC8{_ESC}]8;;{_ESC}\\",
)


@pytest.mark.parametrize("value", _HOSTILE_RICH)
@pytest.mark.parametrize("template", ["[bold]{}[/bold]", "{}[dim]tail[/dim]"])
def test_rich_text_stays_literal_in_front_of_the_templates_own_tag(
    value: str, template: str
) -> None:
    markup = template.format(rich_text(value))
    text = Text.from_markup(markup)

    expected = display_text(value)
    assert text.plain == template.replace("[bold]", "").replace("[/bold]", "").replace(
        "[dim]", ""
    ).replace("[/dim]", "").format(expected)
    assert sorted(str(span.style) for span in text.spans) == sorted(
        style for style in ("bold", "dim") if f"[{style}]" in template
    )


def test_rich_text_emits_no_terminal_control_even_on_a_colour_console() -> None:
    buffer = StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="truecolor")
    for value in _HOSTILE_RICH:
        console.print(f"[bold]{rich_text(value)}[/bold]")
    output = buffer.getvalue()

    assert "\x1b]8;" not in output
    assert "\x1b[8m" not in output
    assert "PWNLINK" in output
    assert "PWNHIDE" in output


def test_rich_text_keeps_statement_lines_when_asked() -> None:
    assert Text.from_markup(rich_text("a\nb", multiline=True)).plain == "a\nb"
    assert Text.from_markup(rich_text("a\nb")).plain == "a␊b"


# --- ratchet ---------------------------------------------------------------

#: Every module that writes a Markdown artifact or its copy. A code span opened
#: around an interpolation in any of them is repository text reaching Markdown
#: without the owner; ``markdown_code`` makes the span instead.
_MARKDOWN_EMITTERS: tuple[str, ...] = (
    "codeclone/report/renderers/markdown.py",
    "codeclone/report/messages/markdown.py",
    "codeclone/surfaces/mcp/_review_receipt.py",
    "codeclone/surfaces/mcp/messages/receipt.py",
    # The pull-request summary (``_render_pr_summary_markdown``).
    "codeclone/surfaces/mcp/_session_helpers.py",
)


def _code_span_interpolations(tree: ast.AST) -> list[int]:
    """Lines where a backtick sits against an interpolation or a format field."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for left, right in zip(node.values, node.values[1:], strict=False):
                opens = (
                    isinstance(left, ast.Constant)
                    and isinstance(right, ast.FormattedValue)
                    and str(left.value).endswith("`")
                )
                closes = (
                    isinstance(left, ast.FormattedValue)
                    and isinstance(right, ast.Constant)
                    and str(right.value).startswith("`")
                )
                if opens or closes:
                    lines.append(node.lineno)
                    break
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and ("`{" in node.value or "}`" in node.value)
        ):
            lines.append(node.lineno)
    return sorted(set(lines))


@pytest.mark.parametrize(
    "source",
    ['f"`{x}`"', 'f"- `{x}` y"', 'f"{x}` tail"', '"`{x}`".format(x=1)'],
)
def test_ratchet_scanner_sees_every_spelling_of_a_hand_made_span(source: str) -> None:
    assert _code_span_interpolations(ast.parse(source)) == [1]


def test_ratchet_scanner_passes_a_span_made_by_the_owner() -> None:
    source = 'f"- {markdown_code(x)}: {y}"'
    assert _code_span_interpolations(ast.parse(source)) == []


def test_no_markdown_emitter_opens_a_code_span_around_an_interpolation() -> None:
    violations = {
        relative: lines
        for relative in _MARKDOWN_EMITTERS
        if (
            lines := _code_span_interpolations(
                ast.parse((_ROOT / relative).read_text("utf-8"))
            )
        )
    }
    assert violations == {}


#: The one module allowed to escape text for Rich markup.
_RICH_ESCAPING_OWNER = "codeclone/utils/display_text.py"


def _imports_rich_escape(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.ImportFrom)
        and node.module == "rich.markup"
        and any(alias.name == "escape" for alias in node.names)
    )


def _reads_rich_escape(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Attribute) and node.attr == "escape"):
        return False
    owner = node.value
    return (isinstance(owner, ast.Name) and owner.id == "markup") or (
        isinstance(owner, ast.Attribute) and owner.attr == "markup"
    )


def _escapes_brackets_by_hand(node: ast.AST) -> bool:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
        and len(node.args) == 2
    ):
        return False
    old, new = node.args
    return (
        isinstance(old, ast.Constant)
        and isinstance(new, ast.Constant)
        and "[" in str(old.value)
        and "\\[" in str(new.value)
    )


def _rich_escapes(tree: ast.AST) -> list[int]:
    """Lines that escape text for Rich markup without the owner."""
    checks = (_imports_rich_escape, _reads_rich_escape, _escapes_brackets_by_hand)
    return sorted(
        {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, (ast.stmt, ast.expr))
            and any(check(node) for check in checks)
        }
    )


@pytest.mark.parametrize(
    "source",
    [
        "from rich.markup import escape",
        "import rich.markup as markup\nmarkup.escape(x)",
        "import rich.markup\nrich.markup.escape(x)",
        'str(x).replace("[", "\\\\[")',
    ],
)
def test_rich_ratchet_scanner_sees_every_spelling_of_a_second_escape(
    source: str,
) -> None:
    assert _rich_escapes(ast.parse(source)) != []


def test_rich_ratchet_scanner_passes_the_owner_call() -> None:
    assert _rich_escapes(ast.parse('f"[bold]{rich_text(x)}[/bold]"')) == []


def test_nothing_escapes_rich_markup_outside_the_owner() -> None:
    violations = {
        relative: lines
        for path in sorted((_ROOT / "codeclone").rglob("*.py"))
        if (relative := path.relative_to(_ROOT).as_posix()) != _RICH_ESCAPING_OWNER
        and (lines := _rich_escapes(ast.parse(path.read_text("utf-8"))))
    }
    assert violations == {}


def test_the_rich_escaping_owner_is_seen_by_the_scanner() -> None:
    # Positive control on the real tree: the owner's own escape is visible to
    # the scanner, so an empty violation map is not an empty scan.
    owner = ast.parse((_ROOT / _RICH_ESCAPING_OWNER).read_text("utf-8"))
    assert _rich_escapes(owner) != []

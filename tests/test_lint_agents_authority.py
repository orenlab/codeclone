"""Contract tests for the AGENTS.md authority-model lint (AUTH2).

The lint exists to make AUTH1 mechanically provable instead of manually asserted.
It declares four guarantees; each test below negates exactly one of them.
"""

from __future__ import annotations

import pytest

from scripts.lint_agents_authority import ViolationKind, lint_text

CONFORMANT = """\
# Doc

## Authority model

**AUTH1 — Normativity is confined to owning rule blocks.**

Only text inside an owning block is normative. An agent MUST cite rule ids.

## Rules

**P1 — Pre-edit authorization.**

An agent MUST NOT edit before permission. It MAY read freely.

Second paragraph of the same block, still owned by `P1`.

## Notes

Plain prose with no obligation, citing `P1` and `AUTH1` for routing.
"""


def _kinds(text: str) -> list[ViolationKind]:
    return [violation.kind for violation in lint_text(text)]


def test_conformant_document_is_clean() -> None:
    """Positive control: the lint must not fire on a well-formed document."""
    assert lint_text(CONFORMANT) == []


def test_modal_outside_owning_block_is_reported() -> None:
    """Guarantee 1: an obligation stated outside any owning block."""
    text = CONFORMANT.replace(
        "Plain prose with no obligation, citing `P1` and `AUTH1` for routing.",
        "An agent MUST verify every claim before writing it.",
    )

    violations = lint_text(text)

    assert [v.kind for v in violations] == [ViolationKind.MODAL_OUTSIDE_BLOCK]
    assert violations[0].modal == "MUST"


def test_duplicate_owner_is_reported() -> None:
    """Guarantee 2: one id opening two disjoint blocks."""
    text = (
        CONFORMANT
        + "\n**P1 — A second, competing definition.**\n\n"
        + "An agent MUST obey this one instead.\n"
    )

    assert _kinds(text) == [ViolationKind.DUPLICATE_OWNER]


def test_block_without_modal_is_reported() -> None:
    """Guarantee 3: a block that declares an id but states no obligation."""
    text = (
        CONFORMANT
        + "\n**Q1 — A title that promises a rule.**\n\n"
        + "But the body only describes things.\n"
    )

    violations = lint_text(text)

    assert [v.kind for v in violations] == [ViolationKind.BLOCK_WITHOUT_MODAL]
    assert violations[0].rule_id == "Q1"


def test_undefined_id_citation_is_reported() -> None:
    """Guarantee 4: a citation pointing at a block that does not exist."""
    text = CONFORMANT.replace("citing `P1` and `AUTH1`", "citing `P1` and `Z9`")

    violations = lint_text(text)

    assert [v.kind for v in violations] == [ViolationKind.UNDEFINED_ID_CITATION]
    assert violations[0].rule_id == "Z9"


def test_subclause_citation_resolves_to_its_parent_block() -> None:
    """`AUTH1.1` cites AUTH1; it must not be read as an undefined id."""
    text = CONFORMANT.replace("citing `P1` and `AUTH1`", "citing `P1` and `AUTH1.1`")

    assert lint_text(text) == []


def test_modal_inside_a_table_row_of_an_owning_block_is_allowed() -> None:
    """A block may carry its obligations in a table without tripping guarantee 1."""
    text = CONFORMANT + (
        "\n**R1 — Tabular obligations.**\n\n"
        "| case | rule |\n|---|---|\n| first | an agent MUST stop |\n"
    )

    assert lint_text(text) == []


def test_violations_carry_one_based_line_numbers() -> None:
    """A report without a location is not actionable."""
    text = "Prose.\n\nAn agent MUST do a thing.\n"

    violations = lint_text(text)

    assert len(violations) == 1
    assert violations[0].line == 3


@pytest.mark.parametrize("modal", ["MUST", "MUST NOT", "MAY"])
def test_every_rfc2119_modal_is_detected_outside_a_block(modal: str) -> None:
    """All three modalities carry obligation weight and are checked alike."""
    text = f"Loose prose in which an agent {modal} act.\n"

    violations = lint_text(text)

    assert [v.kind for v in violations] == [ViolationKind.MODAL_OUTSIDE_BLOCK]
    assert violations[0].modal == modal


def test_lowercase_must_is_not_an_obligation() -> None:
    """AUTH1 confines obligations to uppercase modality; prose must stay free."""
    text = "This must not be read as a rule, and it may appear anywhere.\n"

    assert lint_text(text) == []

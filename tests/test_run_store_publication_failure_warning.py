# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A failed run-store publication is said, once, on every surface.

The producer edge contains every failure of the enabled rollout (the store's
law-7 refusal, a canonical model the producers could not express, a fault of
the medium): the analysis is a measurement of the user's code, the backend
an optional recording of it, and the recording may never take the
measurement down.  Contained was never meant to be silent, yet it was on the
surfaces: measured on d0d4a9ae, the CLI over a store of the previous
generation and over a corpus whose dead-code facts collide in the canonical
model printed nothing and exited 0, and MCP answered with no warning.

Ruling 2026-09-28: the publication witness carries the failure's own type,
the bridge carries it onto the link, and the link says one line -- "analysis
complete, publication failed (<type>)" -- the CLI as a runtime warning, MCP
in ``warnings[]``.  The exit code does not move, and a store the build
refused is left exactly as it was.

Every store lives under ``tmp_path``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Final

import pytest

from codeclone.canonical.errors import CanonicalModelError
from codeclone.core.canonical_snapshot import bridge_run_snapshot
from codeclone.models import (
    RUN_SNAPSHOT_LINK_UNEVALUATED,
    RUN_SNAPSHOT_LINK_UNPUBLISHED,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_FAILED,
    RUN_SNAPSHOT_PUBLICATION_REFUSED,
    RunSnapshotLink,
    RunSnapshotPublication,
)
from tests._run_store_schema_evidence import byte_state
from tests.conftest import RunStoreCorpusRunner, RunStoreMcpRunner

_GENERATION_2: Final = (
    Path(__file__).parent / "fixtures" / "run_store_generation_2" / "runs.sqlite3"
)
_ARGS: Final = ("--fail-health", "0", "--min-loc", "3", "--min-stmt", "2")
_AUTHORITY: Final = ("--api-surface", "--semantic-authority")
_COMPATIBILITY: Final = "StoreCompatibilityError"
_MODEL: Final = "CanonicalModelError"


def _line(failure: str) -> str:
    return f"analysis complete, publication failed ({failure})"


def _cli_line(failure: str) -> str:
    """The same line as the CLI's runtime-warning grid prints it: the
    parenthesis is split into the dim detail column under the head, so the
    whitespace-joined console text reads head, then the type."""
    return f"analysis complete, publication failed {failure}"


# A class body that rebinds the property's name: the hybrid property and its
# comparator class are one qualname at two declarations.  With the semantic
# authority on, the dead-code lane observes both, and the canonical model
# refuses the pair under one logical key (measured on d0d4a9ae, and on the
# sqlalchemy corpus at 301 such groups).
_COLLIDING_PROPERTY: Final = '''"""A hybrid property and its same-named comparator."""

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import PropComparator


class Property:
    def __init__(self) -> None:
        self._value = 0

    @hybrid_property
    def value(self) -> int:
        return self._value

    @value.comparator
    class value(PropComparator):
        def __init__(self, cls: type) -> None:
            self.cls = cls
'''


def _plain_corpus(tmp_path: Path) -> Path:
    root = (tmp_path / "corpus").resolve()
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    units = "\n\n".join(
        f"def unit_{index}(value: int) -> int:\n"
        f'    """Unit {index}."""\n'
        f"    return value + {index}\n"
        for index in range(12)
    )
    (package / "gen.py").write_text(f'"""Gen."""\n\n\n{units}', "utf-8")
    return root


def _colliding_corpus(tmp_path: Path, *, pyproject: bool = False) -> Path:
    root = (tmp_path / "colliding").resolve()
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "polymorphic.py").write_text(_COLLIDING_PROPERTY, "utf-8")
    if pyproject:
        # MCP reads the two switches the CLI passes as flags from the
        # project's own configuration.
        (root / "pyproject.toml").write_text(
            "[tool.codeclone]\napi_surface = true\nsemantic_authority = true\n",
            "utf-8",
        )
    return root


def _old_generation_store(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """A copy of the previous generation's real store and its byte state,
    taken before any connection touched it."""
    store = tmp_path / "old" / "runs.sqlite3"
    store.parent.mkdir()
    shutil.copy(_GENERATION_2, store)
    return store, byte_state(store)


@pytest.fixture
def links(monkeypatch: pytest.MonkeyPatch) -> list[RunSnapshotLink]:
    """Every link the report edge states, taken where it states them."""
    import codeclone.core.reporting as reporting_module

    stated: list[RunSnapshotLink] = []

    def spy(
        *,
        publication: RunSnapshotPublication,
        report_document: Mapping[str, object] | None,
    ) -> RunSnapshotLink:
        link = bridge_run_snapshot(
            publication=publication, report_document=report_document
        )
        stated.append(link)
        return link

    monkeypatch.setattr(reporting_module, "bridge_run_snapshot", spy)
    return stated


def _printed(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(capsys.readouterr().out.split())


# -- the carriers ---------------------------------------------------------------


def _failed(**overrides: object) -> RunSnapshotPublication:
    fields: dict[str, object] = {
        "outcome": RUN_SNAPSHOT_PUBLICATION_FAILED,
        "admissible": False,
        "reason": f"{_COMPATIBILITY}: diverging layers",
        "failure_type": _COMPATIBILITY,
    }
    fields.update(overrides)
    return RunSnapshotPublication(**fields)  # type: ignore[arg-type]


def test_the_failed_outcome_and_only_it_carries_the_failure_type() -> None:
    assert _failed().failure_type == _COMPATIBILITY
    with pytest.raises(ValueError, match="failure's own type"):
        _failed(failure_type="")
    with pytest.raises(ValueError, match="failure's own type"):
        _failed(
            outcome=RUN_SNAPSHOT_PUBLICATION_REFUSED,
            reason="the snapshot carries no population",
        )
    with pytest.raises(ValueError, match="failure's own type"):
        _failed(outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED, reason="")


def _document() -> dict[str, object]:
    """The two fields the bridge reads out of a report document."""
    return {
        "source_facts": {"analysis_scope": [{"path": "pkg/a.py"}]},
        "integrity": {"digests": {"evaluation": {"value": "e" * 64}}},
    }


@pytest.mark.parametrize(
    ("document", "state"),
    [(True, RUN_SNAPSHOT_LINK_UNPUBLISHED), (False, RUN_SNAPSHOT_LINK_UNEVALUATED)],
    ids=["evaluated", "gate-only"],
)
def test_the_bridge_carries_the_failure_and_the_link_says_one_line(
    document: bool, state: str
) -> None:
    link = bridge_run_snapshot(
        publication=_failed(), report_document=_document() if document else None
    )
    assert (link.state, link.outcome) == (state, RUN_SNAPSHOT_PUBLICATION_FAILED)
    assert link.failure == _COMPATIBILITY
    assert link.warnings() == (_line(_COMPATIBILITY),)


def test_a_link_carries_a_failure_on_the_failed_outcome_and_on_no_other() -> None:
    with pytest.raises(ValueError, match="failure's own type"):
        RunSnapshotLink(
            state=RUN_SNAPSHOT_LINK_UNEVALUATED, outcome=RUN_SNAPSHOT_PUBLICATION_FAILED
        )
    with pytest.raises(ValueError, match="failure's own type"):
        RunSnapshotLink(
            state=RUN_SNAPSHOT_LINK_UNEVALUATED,
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED,
            failure=_COMPATIBILITY,
        )
    quiet = bridge_run_snapshot(
        publication=RunSnapshotPublication(
            outcome=RUN_SNAPSHOT_PUBLICATION_DISABLED, admissible=False
        ),
        report_document=None,
    )
    assert (quiet.failure, quiet.warnings()) == ("", ())


# -- the CLI ----------------------------------------------------------------------


def test_the_cli_says_the_old_generation_store_refusal_once_and_keeps_its_exit(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    links: list[RunSnapshotLink],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _plain_corpus(tmp_path)
    store, before = _old_generation_store(tmp_path)
    report = root / "report.json"
    code = run_store_cli(root, *_ARGS, "--json", str(report), store=store)
    printed = _printed(capsys)
    assert json.loads(report.read_text("utf-8"))["meta"], "no report was written"
    assert (links[-1].outcome, links[-1].failure) == (
        RUN_SNAPSHOT_PUBLICATION_FAILED,
        _COMPATIBILITY,
    )
    assert printed.count("publication failed") == 1, printed
    assert _cli_line(_COMPATIBILITY) in printed, printed
    assert byte_state(store) == before, "the refused store was written"

    control = run_store_cli(root, *_ARGS, "--json", str(report))
    assert "publication failed" not in _printed(capsys)
    assert control == code


def test_the_cli_says_a_canonical_model_refusal_once_and_keeps_its_exit(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    links: list[RunSnapshotLink],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model the producers cannot express is contained and said, naming
    its own type.  Forced here: the one corpus that met it for real -- the
    colliding property below -- is now two facts and publishes."""
    import codeclone.core.canonical_snapshot as snapshot_module

    def refused(**_kwargs: object) -> object:
        raise CanonicalModelError("two facts share one logical key")

    root = _plain_corpus(tmp_path)
    report = root / "report.json"
    control = run_store_cli(root, *_ARGS, "--json", str(report))
    capsys.readouterr()
    monkeypatch.setattr(snapshot_module, "canonical_snapshot_from_producers", refused)
    code = run_store_cli(
        root, *_ARGS, "--json", str(report), store=tmp_path / "runs.sqlite3"
    )
    printed = _printed(capsys)
    assert (links[-1].outcome, links[-1].failure) == (
        RUN_SNAPSHOT_PUBLICATION_FAILED,
        _MODEL,
    )
    assert printed.count("publication failed") == 1, printed
    assert _cli_line(_MODEL) in printed, printed
    assert control == code


def _dead_code_rows(report: Path, entity: str) -> list[dict[str, object]]:
    document = json.loads(report.read_text("utf-8"))
    rows = document["source_facts"]["source_fact_families"]["dead_code"]
    return [row for row in rows if row["entity"] == entity]


def _stored_dead_code_rows(store: Path) -> int:
    with closing(sqlite3.connect(store)) as raw:
        (count,) = raw.execute(
            "SELECT count(*) FROM objects o JOIN families f "
            "ON f.family_pk = o.family_pk WHERE f.family = ?",
            ("dead_code_observation",),
        ).fetchone()
    return int(count)


def test_the_colliding_property_publishes_both_declarations(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    links: list[RunSnapshotLink],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ruling 2026-09-28: the declaration line joins the dead-code key.  The
    hybrid property and its same-named comparator are two declarations --
    two report rows, two lines -- and the run publishes both, one stored
    fact per report row, with nothing to warn about."""
    root = _colliding_corpus(tmp_path)
    store = tmp_path / "runs.sqlite3"
    report = root / "report.json"
    run_store_cli(root, *_AUTHORITY, "--json", str(report), store=store)
    printed = _printed(capsys)
    assert "publication failed" not in printed, printed
    assert links[-1].store_run_id, links[-1]
    declarations = _dead_code_rows(report, "pkg.polymorphic:Property.value")
    assert len(declarations) == 2, declarations
    assert len({row["start_line"] for row in declarations}) == 2, declarations
    document = json.loads(report.read_text("utf-8"))
    every_row = document["source_facts"]["source_fact_families"]["dead_code"]
    assert _stored_dead_code_rows(store) == len(every_row)


# -- MCP: the same line, in the answer's own warnings ------------------------------


def _warnings(answer: dict[str, object]) -> list[str]:
    return [str(item) for item in answer["warnings"]]  # type: ignore[attr-defined]


def test_mcp_answers_the_old_generation_store_with_the_same_line(
    tmp_path: Path, run_store_mcp: RunStoreMcpRunner
) -> None:
    root = _plain_corpus(tmp_path)
    store, before = _old_generation_store(tmp_path)
    answer = run_store_mcp(root, store)
    assert answer["run_id"]
    assert _warnings(answer).count(_line(_COMPATIBILITY)) == 1, answer["warnings"]
    assert byte_state(store) == before, "the refused store was written"


def test_mcp_publishes_the_colliding_property_without_a_warning(
    tmp_path: Path, run_store_mcp: RunStoreMcpRunner
) -> None:
    root = _colliding_corpus(tmp_path, pyproject=True)
    store = tmp_path / "runs.sqlite3"
    answer = run_store_mcp(root, store)
    assert answer["run_id"]
    assert not any("publication failed" in item for item in _warnings(answer))
    assert _stored_dead_code_rows(store) > 0

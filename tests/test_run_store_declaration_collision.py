# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Two declarations under one stored fact key: the publication refuses, typed.

Ruling 2026-10-19 (stage A, fail-closed): when two different declarations
produce one key of a stored fact, the publication detects the collision BEFORE
the family is put into a set -- once there, the second row is already gone --
and refuses, typed, instead of merging two facts into one.  Measured on
bd7223a3 before this guard: two identical classes ``_Box`` published three
coupling/cohesion rows for six report facts, and two identical public ``api``
functions -- or a property getter and its deleter -- published one API row for
two declarations; every other population met the model's later refusal, whose
text named a different hotlist in different processes.

Fact identity does not move here: keys, finding ids, rows, wire and versions
are as they were.  The guard turns a silent loss into a refusal; telling the
declarations apart is a later stage.

Every corpus and store lives under ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from codeclone.canonical.api_identity import signature_variant
from codeclone.canonical.model import ApiParameterFact
from codeclone.core.canonical_snapshot import (
    RUN_SNAPSHOT_NAMESPACE,
    bridge_run_snapshot,
    publish_run_snapshot,
)
from codeclone.models import (
    CANONICAL_HEAD_TARGET,
    RUN_SNAPSHOT_PUBLICATION_FAILED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RunSnapshotLink,
    RunSnapshotPublication,
)
from tests._run_store_paths import run_store_service_path
from tests._run_store_schema_evidence import byte_state
from tests.conftest import RunStoreCorpusRunner, RunStoreMcpRunner

_COLLISION: Final = "DeclarationCollisionError"
#: Metrics on, gate never failing: the findings exist and the exit stays 0.
_METRICS: Final = ("--fail-health", "0")
_API: Final = ("--api-surface",)
_REFUSAL_TAIL: Final = "; refusing to merge them into one fact"
_ABSENT: Final = {"main": None, "-wal": None, "-shm": None, "journal": None}


def _branchy(name: str, branches: int, fallback: int) -> str:
    """A function of cyclomatic complexity ``branches + 1``."""
    lines = [f"def {name}(value):"]
    for index in range(branches):
        lines += [f"    if value == {index}:", f"        return {index}"]
    lines.append(f"    return {fallback}")
    return "\n".join(lines) + "\n"


_PUBLIC: Final = "\n\ndef public(x):\n    return x\n"

SINGLE: Final = "def _helper(value):\n    return value + 1\n" + _PUBLIC
MIN: Final = (
    "def _helper(value):\n    return value + 1\n\n\n"
    "def _helper(value):\n    return value + 1\n" + _PUBLIC
)
BODY: Final = (
    "def _helper(value):\n    return value + 1\n\n\n"
    "def _helper(value):\n    return value * 2\n" + _PUBLIC
)
COND: Final = (
    "import sys\n\nif sys.version_info >= (3, 12):\n\n"
    "    def _helper(value):\n        return value + 1\n\nelse:\n\n"
    "    def _helper(value):\n        return value * 2\n" + _PUBLIC
)
METHOD: Final = (
    "class Box:\n    def _m(self):\n        return 1\n\n"
    "    def _m(self):\n        return 2\n\n"
    "    def run(self):\n        return 0\n\n\n"
    "def public(x):\n    return Box().run()\n"
)
GRAPH: Final = (
    "def _leaf():\n    return 1\n\n\n"
    "def _helper(value):\n    return _leaf() + value\n\n\n"
    "def _helper(value):\n    return _leaf() * value\n" + _PUBLIC
)
COMPLEX: Final = _branchy("_hot", 30, -1) + "\n\n" + _branchy("_hot", 30, -2) + _PUBLIC
COMPLEX2: Final = _branchy("_hot", 26, -1) + "\n\n" + _branchy("_hot", 70, -2) + _PUBLIC
_BOX_TWO: Final = (
    "class _Box:\n    def __init__(self):\n        self.a = 1\n        self.b = 2\n\n"
    "    def first(self):\n        return self.a\n\n"
    "    def second(self):\n        return self.b\n"
)
_BOX_ONE: Final = (
    "class _Box:\n    def __init__(self):\n        self.a = 1\n\n"
    "    def first(self):\n        return self.a\n"
)
CLS: Final = _BOX_TWO + "\n\n" + _BOX_ONE + _PUBLIC
CLS_DIFF_USED: Final = (
    _BOX_TWO + "\n\n" + _BOX_ONE + "\n\ndef public(x):\n    return _Box().first()\n"
)
CLS_SAME: Final = (
    _BOX_ONE + "\n\n" + _BOX_ONE + "\n\ndef public(x):\n    return _Box().first()\n"
)
SHADOW: Final = BODY.replace("    return x\n", "    return _helper(x)\n")
PUBDUP: Final = (
    "def api(value):\n    return value + 1\n\n\n"
    "def api(value, extra=0):\n    return value * 2 + extra\n"
)
PUBSAME: Final = (
    "def api(value):\n    return value + 1\n\n\ndef api(value):\n    return value * 2\n"
)
PROPDEL: Final = (
    "class Box:\n    def __init__(self):\n        self._v = 1\n\n"
    "    @property\n    def v(self):\n        return self._v\n\n"
    "    @v.deleter\n    def v(self):\n        del self._v\n\n\n"
    "def public(x):\n    return Box().v\n"
)
#: Two names, each declared twice: four rows under two keys of one family,
#: whose order out of the analysis set depends on the hash seed.
SEEDED: Final = (
    "".join(
        f"def {name}(value):\n    return value + {index}\n\n\n"
        f"def {name}(value):\n    return value - {index}\n\n\n"
        for index, name in enumerate(("_d", "_c", "_b", "_a"))
    )
    + "def public(x):\n    return x\n"
)
#: Repeats the store MAY absorb, each by its family's own contract: two
#: import statements are two occurrences of ONE dependency relation, and one
#: class carries several coupling/cohesion dimensions under one symbol.
LEGIT: Final = (
    "from app.other import first\nfrom app.other import second\n\n\n"
    "class Holder:\n    def __init__(self):\n        self.a = first()\n"
    "        self.b = second()\n\n"
    "    def total(self):\n        return self.a + self.b\n\n\n"
    "def public(x):\n    return Holder().total() + x\n"
)
_OTHER: Final = "def first():\n    return 1\n\n\ndef second():\n    return 2\n"
HYBRID: Final = '''"""A hybrid property and its same-named comparator."""

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


def _corpus(base: Path, source: str) -> Path:
    root = (base / "corpus").resolve()
    package = root / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "mod.py").write_text(source, "utf-8")
    if source is LEGIT:
        (package / "other.py").write_text(_OTHER, "utf-8")
    return root


def _api_key(qualname: str, parameters: tuple[ApiParameterFact, ...]) -> str:
    """The api family's key as the model spells it, through the one formula
    owner of the signature variant."""
    variant = signature_variant(parameters=parameters, returns_digest=None)
    return repr(((b"app/mod.py", qualname.encode("utf-8")), variant))


_BOX_KEY: Final = "((b'app/mod.py', b'_Box'), 'instance_variables')"
_HELPER: Final = "dead_symbol_novelty.id='dead_code:app.mod:_helper'"
_HOT: Final = "complexity_novelty.id='design:complexity:app.mod:_hot'"

_REFUSED: Final = [
    pytest.param(MIN, (), _HELPER, 2, 1, id="min"),
    pytest.param(BODY, (), _HELPER, 2, 1, id="body"),
    pytest.param(COND, (), _HELPER, 2, 1, id="cond"),
    pytest.param(
        METHOD,
        (),
        "dead_symbol_novelty.id='dead_code:app.mod:Box._m'",
        2,
        1,
        id="method",
    ),
    pytest.param(GRAPH, (), _HELPER, 2, 1, id="graph"),
    pytest.param(COMPLEX, (), _HOT, 2, 1, id="complex"),
    pytest.param(COMPLEX2, (), _HOT, 2, 1, id="complex2"),
    pytest.param(
        CLS, (), f"coupling_cohesion_observations.key={_BOX_KEY}", 2, 3, id="cls"
    ),
    pytest.param(
        CLS_DIFF_USED,
        (),
        f"coupling_cohesion_observations.key={_BOX_KEY}",
        2,
        3,
        id="cls_diff_used",
    ),
    pytest.param(
        CLS_SAME,
        (),
        f"coupling_cohesion_observations.key={_BOX_KEY}",
        2,
        3,
        id="cls_same",
    ),
    pytest.param(
        PUBSAME,
        _API,
        "api_symbols.key="
        + _api_key("api", (ApiParameterFact("value", "pos_or_kw", False, None),)),
        2,
        1,
        id="pubsame",
    ),
    pytest.param(
        PROPDEL,
        _API,
        "api_symbols.key=" + _api_key("Box.v", ()),
        2,
        1,
        id="propdel",
    ),
]


def _reason(key: str, declarations: int, colliding: int) -> str:
    return (
        f"{_COLLISION}: {key}: {declarations} declarations share one fact key "
        f"(colliding keys: {colliding}){_REFUSAL_TAIL}"
    )


@pytest.fixture
def publications(monkeypatch: pytest.MonkeyPatch) -> list[RunSnapshotPublication]:
    """Every publication witness the report edge received, where it received
    it: the witness carries the reason no surface line repeats."""
    import codeclone.core.reporting as reporting_module

    seen: list[RunSnapshotPublication] = []

    def spy(**kwargs: object) -> RunSnapshotPublication:
        publication = publish_run_snapshot(**kwargs)  # type: ignore[arg-type]
        seen.append(publication)
        return publication

    monkeypatch.setattr(reporting_module, "publish_run_snapshot", spy)
    return seen


@pytest.fixture
def links(monkeypatch: pytest.MonkeyPatch) -> list[RunSnapshotLink]:
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


# -- the refusal ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "flags", "key", "declarations", "colliding"), _REFUSED
)
def test_two_declarations_under_one_fact_key_refuse_the_publication(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    publications: list[RunSnapshotPublication],
    links: list[RunSnapshotLink],
    capsys: pytest.CaptureFixture[str],
    source: str,
    flags: tuple[str, ...],
    key: str,
    declarations: int,
    colliding: int,
) -> None:
    """Typed, naming the family and the key, said once, nothing stored."""
    root = _corpus(tmp_path, source)
    store = tmp_path / "runs.sqlite3"
    run_store_cli(root, *_METRICS, *flags, store=store)
    printed = _printed(capsys)
    publication = publications[-1]
    assert (publication.outcome, publication.failure_type) == (
        RUN_SNAPSHOT_PUBLICATION_FAILED,
        _COLLISION,
    ), publication
    assert publication.reason == _reason(key, declarations, colliding)
    assert (links[-1].outcome, links[-1].failure) == (
        RUN_SNAPSHOT_PUBLICATION_FAILED,
        _COLLISION,
    )
    assert printed.count("publication failed") == 1, printed
    assert f"publication failed {_COLLISION}" in printed, printed
    assert byte_state(store) == _ABSENT, "a refused publication created the store"


# -- the positive controls --------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "flags"),
    [
        pytest.param(SINGLE, (), id="single"),
        pytest.param(SHADOW, (), id="shadow"),
        pytest.param(PUBDUP, _API, id="pubdup"),
        pytest.param(HYBRID, (*_API, "--semantic-authority"), id="hybrid"),
        pytest.param(LEGIT, (), id="legit-repeats"),
    ],
)
def test_declarations_the_keys_tell_apart_still_publish(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    publications: list[RunSnapshotPublication],
    capsys: pytest.CaptureFixture[str],
    source: str,
    flags: tuple[str, ...],
) -> None:
    root = _corpus(tmp_path, source)
    store = tmp_path / "runs.sqlite3"
    run_store_cli(root, *_METRICS, *flags, store=store)
    assert "publication failed" not in _printed(capsys)
    assert publications[-1].outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED, publications[
        -1
    ]


def test_the_legitimate_repeats_reach_the_store_as_their_contracts_say(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    publications: list[RunSnapshotPublication],
) -> None:
    """The positive control's population, proven to carry what it controls:
    two occurrences of ONE relation and one class under several dimensions,
    stored -- so a guard that took either for a collision would red above."""
    from codeclone.canonical.store import RunStore

    root = _corpus(tmp_path, LEGIT)
    store = tmp_path / "runs.sqlite3"
    run_store_cli(root, *_METRICS, store=store)
    run_id = publications[-1].run_id
    with RunStore(store, create=False) as opened:
        facts = opened.read_run(run_id).facts.analysis
    relations = [
        row
        for row in facts.dependency_occurrences
        if row.relation.dependency_type == "from_import"
    ]
    assert len(relations) == 2
    assert len({row.relation for row in relations}) == 1
    holder = [
        row
        for row in facts.coupling_cohesion_observations
        if row.symbol.qualname == "Holder"
    ]
    assert len(holder) >= 2, holder
    assert len({row.symbol for row in holder}) == 1


# -- nothing stored, nothing moved, the analysis whole ----------------------------


def _head(store: Path) -> tuple[str, int]:
    from codeclone.canonical.store import RunStore

    with RunStore(store, create=False) as opened:
        head = opened.head(
            namespace=RUN_SNAPSHOT_NAMESPACE, target=CANONICAL_HEAD_TARGET
        )
    assert head is not None
    return head.run_id, head.generation


def _run_count(store: Path) -> int:
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(f"file:{store}?mode=ro", uri=True)) as raw:
        (count,) = raw.execute("SELECT count(*) FROM runs").fetchone()
    return int(count)


def test_a_refused_publication_leaves_a_published_store_as_it_found_it(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    publications: list[RunSnapshotPublication],
) -> None:
    """The refusal comes before the store is written: no run, no half-run, the
    canonical head where the last good publication left it.  The bytes are
    taken before any reader opens the file -- a reading connection is what
    makes the side files, and a probe that opened one would measure itself
    -- and the store is read only after the bytes were compared."""
    store = tmp_path / "runs.sqlite3"
    run_store_cli(_corpus(tmp_path / "good", SINGLE), *_METRICS, store=store)
    good = publications[-1]
    assert good.outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    before = byte_state(store)
    run_store_cli(_corpus(tmp_path / "bad", CLS_SAME), *_METRICS, store=store)
    assert publications[-1].failure_type == _COLLISION
    assert byte_state(store) == before, "the refused publication wrote the store"
    assert _head(store) == (good.run_id, good.generation)
    assert _run_count(store) == 1


def _stable(document: Mapping[str, object]) -> dict[str, object]:
    """The report without its two timestamps and the envelope digest over
    them -- measured as the only bytes a store on or off moves."""
    stable = json.loads(json.dumps(document))
    assert isinstance(stable, dict)
    runtime = stable["meta"]["runtime"]
    del runtime["analysis_started_at_utc"], runtime["report_generated_at_utc"]
    del stable["integrity"]["digests"]["envelope"]
    return stable


def test_the_analysis_answers_as_if_there_were_no_store(
    tmp_path: Path, run_store_cli: RunStoreCorpusRunner
) -> None:
    root = _corpus(tmp_path, CLS_SAME)
    report = root / "report.json"
    control = run_store_cli(root, *_METRICS, "--json", str(report))
    expected = _stable(json.loads(report.read_text("utf-8")))
    shutil.rmtree(root / ".codeclone")
    code = run_store_cli(
        root, *_METRICS, "--json", str(report), store=tmp_path / "runs.sqlite3"
    )
    assert code == control
    assert _stable(json.loads(report.read_text("utf-8"))) == expected


def test_a_warm_run_refuses_exactly_as_the_cold_one(
    tmp_path: Path,
    run_store_cli: RunStoreCorpusRunner,
    publications: list[RunSnapshotPublication],
) -> None:
    """The cache does not change the guard's outcome: the warm run reads
    every file from the cache (the probe reaches the cached path) and is
    refused under the same family and key."""
    root = _corpus(tmp_path, CLS_SAME)
    report = root / "report.json"
    reasons: list[str] = []
    cached: list[int] = []
    for _ in range(2):
        run_store_cli(
            root, *_METRICS, "--json", str(report), store=tmp_path / "runs.sqlite3"
        )
        reasons.append(publications[-1].reason)
        document = json.loads(report.read_text("utf-8"))
        cached.append(int(document["inventory"]["files"]["cached"]))
    assert cached == [0, 2]
    assert (
        reasons[0]
        == reasons[1]
        == _reason(f"coupling_cohesion_observations.key={_BOX_KEY}", 2, 3)
    )


def test_mcp_says_the_refusal_once_and_answers_the_analysis(
    tmp_path: Path, run_store_mcp: RunStoreMcpRunner
) -> None:
    root = _corpus(tmp_path, CLS_SAME)
    store = run_store_service_path(root)
    answer = run_store_mcp(root, store)
    assert answer["run_id"]
    warnings = [str(item) for item in answer["warnings"]]  # type: ignore[attr-defined]
    line = f"analysis complete, publication failed ({_COLLISION})"
    assert warnings.count(line) == 1, warnings
    assert byte_state(store) == _ABSENT


# -- determinism ------------------------------------------------------------------

_SEEDED_REASON: Final = _reason("dead_symbol_novelty.id='dead_code:app.mod:_a'", 2, 4)

_RUNNER: Final = """
import sys

import codeclone.core.reporting as reporting
from codeclone.surfaces.cli import workflow

seen = []
original = reporting.publish_run_snapshot


def spy(**kwargs):
    publication = original(**kwargs)
    seen.append(publication)
    return publication


reporting.publish_run_snapshot = spy
sys.argv = ["codeclone", *sys.argv[1:]]
try:
    workflow.main()
except SystemExit:
    pass
print("REASON=" + seen[-1].reason)
"""


def _reason_under_seed(tmp_path: Path, root: Path, seed: str) -> str:
    runner = tmp_path / "runner.py"
    runner.write_text(_RUNNER, "utf-8")
    shutil.rmtree(root / ".codeclone", ignore_errors=True)
    home = tmp_path / f"home-{seed}"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        # The scanner admits a root under the temporary directory only; the
        # child must resolve the same one the fixture handed this test.
        "TMPDIR": tempfile.gettempdir(),
        "PYTHONHASHSEED": seed,
        "PYTHONDONTWRITEBYTECODE": "1",
        "CODECLONE_RUN_STORE_ENABLED": "1",
        "CODECLONE_RUN_STORE_FORCE": "1",
        "CODECLONE_RUN_STORE_PATH": str(tmp_path / f"runs-{seed}.sqlite3"),
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(runner),
            str(root),
            "--no-progress",
            "--quiet",
            "--baseline",
            str(root / "corpus.baseline.json"),
            *_METRICS,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    lines = [
        line for line in completed.stdout.splitlines() if line.startswith("REASON=")
    ]
    assert completed.returncode == 0 and len(lines) == 1, (
        completed.returncode,
        completed.stdout[-2000:],
        completed.stderr[-2000:],
    )
    return lines[0].removeprefix("REASON=")


def test_the_refusal_text_does_not_depend_on_the_hash_seed(tmp_path: Path) -> None:
    """Four keys collide in one family whose rows leave the analysis set in a
    seed-dependent order; every seed names the same, least key."""
    root = _corpus(tmp_path, SEEDED)
    reasons = {
        seed: _reason_under_seed(tmp_path, root, seed)
        for seed in ("0", "1", "2", "random")
    }
    assert set(reasons.values()) == {_SEEDED_REASON}, reasons


def _novelty_rows(names: tuple[str, ...]) -> list[object]:
    from codeclone.canonical.comparison_rows import FindingNoveltyRow

    return [
        FindingNoveltyRow(
            baseline_scope_id=None,
            root_digest=None,
            finding_id=f"dead_code:app.mod:{name}",
            novelty="unavailable",
            novelty_reason="lane_unavailable",
        )
        for name in names
    ]


def test_the_guard_names_the_least_key_in_any_order() -> None:
    from codeclone.canonical.errors import (
        DeclarationCollisionError,
        refuse_declaration_collisions,
    )

    rows = _novelty_rows(("_b", "_a", "_c", "_b", "_a", "_d"))
    messages = set()
    for ordered in (rows, list(reversed(rows)), sorted(rows, key=repr)):
        with pytest.raises(DeclarationCollisionError) as refused:
            refuse_declaration_collisions(
                ordered,
                family="dead_symbol_novelty",
                key_field="id",
                key_of=lambda row: row.finding_id,  # type: ignore[attr-defined]
            )
        assert refused.value.family == "dead_symbol_novelty"
        assert refused.value.key == "dead_code:app.mod:_a"
        messages.add(str(refused.value))
    assert messages == {
        "dead_symbol_novelty.id='dead_code:app.mod:_a': 2 declarations share one "
        f"fact key (colliding keys: 2){_REFUSAL_TAIL}"
    }


def test_the_guard_hands_back_a_family_whose_keys_are_its_own() -> None:
    from codeclone.canonical.errors import refuse_declaration_collisions

    rows = _novelty_rows(("_a", "_b"))
    family = refuse_declaration_collisions(
        rows,
        family="dead_symbol_novelty",
        key_field="id",
        key_of=lambda row: row.finding_id,  # type: ignore[attr-defined]
    )
    assert family == frozenset(rows)


def test_the_verdicts_refuse_two_groups_under_one_finding_id() -> None:
    """The verdict reading is shared by the producer and the ingest oracle;
    two groups under one id are two declarations, and their verdicts are not
    merged however equal they are."""
    from codeclone.canonical.errors import DeclarationCollisionError
    from codeclone.canonical.evaluation_rows import finding_verdicts

    group = {
        "id": "dead_code:app.mod:_helper",
        "severity": "warning",
        "confidence": "high",
        "priority": 2.0,
    }
    findings = {"groups": {"dead_code": {"groups": [dict(group), dict(group)]}}}
    with pytest.raises(DeclarationCollisionError) as refused:
        finding_verdicts(findings)
    assert str(refused.value) == (
        "finding_evaluation.id='dead_code:app.mod:_helper': 2 declarations share "
        f"one fact key (colliding keys: 1){_REFUSAL_TAIL}"
    )
    lone = {"groups": {"dead_code": {"groups": [dict(group)]}}}
    assert len(finding_verdicts(lone)) == 1

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Patch verification over two declarations that share one ``(path, symbol)``.

The verifier compares per-symbol metric values keyed by ``(path, glued
qualname)``.  Two declarations under one key -- two ``def _calc``, two
``class C`` -- gave that index two candidates, and both roads picked one:
the store road by ``frozenset`` order (seed-dependent: 1 under seeds 0, 1,
3, 5 and 4 under 2, 4, 6, 7 on ``cxdup``), the record road by document order
(last wins).  A growth of 4 -> 8 on the hidden one was "nothing worsened".

The guard counts the elements per key BEFORE anything is mapped: a key with
two or more on a side has no value at all, and a key ambiguous on a side
present on both sides is an ``unresolved`` record instead of a comparison.
Only that key: a unique function beside it is compared as before.  An
unresolved key inside the patch's mandatory checks (its path changed, or
inside the intent's scope) makes the verdict ``unverified`` with reason
``ambiguous_declaration_identity`` -- never ``accepted`` -- and a proven
violation stays ``violated`` whatever is unresolved.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeclone.api.run_store_serving import read_run_store_patch_run
from codeclone.surfaces.mcp._patch_contract_runs import (
    PatchSession,
    RecordPatchRun,
    StorePatchRun,
    compare_metric_items,
    metric_item_index,
    population_maximum,
)
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests._patch_ambiguity_child import (
    BESIDE_AFTER,
    BESIDE_BEFORE,
    CLASS_BESIDE_AFTER,
    CLASS_COUPLING_AFTER,
    CLASS_COUPLING_BEFORE,
    CLASSES_AFTER,
    CLASSES_BEFORE,
    CLASSES_CONTROL_AFTER,
    CLASSES_CONTROL_BEFORE,
    CXDUP_AFTER,
    CXDUP_BEFORE,
    CXDUP_CONTROL_AFTER,
    CXDUP_CONTROL_BEFORE,
    GONE_AFTER,
    GONE_BEFORE,
    GROWN_PAIR_AFTER,
    GROWN_PAIR_BEFORE,
    MIXED_AFTER,
    MIXED_BEFORE,
    OTHER_MODULE,
    PROBE_LIVE_STORE,
    SAME_VECTOR_AFTER,
    SAME_VECTOR_BEFORE,
    SEED_SCENARIOS,
    SHIFTED_AFTER,
    committed_tree,
    git,
    verify_fields,
    write_tree,
)
from tests._patch_contract_serving import _twin
from tests._run_store_paths import run_store_service_path
from tests._run_summary_serving import serving_environment

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SEEDS: tuple[str, ...] = tuple(str(seed) for seed in range(8))
_AMBIGUOUS = "ambiguous_declaration_identity"
_CALC = ("app/mod.py", "app.mod:_calc")


def _keys(items: object) -> list[tuple[str, str, str]]:
    assert isinstance(items, list), items
    return [(item["family"], item["path"], item["symbol"]) for item in items]


# -- the children: one scenario, eight seeds ---------------------------------


def _child(work: Path, home: Path, seed: str, *extra: str) -> subprocess.Popen[str]:
    """One child under one seed, every place it may write inside ``work``."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CODECLONE_")
    }
    environment.update(
        PYTHONHASHSEED=seed,
        PYTHONDONTWRITEBYTECODE="1",
        HOME=str(home),
        XDG_CACHE_HOME=str(home / ".cache"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CONFIG_HOME=str(home / ".config"),
        # The analysed trees live under ``work``, and the product admits a
        # root under the system temporary directory only beneath TMPDIR.
        TMPDIR=str(work),
    )
    return subprocess.Popen(
        (
            sys.executable,
            "-m",
            "tests._patch_ambiguity_child",
            str(work),
            str(work / "answers.json"),
            *extra,
        ),
        cwd=_REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_the_child_refuses_live_state(tmp_path: Path) -> None:
    """The positive control of the children's fence, on its own path: a
    child asked to open a database under the hosting checkout's live
    ``.codeclone/`` is refused by the guard, not by SQLite."""
    work = tmp_path.resolve() / "probe"
    home = work / "home"
    home.mkdir(parents=True)
    child = _child(work, home, "0", PROBE_LIVE_STORE)
    _stdout, stderr = child.communicate(timeout=300)
    assert child.returncode != 0
    assert "LiveStateViolation" in stderr, stderr[-3000:]
    assert "reaches live CodeClone state" in stderr


@pytest.fixture(scope="module")
def seed_answers(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Each seed's answers, as the bytes its child wrote."""
    base = tmp_path_factory.mktemp("ambiguity_seeds").resolve()
    children: dict[str, tuple[Path, subprocess.Popen[str]]] = {}
    for seed in _SEEDS:
        work = base / f"seed{seed}"
        home = work / "home"
        home.mkdir(parents=True)
        children[seed] = (work, _child(work, home, seed))
    answers: dict[str, str] = {}
    for seed, (work, child) in children.items():
        _stdout, stderr = child.communicate(timeout=900)
        assert child.returncode == 0, (seed, stderr[-6000:])
        answers[seed] = (work / "answers.json").read_text("utf-8")
    return answers


def _decoded(seed_answers: Mapping[str, str], seed: str) -> dict[str, Any]:
    decoded = json.loads(seed_answers[seed])
    assert isinstance(decoded, dict)
    return decoded


def test_every_seed_answers_the_same_bytes(seed_answers: dict[str, str]) -> None:
    """Budget, verify on both roads and both finishes, byte for byte, under
    every seed -- the axis only a fresh interpreter reaches."""
    assert sorted(seed_answers) == sorted(_SEEDS)
    assert len(set(seed_answers.values())) == 1, {
        seed: answer[:400] for seed, answer in seed_answers.items()
    }


def test_the_seed_population_can_move(seed_answers: dict[str, str]) -> None:
    """Probe validity: the populations the children compare hold several
    elements in every family -- the store road's input is a ``frozenset``
    whose layout a seed can change only where there is more than one."""
    population = _decoded(seed_answers, "0")["mixed"]["roads:before"]["population"]
    assert {family: len(items) >= 3 for family, items in population.items()} == {
        "complexity": True,
        "coupling": True,
        "cohesion": True,
    }


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("scenario", sorted(SEED_SCENARIOS))
def test_the_store_answer_is_the_memory_answer(
    seed_answers: dict[str, str], seed: str, scenario: str
) -> None:
    """Under ``run_store`` every answer is served from the store, which the
    surface does only when the store's answer is the memory's byte for byte
    (``served_patch_contract``); and the served fields are the memory's."""
    answers = _decoded(seed_answers, seed)[scenario]
    for question in ("budget", "verify"):
        stored = answers[f"{question}:run_store"]
        memory = answers[f"{question}:memory"]
        assert stored["serving"] == {"source": "run_store", "reason": "served"}, (
            question,
            stored["serving"],
        )
        assert memory["serving"]["source"] == "memory"
        assert {k: v for k, v in stored.items() if k != "serving"} == {
            k: v for k, v in memory.items() if k != "serving"
        }


@pytest.mark.parametrize("seed", _SEEDS)
def test_the_duplicate_has_no_value_and_is_unresolved(
    seed_answers: dict[str, str], seed: str
) -> None:
    """``cxdup`` -> ``cxdup_after`` (4 -> 8 on the second ``_calc``): the key
    is unresolved on both sides, never worsened, never given a value, and
    the patch that edits it is not accepted."""
    verify = _decoded(seed_answers, seed)["cxdup"]["verify:memory"]["fields"]
    assert verify["status"] == "unverified", verify
    assert verify["reason"] == _AMBIGUOUS
    assert verify["worsened"] == []
    assert verify["unresolved"] == [
        {
            "family": "complexity",
            "path": _CALC[0],
            "symbol": _CALC[1],
            "reason": _AMBIGUOUS,
            "before_count": 2,
            "after_count": 2,
            "population": "differs",
        }
    ]
    assert verify["intent_unresolved"] == verify["unresolved"]
    assert verify["external_unresolved"] == []
    assert verify["checks_not_performed"] == ["worsened_symbols"]


@pytest.mark.parametrize("seed", _SEEDS)
def test_an_edit_beside_the_duplicates_is_verified_under_every_seed(
    seed_answers: dict[str, str], seed: str
) -> None:
    """``beside``: the store road's spans are the document's, so the
    narrowed answer -- accepted, ``_calc`` holding no measured change -- is
    served from the store under every seed."""
    verify = _decoded(seed_answers, seed)["beside"]["verify:run_store"]
    assert verify["serving"] == {"source": "run_store", "reason": "served"}
    fields = verify["fields"]
    assert (fields["status"], fields["reason"]) == ("accepted", None), fields
    assert [item["population"] for item in fields["unresolved"]] == [
        "no_measured_change"
    ]
    assert _keys(fields["worsened"]) == [("complexity", "app/mod.py", "app.mod:grow")]


@pytest.mark.parametrize("seed", _SEEDS)
@pytest.mark.parametrize("scenario", sorted(SEED_SCENARIOS))
def test_the_population_maximum_is_four_on_both_roads(
    seed_answers: dict[str, str], seed: str, scenario: str
) -> None:
    """Both ``_calc`` exist; the larger is 4.  The maximum is the population's,
    so it is defined however the key resolves: read on each road directly
    (the served answer falls back to memory whenever the roads differ), and
    served the same under either switch."""
    answers = _decoded(seed_answers, seed)[scenario]
    roads = answers["roads:before"]
    assert roads["store"]["complexity_max"] == 4, roads
    assert roads["record"]["complexity_max"] == 4, roads
    assert answers["roads:after"]["store"] == answers["roads:after"]["record"]
    for serve_from in ("run_store", "memory"):
        state = answers[f"budget:{serve_from}"]["current_state"]
        assert state == roads["store"], (serve_from, state)


@pytest.mark.parametrize("seed", _SEEDS)
def test_the_unresolved_order_is_the_sorted_order(
    seed_answers: dict[str, str], seed: str
) -> None:
    """``mixed``: five ambiguous keys over two modules; the records come in
    (family, path, symbol) order whatever the seed laid the sets out as, and
    the module nobody edits stays outside the intent."""
    verify = _decoded(seed_answers, seed)["mixed"]["verify:memory"]["fields"]
    keys = _keys(verify["unresolved"])
    assert keys == sorted(keys)
    assert keys == [
        ("complexity", "app/mod.py", "app.mod:_calc"),
        *(
            ("complexity", "app/other.py", f"app.other:{name}")
            for name in ("_a", "_b", "_c", "_d")
        ),
    ]
    assert _keys(verify["intent_unresolved"]) == keys[:1]
    assert _keys(verify["external_unresolved"]) == keys[1:]
    assert _keys(verify["worsened"]) == [("complexity", "app/mod.py", "app.mod:grow")]


@pytest.mark.parametrize("seed", _SEEDS)
def test_finish_cannot_close_an_ambiguous_change(
    seed_answers: dict[str, str], seed: str
) -> None:
    """The agent cannot close it: the user acts, the intent stays, no receipt
    and no claim validation call it verified, and finishing again with the
    same evidence answers the same."""
    answers = _decoded(seed_answers, seed)["cxdup"]
    first, again = answers["finish"], answers["finish_again"]
    assert first["status"] == "unverified", first
    assert first["reason"] == _AMBIGUOUS
    assert first["user_action_required"] is True
    assert first["intent_cleared"] is False
    assert first["receipt"] is None
    assert first["claims"] is None
    assert again == first


# -- in-process cycles --------------------------------------------------------


@contextmanager
def _environment(root: Path, *, store: bool) -> Iterator[None]:
    """The run store on and served from (``store``), or off entirely."""
    if store:
        with serving_environment(run_store_service_path(root), serve_from="run_store"):
            yield
        return
    patch = pytest.MonkeyPatch()
    try:
        for key in (
            "CODECLONE_RUN_STORE_ENABLED",
            "CODECLONE_RUN_STORE_FORCE",
            "CODECLONE_RUN_STORE_PATH",
            "CODECLONE_SERVE_FROM",
        ):
            patch.delenv(key, raising=False)
        yield
    finally:
        patch.undo()


def _cycle(
    base: Path,
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    scope: list[str],
    changed: list[str],
    store: bool = True,
    finish: bool = False,
    audit: list[dict[str, object]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Analyse, start, edit, analyse, verify (and finish): the answers;
    with ``audit``, every audit event the session emits is kept there."""
    root = committed_tree(base, {"app/__init__.py": "", **before})
    service = CodeCloneMCPService(history_limit=4)
    if audit is not None:
        real_emit = service._audit_emit

        def recording_emit(**event: Any) -> int | None:
            audit.append(dict(event))
            return real_emit(**event)

        service._audit_emit = recording_emit  # type: ignore[method-assign]
    with _environment(root, store=store):
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))
        started = service.start_controlled_change(
            root=str(root), scope={"allowed_files": scope}, intent="ambiguity cycle"
        )
        assert started.get("edit_allowed") is True, started
        intent_id = str(started["intent_id"])
        write_tree(root, after)
        after_run = str(
            service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
        )
        answers: dict[str, dict[str, Any]] = {
            "verify": service.check_patch_contract(
                mode="verify",
                intent_id=intent_id,
                after_run_id=after_run,
                changed_files=changed,
                root=str(root),
            )
        }
        if finish:
            answers["finish"] = service.finish_controlled_change(
                intent_id=intent_id, after_run_id=after_run, changed_files=changed
            )
    return answers


def test_unique_control_reports_the_growth(tmp_path: Path) -> None:
    """The same 4 -> 8 on a unique ``_calc``: compared, worsened, accepted --
    the guard does not reach a key that names one declaration."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": CXDUP_CONTROL_BEFORE},
        {"app/mod.py": CXDUP_CONTROL_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert verify["status"] == "accepted", verify
    assert verify["worsened"] == [
        {
            "family": "complexity",
            "path": _CALC[0],
            "symbol": _CALC[1],
            "before": 4,
            "after": 8,
            "delta": 4,
        }
    ]
    assert verify["unresolved"] == []


def test_unique_function_beside_the_duplicate_stays_worsened(tmp_path: Path) -> None:
    """The unavailability is the key's, not the file's: ``grow`` (2 -> 5) in
    the same module is still compared and still worsened."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": MIXED_BEFORE},
        {"app/mod.py": MIXED_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert verify["worsened"] == [
        {
            "family": "complexity",
            "path": "app/mod.py",
            "symbol": "app.mod:grow",
            "before": 2,
            "after": 5,
            "delta": 3,
        }
    ]
    assert _keys(verify["unresolved"]) == [("complexity", *_CALC)]


def test_duplicate_classes_are_unresolved_for_coupling_and_cohesion(
    tmp_path: Path,
) -> None:
    """Two ``class C``: the first couples to both and splits (1 -> 2 on both
    families).  The record road showed the last ``C`` (1 -> 1); now the key
    is unresolved on each family it is measured in and worsened nowhere."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": CLASSES_BEFORE},
        {"app/mod.py": CLASSES_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert verify["status"] == "unverified", verify
    assert verify["reason"] == _AMBIGUOUS
    assert _keys(verify["unresolved"]) == [
        ("cohesion", "app/mod.py", "app.mod:C"),
        ("coupling", "app/mod.py", "app.mod:C"),
    ]
    assert not [item for item in verify["worsened"] if item["symbol"] == "app.mod:C"]


def test_unique_classes_are_compared_as_before(tmp_path: Path) -> None:
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": CLASSES_CONTROL_BEFORE},
        {"app/mod.py": CLASSES_CONTROL_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert verify["unresolved"] == []
    assert sorted(_keys(verify["worsened"])) == [
        ("cohesion", "app/mod.py", "app.mod:C1"),
        ("coupling", "app/mod.py", "app.mod:C1"),
    ]


# -- the acceptance table -----------------------------------------------------

_UNIQUE_BEFORE = "def helper(value):\n    return value\n"
#: A new function: a structural change (a new run id) that worsens nothing.
_UNIQUE_AFTER = _UNIQUE_BEFORE + "\n\ndef added(value):\n    return value * 2\n"


def test_table_unambiguous_and_passed_is_accepted(tmp_path: Path) -> None:
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": _UNIQUE_BEFORE},
        {"app/mod.py": _UNIQUE_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("accepted", None), verify
    assert verify["unresolved"] == []
    assert "checks_not_performed" not in verify
    assert "limitations" not in verify


def test_table_ambiguity_outside_the_patch_is_accepted(tmp_path: Path) -> None:
    """Duplicates in a module the intent neither declares nor changes: the
    patch's checks never read them.  Accepted; the keys stay visible."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": _UNIQUE_BEFORE, "app/other.py": OTHER_MODULE},
        {"app/mod.py": _UNIQUE_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("accepted", None), verify
    assert verify["intent_unresolved"] == []
    assert [symbol for _f, _p, symbol in _keys(verify["external_unresolved"])] == [
        f"app.other:{name}" for name in ("_a", "_b", "_c", "_d")
    ]
    assert verify["external_unresolved"] == verify["unresolved"]


def test_table_ambiguity_inside_the_patch_is_unverified(tmp_path: Path) -> None:
    """``cxdup`` -> ``cxdup_after`` with ``_calc`` in the intent's scope; the
    verification event it writes warns, as an unverified verdict does."""
    audit: list[dict[str, object]] = []
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": CXDUP_BEFORE},
        {"app/mod.py": CXDUP_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
        audit=audit,
    )["verify"]
    verified = [event for event in audit if event.get("status") == "unverified"]
    assert [event["severity"] for event in verified] == ["warn"], audit
    assert (verify["status"], verify["reason"]) == ("unverified", _AMBIGUOUS), verify
    assert verify["checks_not_performed"] == ["worsened_symbols"]
    limitations = verify["limitations"]
    assert isinstance(limitations, list) and limitations
    assert any("app.mod:_calc" in str(line) for line in limitations), limitations
    assert "manage_change_intent" in str(verify["next_step"])


def test_table_a_proven_violation_stays_violated(tmp_path: Path) -> None:
    """The duplicate is in scope AND the patch adds a clone pair there: the
    regression is proven, so the verdict is ``violated``, not hidden behind
    the ambiguity."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": CXDUP_BEFORE},
        {
            "app/mod.py": CXDUP_AFTER
            + "\n\n"
            + _twin("twin_a")
            + "\n\n"
            + _twin("twin_b")
        },
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert verify["status"] == "violated", verify
    assert "structural_regressions" in verify["contract_violations"]
    assert _keys(verify["intent_unresolved"]) == [("complexity", *_CALC)]


def test_an_unchanged_duplicate_in_the_declared_scope_binds_nothing(
    tmp_path: Path,
) -> None:
    """The intent declares the module of duplicates and changes another: the
    duplicates hold the same measured metrics at the same positions, so they
    bind nothing -- reported in ``intent_unresolved``, accepted.  (The first
    cycle blocked the whole declared file here; ruling 2026-10-19 (9).)"""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": _UNIQUE_BEFORE, "app/other.py": OTHER_MODULE},
        {"app/mod.py": _UNIQUE_AFTER},
        scope=["app/mod.py", "app/other.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("accepted", None), verify
    assert len(_keys(verify["intent_unresolved"])) == 4
    assert {item["population"] for item in verify["intent_unresolved"]} == {
        "no_measured_change"
    }
    assert verify["external_unresolved"] == []


def test_which_unresolved_keys_bind_the_patch() -> None:
    """A key binds the patch when its population differs AND the patch's
    checks read it: in a changed file, inside the intent's scope, or
    without a path (which cannot be shown outside the patch).  A key whose
    population shows no measured change binds nothing, wherever it is."""
    service = CodeCloneMCPService(history_limit=4)
    differs = {"family": "complexity", "path": "app/mod.py", "symbol": "app.mod:_calc"}
    keys = {
        "changed:differs": {**differs, "population": "differs"},
        "changed:unchanged": {**differs, "population": "no_measured_change"},
        "pathless:differs": {**differs, "path": "", "population": "differs"},
        "pathless:unchanged": {
            **differs,
            "path": "",
            "population": "no_measured_change",
        },
        "elsewhere:differs": {
            **differs,
            "path": "app/other.py",
            "population": "differs",
        },
    }
    mandatory = service._mandatory_unresolved(
        unresolved=list(keys.values()), intent=None, changed_files=["app/mod.py"]
    )
    assert [name for name, item in keys.items() if item in mandatory] == [
        "changed:differs",
        "pathless:differs",
    ]


def test_a_differing_key_inside_the_declared_scope_binds_beside_the_changed_files() -> (
    None
):
    """The intent's scope is the patch's too: a key whose population differs
    in a declared module binds even when the changed-file evidence does not
    name that module (``changed_files`` stated narrower than the scope).  A
    key there whose population shows no measured change still binds
    nothing; one outside both binds nothing either."""
    service = CodeCloneMCPService(history_limit=4)
    key = {"family": "complexity", "symbol": "app.other:_calc"}
    keys = {
        "scope:differs": {**key, "path": "app/other.py", "population": "differs"},
        "scope:unchanged": {
            **key,
            "path": "app/other.py",
            "population": "no_measured_change",
        },
        "outside:differs": {**key, "path": "app/third.py", "population": "differs"},
    }
    intent = SimpleNamespace(
        scope=SimpleNamespace(allowed_files=("app/other.py",), allowed_related=())
    )
    mandatory = service._mandatory_unresolved(
        unresolved=list(keys.values()),
        intent=cast(Any, intent),
        changed_files=["app/mod.py"],
    )
    assert [name for name, item in keys.items() if item in mandatory] == [
        "scope:differs"
    ]


def test_the_reason_joins_the_typed_outcome_vocabulary() -> None:
    """A typed outcome arrives with its remedy and its help mention -- and
    the remedy names a call, not a diagnosis."""
    from codeclone.surfaces.mcp.messages import patch_contract as patch_msgs
    from codeclone.surfaces.mcp.messages.help_topics import HELP_TOPIC_SPECS

    assert _AMBIGUOUS == patch_msgs.AMBIGUOUS_DECLARATION_IDENTITY_REASON
    assert _AMBIGUOUS in patch_msgs.FINISH_OUTCOME_REASONS
    assert _AMBIGUOUS not in patch_msgs.ACCEPTED_OUTCOME_REASONS
    step = patch_msgs.next_step_hint(_AMBIGUOUS)
    assert step is not None and "manage_change_intent(" in step
    assert _AMBIGUOUS in str(HELP_TOPIC_SPECS["verification_profiles"])


def test_without_an_intent_the_changed_duplicate_blocks(tmp_path: Path) -> None:
    """Without an intent the changed files are the patch: the duplicate in
    the changed module blocks, the four in the module nobody changed do not.
    ``relaxed``: without an intent every failing gate is the patch's, and
    this tree has no baseline, so its clone lanes fail the gate on both
    runs; the profile that does not block on gates leaves the verdict to the
    comparison alone."""
    root = committed_tree(
        tmp_path / "tree",
        {
            "app/__init__.py": "",
            "app/mod.py": CXDUP_BEFORE,
            "app/other.py": OTHER_MODULE,
        },
    )
    service = CodeCloneMCPService(history_limit=4)
    with _environment(root, store=True):
        before = str(
            service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
        )
        write_tree(root, {"app/mod.py": CXDUP_AFTER})
        after = str(
            service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
        )
        verify = service.check_patch_contract(
            mode="verify",
            before_run_id=before,
            after_run_id=after,
            changed_files=["app/mod.py"],
            root=str(root),
            strictness="relaxed",
        )
    assert (verify["status"], verify["reason"]) == ("unverified", _AMBIGUOUS), verify
    assert len(_keys(verify["unresolved"])) == 5


def test_an_unchanged_duplicate_without_an_intent_does_not_block(
    tmp_path: Path,
) -> None:
    root = committed_tree(
        tmp_path / "tree",
        {
            "app/__init__.py": "",
            "app/mod.py": _UNIQUE_BEFORE,
            "app/other.py": OTHER_MODULE,
        },
    )
    service = CodeCloneMCPService(history_limit=4)
    with _environment(root, store=True):
        before = str(
            service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
        )
        write_tree(root, {"app/mod.py": _UNIQUE_AFTER})
        after = str(
            service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
        )
        verify = service.check_patch_contract(
            mode="verify",
            before_run_id=before,
            after_run_id=after,
            changed_files=["app/mod.py"],
            root=str(root),
            strictness="relaxed",
        )
    assert (verify["status"], verify["reason"]) == ("accepted", None), verify
    assert len(_keys(verify["unresolved"])) == 4


# -- positional narrowing: Availability and Soundness -------------------------


def _populations(verify: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    return [
        (item["family"], item["path"], item["symbol"], item["population"])
        for item in verify["unresolved"]
    ]


def test_an_edit_below_the_duplicates_is_verified_as_usual(tmp_path: Path) -> None:
    """Availability: ``grow`` (2 -> 5) BELOW the two ``_calc`` moves none of
    their lines, so their measured positions and metrics are the same on
    both sides -- the key binds nothing, the change is compared as usual
    (accepted, ``grow`` worsened) and ``_calc`` stays in the report."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": BESIDE_BEFORE},
        {"app/mod.py": BESIDE_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("accepted", None), verify
    assert _keys(verify["worsened"]) == [("complexity", "app/mod.py", "app.mod:grow")]
    assert _populations(verify) == [("complexity", *_CALC, "no_measured_change")]
    assert verify["intent_unresolved"] == verify["unresolved"]
    assert "checks_not_performed" not in verify


def test_a_proven_regression_beside_unchanged_duplicates_is_violated(
    tmp_path: Path,
) -> None:
    """``no_measured_change`` is read by no other check: a clone pair added
    below the untouched duplicates is a structural regression of the patch,
    and the verdict is ``violated``."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": BESIDE_BEFORE},
        {
            "app/mod.py": BESIDE_AFTER
            + "\n\n"
            + _twin("twin_a")
            + "\n\n"
            + _twin("twin_b")
        },
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert verify["status"] == "violated", verify
    assert "structural_regressions" in verify["contract_violations"]
    assert _populations(verify) == [("complexity", *_CALC, "no_measured_change")]


def test_a_line_shift_above_the_duplicates_is_unverified(tmp_path: Path) -> None:
    """One line added ABOVE the duplicates: same values, other positions --
    ``differs`` by design, so the patch that moved them is ``unverified``."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": BESIDE_BEFORE},
        {"app/mod.py": SHIFTED_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("unverified", _AMBIGUOUS), verify
    assert _populations(verify) == [("complexity", *_CALC, "differs")]
    assert verify["worsened"] == []


def test_a_duplicate_class_whose_coupling_grew_is_unverified(tmp_path: Path) -> None:
    """Two ``class C`` whose methods share their names: the first ``C.run``
    couples to ``Y`` too, on the same line.  No line moves and no method's
    complexity changes, so every method key holds no measured change -- but
    the class key's full vector (coupling WITH cohesion) differs, so the
    patch is not verified."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": CLASS_COUPLING_BEFORE},
        {"app/mod.py": CLASS_COUPLING_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("unverified", _AMBIGUOUS), verify
    assert _populations(verify) == [
        ("cohesion", "app/mod.py", "app.mod:C", "differs"),
        ("complexity", "app/mod.py", "app.mod:C.run", "no_measured_change"),
        ("coupling", "app/mod.py", "app.mod:C", "differs"),
    ]
    assert verify["worsened"] == []


def test_untouched_duplicate_classes_beside_an_edit_bind_nothing(
    tmp_path: Path,
) -> None:
    """The class control: the two ``class C`` untouched, ``grow`` below them
    grows -- every duplicated key holds no measured change and ``grow`` is
    compared."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": CLASS_COUPLING_BEFORE},
        {"app/mod.py": CLASS_BESIDE_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("accepted", None), verify
    assert {population for *_key, population in _populations(verify)} == {
        "no_measured_change"
    }
    assert len(_populations(verify)) == 3
    assert _keys(verify["worsened"]) == [("complexity", "app/mod.py", "app.mod:grow")]


def test_two_declarations_of_one_vector_against_one_differ(tmp_path: Path) -> None:
    """Multiset, not set: two ``_calc`` of complexity 1 become one ``_calc``
    of complexity 1 at the first one's place -- the same set of vectors,
    a different population.  The key is unresolved and binds the patch; no
    surviving declaration is chosen."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": SAME_VECTOR_BEFORE},
        {"app/mod.py": SAME_VECTOR_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("unverified", _AMBIGUOUS), verify
    assert [
        (item["before_count"], item["after_count"], item["population"])
        for item in verify["unresolved"]
    ] == [(2, 1, "differs")]
    assert verify["unpaired"] == []


def test_one_declaration_becoming_two_is_unresolved_not_matched(
    tmp_path: Path,
) -> None:
    """``1 -> 2``: the first ``_calc`` stays exactly where and what it was and
    a second one is added.  The count change is stated (1 before, 2 after);
    the unchanged one is never taken for "the" ``_calc``."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": GROWN_PAIR_BEFORE},
        {"app/mod.py": GROWN_PAIR_AFTER},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert (verify["status"], verify["reason"]) == ("unverified", _AMBIGUOUS), verify
    assert [
        (item["before_count"], item["after_count"], item["population"])
        for item in verify["unresolved"]
    ] == [(1, 2, "differs")]
    assert verify["worsened"] == []


@pytest.mark.parametrize(
    ("before", "after", "direction", "counts"),
    [
        pytest.param(GONE_BEFORE, GONE_AFTER, "removed", (2, 0), id="two-to-zero"),
        pytest.param(GONE_AFTER, GONE_BEFORE, "added", (0, 2), id="zero-to-two"),
    ],
)
def test_one_sided_duplicates_are_unpaired_with_direction_and_counts(
    tmp_path: Path,
    before: str,
    after: str,
    direction: str,
    counts: tuple[int, int],
) -> None:
    """Declarations under one key on one side only: nothing to compare, but
    the structural fact is kept -- direction and both counts -- and it does
    not block."""
    verify = _cycle(
        tmp_path / "tree",
        {"app/mod.py": before},
        {"app/mod.py": after},
        scope=["app/mod.py"],
        changed=["app/mod.py"],
    )["verify"]
    assert verify["unpaired"] == [
        {
            "family": "complexity",
            "path": _CALC[0],
            "symbol": _CALC[1],
            "direction": direction,
            "before_count": counts[0],
            "after_count": counts[1],
            "comparison": "no_comparable_pair",
        }
    ]
    assert verify["unresolved"] == []
    assert (verify["status"], verify["reason"]) == ("accepted", None), verify


_SCOPE_ID = "11111111-1111-4111-8111-111111111111"
_API_PYPROJECT = (
    '[project]\nname = "probe"\nversion = "0"\n\n[tool.codeclone]\n'
    f'baseline_scope_id = "{_SCOPE_ID}"\napi_surface = true\n'
)
#: A public ``handle`` declared twice beside a public ``keep``; the patch
#: removes both ``handle``.
_API_BEFORE = (
    "def handle(value):\n    return value\n\n\n"
    "def handle(value):\n    return value + 1\n\n\n"
    "def keep(value):\n    return value\n"
)
_API_AFTER = "def keep(value):\n    return value\n"


def test_removing_a_duplicated_public_symbol_is_an_api_break(tmp_path: Path) -> None:
    """``unpaired`` says two ``handle`` were removed and claims nothing about
    the API: the existing API comparison, against the baseline's API
    surface, reports the removal as a breaking change of ``handle``."""
    from tests.conftest import _run_codeclone_cli

    root = committed_tree(
        tmp_path / "tree",
        {
            "app/__init__.py": "",
            "app/mod.py": _API_BEFORE,
            "pyproject.toml": _API_PYPROJECT,
        },
    )
    _run_codeclone_cli(
        [str(root), "--no-progress", "--api-surface", "--update-baseline"], {}
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "baseline")
    service = CodeCloneMCPService(history_limit=4)
    with _environment(root, store=True):
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))
        started = service.start_controlled_change(
            root=str(root), scope={"allowed_files": ["app/mod.py"]}, intent="api"
        )
        write_tree(root, {"app/mod.py": _API_AFTER})
        after = service.analyze_repository(MCPAnalysisRequest(root=str(root)))
        verify: dict[str, Any] = service.check_patch_contract(
            mode="verify",
            intent_id=str(started["intent_id"]),
            after_run_id=str(after["run_id"]),
            changed_files=["app/mod.py"],
            root=str(root),
        )
        record = service._runs.get_for_root(str(after["run_id"]), root=root)
    diff = cast("dict[str, Any]", after["diff"])
    assert [
        (item["symbol"], item["direction"], item["before_count"], item["after_count"])
        for item in verify["unpaired"]
    ] == [("app.mod:handle", "removed", 2, 0)]
    assert diff["api_breaking_changes"] == 1, diff
    report = cast("dict[str, Any]", record.served_report)
    api_items = report["metrics"]["families"]["api_surface"]["items"]
    assert [
        (item["qualname"], item["change_kind"])
        for item in api_items
        if item.get("record_kind") == "breaking_change"
    ] == [("app.mod:handle", "removed")]


# -- with the store and without it ---------------------------------------------


def test_verify_and_finish_agree_with_and_without_the_store(tmp_path: Path) -> None:
    """The same controlled change, the run store on and served from, then off
    entirely: the same worsened, unresolved and limitations, in verify and in
    the verification finish embeds."""
    answers = {
        store: _cycle(
            tmp_path / f"tree_{store}",
            {"app/mod.py": MIXED_BEFORE, "app/other.py": OTHER_MODULE},
            {"app/mod.py": MIXED_AFTER},
            scope=["app/mod.py"],
            changed=["app/mod.py"],
            store=store,
            finish=True,
        )
        for store in (True, False)
    }
    stored, memory = answers[True], answers[False]
    assert verify_fields(stored["verify"]) == verify_fields(memory["verify"])
    assert stored["verify"]["serving"]["source"] == "run_store"
    finished = {
        store: verify_fields(answer["finish"]["verification"])
        for store, answer in answers.items()
    }
    assert finished[True] == finished[False]
    assert finished[True]["unresolved"]
    assert finished[True]["limitations"]
    assert stored["finish"]["user_action_required"] is True


# -- the one builder and the decision table ------------------------------------

_KEY = ("pkg/m.py", "pkg.m:f")


def test_the_index_counts_before_it_maps() -> None:
    """Two elements under one key: counted, never mapped; a key with one
    element resolves; the maximum is the whole population's -- whatever
    order the elements arrive in."""
    population = (
        (_KEY, (1, 2), 1),
        (("pkg/m.py", "pkg.m:g"), (4, 5), 2),
        (_KEY, (7, 9), 4),
    )
    for order in (population, tuple(reversed(population))):
        resolved, counts = metric_item_index(order)
        assert resolved == {("pkg/m.py", "pkg.m:g"): 2}
        assert counts == {_KEY: 2, ("pkg/m.py", "pkg.m:g"): 1}
        assert population_maximum(order) == 4


def test_a_keyless_element_counts_toward_the_maximum_only() -> None:
    population = ((("", ""), None, 9), (("", ""), None, 3), (_KEY, (1, 2), 1))
    assert metric_item_index(population) == ({_KEY: 1}, {_KEY: 1})
    assert population_maximum(population) == 9


#: Each side's state of one key: absent (no element), resolved (one) or
#: ambiguous (two), as the population that produces it.
_SIDES: dict[str, tuple[tuple[tuple[str, str], tuple[int, int] | None, int], ...]] = {
    "absent": (),
    "resolved": ((_KEY, (1, 2), 3),),
    "ambiguous": ((_KEY, (1, 2), 1), (_KEY, (5, 6), 3)),
}
#: The decision table of ``compare_metric_items``, every pair of states.
#: The after side grows the value (3 -> 5), so a compared key is worsened.
_TABLE: dict[tuple[str, str], str] = {
    ("resolved", "resolved"): "worsened",
    ("resolved", "ambiguous"): "unresolved",
    ("ambiguous", "resolved"): "unresolved",
    ("ambiguous", "ambiguous"): "unresolved",
    ("absent", "resolved"): "not compared",
    ("absent", "ambiguous"): "unpaired:added",
    ("resolved", "absent"): "not compared",
    ("ambiguous", "absent"): "unpaired:removed",
    ("absent", "absent"): "not compared",
}


def _outcome(
    worsened: list[dict[str, object]],
    unresolved: list[dict[str, object]],
    unpaired: list[dict[str, object]],
) -> str:
    if unpaired:
        return f"unpaired:{unpaired[0]['direction']}"
    return "worsened" if worsened else "unresolved" if unresolved else "not compared"


@pytest.mark.parametrize(("before", "after"), sorted(_TABLE))
def test_the_decision_table(before: str, after: str) -> None:
    grown = tuple((key, span, value + 2) for key, span, value in _SIDES[after])
    worsened, unresolved, unpaired = compare_metric_items(
        "complexity",
        before=_SIDES[before],
        after=grown,
    )
    assert _outcome(worsened, unresolved, unpaired) == _TABLE[(before, after)]
    assert sum(map(bool, (worsened, unresolved, unpaired))) <= 1
    counts = {"before_count": len(_SIDES[before]), "after_count": len(_SIDES[after])}
    key = {"family": "complexity", "path": _KEY[0], "symbol": _KEY[1]}
    if unresolved:
        assert unresolved == [{**key, "reason": _AMBIGUOUS, **counts}]
    if unpaired:
        assert unpaired == [
            {
                **key,
                "direction": "removed" if before == "ambiguous" else "added",
                **counts,
                "comparison": "no_comparable_pair",
            }
        ]


# -- the narrowing table: (span, full vector) multisets ---------------------------

_CLASS = ("pkg/m.py", "pkg.m:C")


_Population = tuple[tuple[tuple[str, str], tuple[int, int] | None, int], ...]


def _family(
    *elements: tuple[tuple[int, int] | None, int], key: tuple[str, str] = _KEY
) -> _Population:
    return tuple((key, span, value) for span, value in elements)


def _population(**families: _Population) -> dict[str, _Population]:
    return {
        family: families.get(family, ())
        for family in ("complexity", "coupling", "cohesion")
    }


#: Each case: (before, after, the key it narrows, its population).
_NARROWING: dict[
    str,
    tuple[dict[str, _Population], dict[str, _Population], tuple[str, str], str],
] = {
    "same positions and values": (
        _population(complexity=_family(((1, 2), 1), ((5, 9), 4))),
        _population(complexity=_family(((5, 9), 4), ((1, 2), 1))),
        _KEY,
        "no_measured_change",
    ),
    "a value changed": (
        _population(complexity=_family(((1, 2), 1), ((5, 9), 4))),
        _population(complexity=_family(((1, 2), 1), ((5, 9), 8))),
        _KEY,
        "differs",
    ),
    "a position moved": (
        _population(complexity=_family(((1, 2), 1), ((5, 9), 4))),
        _population(complexity=_family(((2, 3), 1), ((6, 10), 4))),
        _KEY,
        "differs",
    ),
    "an end line moved": (
        _population(complexity=_family(((1, 2), 1), ((5, 9), 4))),
        _population(complexity=_family(((1, 2), 1), ((5, 10), 4))),
        _KEY,
        "differs",
    ),
    "two identical declarations against one": (
        _population(complexity=_family(((5, 9), 4), ((5, 9), 4))),
        _population(complexity=_family(((5, 9), 4))),
        _KEY,
        "differs",
    ),
    "two identical declarations on both sides": (
        _population(complexity=_family(((5, 9), 4), ((5, 9), 4))),
        _population(complexity=_family(((5, 9), 4), ((5, 9), 4))),
        _KEY,
        "differs",
    ),
    "positions unknown on both sides": (
        _population(complexity=_family((None, 1), (None, 4))),
        _population(complexity=_family((None, 1), (None, 4))),
        _KEY,
        "differs",
    ),
    "class: coupling and cohesion the same": (
        _population(
            coupling=_family(((3, 8), 1), ((10, 14), 2), key=_CLASS),
            cohesion=_family(((3, 8), 1), ((10, 14), 1), key=_CLASS),
        ),
        _population(
            coupling=_family(((10, 14), 2), ((3, 8), 1), key=_CLASS),
            cohesion=_family(((10, 14), 1), ((3, 8), 1), key=_CLASS),
        ),
        _CLASS,
        "no_measured_change",
    ),
    "class: coupling the same, cohesion changed": (
        _population(
            coupling=_family(((3, 8), 1), ((10, 14), 2), key=_CLASS),
            cohesion=_family(((3, 8), 1), ((10, 14), 1), key=_CLASS),
        ),
        _population(
            coupling=_family(((3, 8), 1), ((10, 14), 2), key=_CLASS),
            cohesion=_family(((3, 8), 2), ((10, 14), 1), key=_CLASS),
        ),
        _CLASS,
        "differs",
    ),
    "class: the values swapped between the two positions": (
        _population(
            coupling=_family(((3, 8), 1), ((10, 14), 2), key=_CLASS),
            cohesion=_family(((3, 8), 1), ((10, 14), 1), key=_CLASS),
        ),
        _population(
            coupling=_family(((3, 8), 2), ((10, 14), 1), key=_CLASS),
            cohesion=_family(((3, 8), 1), ((10, 14), 1), key=_CLASS),
        ),
        _CLASS,
        "differs",
    ),
}


@pytest.mark.parametrize("case", sorted(_NARROWING))
def test_the_narrowing_table(case: str) -> None:
    """``no_measured_change`` only when the key's ``(span, full vector)``
    multisets are equal: cardinality, both lines, every family it is
    measured in.  Anything else -- a value, a line, one more declaration,
    an unknown position, two elements at one position -- ``differs``."""
    import codeclone.surfaces.mcp._patch_contract_runs as patch_runs

    before, after, key, population = _NARROWING[case]
    families = [family for family in before if any(e[0] == key for e in before[family])]
    unresolved = [
        {"family": family, "path": key[0], "symbol": key[1]} for family in families
    ]
    narrowed = patch_runs.narrowed_unresolved(unresolved, before=before, after=after)
    assert [item["population"] for item in narrowed] == [population] * len(families)


def test_both_roads_build_one_index_for_one_run(tmp_path: Path) -> None:
    """The store road's stored rows and the record road's document hold one
    population per family, element for element, so the one builder gives
    them one index and one maximum -- on a run that holds a duplicated key,
    which is in both and resolves in neither."""
    root = committed_tree(
        tmp_path / "tree", {"app/__init__.py": "", "app/mod.py": MIXED_BEFORE}
    )
    service = CodeCloneMCPService(history_limit=4)
    with serving_environment(run_store_service_path(root), serve_from="run_store"):
        run_id = str(
            service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
        )
        record = service._runs.get_for_root(run_id, root=root)
        stored, outcome = read_run_store_patch_run(
            root=record.root, link=record.execution.run_snapshot_link
        )
    assert stored is not None, outcome
    session = cast("PatchSession", service)
    for family in ("complexity", "coupling", "cohesion"):
        store_road = StorePatchRun(session, record, stored).metric_population(family)
        record_road = RecordPatchRun(session, record).metric_population(family)
        assert sorted(store_road) == sorted(record_road), family
        assert metric_item_index(store_road) == metric_item_index(record_road)
    resolved, counts = metric_item_index(stored.metric_items["complexity"])
    assert counts[_CALC] == 2
    assert _CALC not in resolved

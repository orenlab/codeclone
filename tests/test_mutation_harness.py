# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Contract tests for the mutation protocol harness.

The harness exists because a hand-written mutation report is a claim.  Each test
below negates exactly one guarantee the harness makes, using a throwaway git
sandbox with a real ``pytest`` subprocess -- the same machinery a real battery
uses, sized down to two tests.

Every scenario here reproduces a failure mode measured on this repository, and
the assertion is always the same shape: the harness must refuse to say ``kill``.
"""

from __future__ import annotations

import functools
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from scripts.mutation_harness import PlanError, load_plan, main

_HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "mutation_harness.py"

_PYTEST_INI = "[pytest]\ntestpaths = .\n"
_GITIGNORE = "__pycache__/\n"

_SUBJECT = '''"""Sandbox production module."""


def answer() -> int:
    """Return the pinned answer."""
    return 41 + 1


def labels() -> list[str]:
    """Return the label set in a stable order."""
    return sorted({"alpha", "beta", "gamma"})
'''

_TEST_SUBJECT = """from subject import answer


def test_answer() -> None:
    assert answer() == 42
"""

_TEST_OTHER = """def test_unrelated() -> None:
    assert True
"""

_TEST_SLOW = """import time


def test_slow() -> None:
    time.sleep(30)
"""

_TEST_SIDE_EFFECT = """from pathlib import Path


def test_writes_a_sibling() -> None:
    Path(__file__).with_name("sibling.txt").write_text("polluted\\n")
"""

_TEST_LABELS = """from subject import labels


def test_first_label() -> None:
    assert labels()[0] == "alpha"
"""

_TEST_BROKEN = """def test_already_red() -> None:
    raise AssertionError("this home was red before anybody mutated anything")
"""

_TWIN = '''"""Two byte-identical sites; only the first one is pinned."""


def first() -> int:
    """Return the pinned sum."""
    return 1 + 1


def second() -> int:
    """Return the unpinned sum."""
    return 1 + 1
'''

_TEST_TWIN = """from twin import first


def test_first_site() -> None:
    assert first() == 2
"""

_TEST_OBSERVER = """import os
from pathlib import Path


def test_records_what_it_saw() -> None:
    log = Path(os.environ["MUTATION_HARNESS_SELFTEST_LOG"])
    here = Path(__file__).parent
    seen = {name: (here / name).read_text() for name in ("subject.py", "second.py")}
    with log.open("a") as handle:
        handle.write(repr(sorted(seen.items())) + "\\n")
"""

_SECOND = '''"""Second sandbox module, mutated by the battery's second mutant."""


def other() -> int:
    """Return the second pinned value."""
    return 7 + 0
'''

_ENV_LEAKS = (
    "PYTEST_ADDOPTS",
    "COV_CORE_SOURCE",
    "COV_CORE_CONFIG",
    "COV_CORE_DATAFILE",
    "COV_CORE_CONTEXT",
)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


class _Sandbox:
    """A throwaway git repository holding two tests and one production module."""

    def __init__(self, base: Path) -> None:
        self.root = base / "repo"
        self.control = base / "control"
        self.root.mkdir(parents=True)
        self.control.mkdir(parents=True)
        _git(self.root.parent, "init", "-q", "-b", "main", str(self.root))

    def add(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self) -> None:
        _git(self.root, "add", "-A")
        _git(
            self.root,
            "-c",
            "user.email=harness@example.invalid",
            "-c",
            "user.name=harness",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "sandbox",
        )

    def status(self) -> str:
        return _git(self.root, "status", "--short", "-uall")

    def plan(self, mutants: Sequence[Mapping[str, object]]) -> Path:
        path = self.control / "plan.json"
        path.write_text(json.dumps({"mutants": list(mutants)}), encoding="utf-8")
        return path


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Sandbox:
    for name in _ENV_LEAKS:
        monkeypatch.delenv(name, raising=False)
    box = _Sandbox(tmp_path)
    box.add("pytest.ini", _PYTEST_INI)
    box.add(".gitignore", _GITIGNORE)
    box.add("subject.py", _SUBJECT)
    box.add("test_subject.py", _TEST_SUBJECT)
    box.add("test_other.py", _TEST_OTHER)
    box.commit()
    return box


def _mutant(**overrides: object) -> dict[str, object]:
    """The reference mutant: ``answer()`` returns 43, which ``test_subject`` pins."""
    spec: dict[str, object] = {
        "id": "m1",
        "target": "subject.py",
        "find": "41 + 1",
        "replace": "41 + 2",
        "home": {"declared": "full"},
    }
    spec.update(overrides)
    return spec


def _drive(
    sandbox: _Sandbox, *mutants: Mapping[str, object]
) -> tuple[int, Mapping[str, object]]:
    plan = sandbox.plan(mutants)
    report_path = sandbox.control / "report.json"
    argv = [
        "--root",
        str(sandbox.root),
        "--plan",
        str(plan),
        "--report",
        str(report_path),
    ]
    saved = {n: signal.getsignal(n) for n in (signal.SIGINT, signal.SIGTERM)}
    try:
        code = main(argv)
    finally:
        for number, handler in saved.items():
            signal.signal(number, handler)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return code, payload


def _entry(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    assert isinstance(value, dict)
    return value


def _rows(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = payload[key]
    assert isinstance(value, list)
    return [row for row in value if isinstance(row, dict)]


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    assert isinstance(value, str)
    return value


def _flag(payload: Mapping[str, object], key: str) -> bool:
    value = payload[key]
    assert isinstance(value, bool)
    return value


def _strings(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload[key]
    assert isinstance(value, list)
    return [item for item in value if isinstance(item, str)]


def _number(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    assert isinstance(value, int)
    return value


def _only(report: Mapping[str, object]) -> Mapping[str, object]:
    mutants = _rows(report, "mutants")
    assert len(mutants) == 1
    return mutants[0]


@functools.cache
def _seeds_that_disagree_on_set_order() -> tuple[int, int]:
    """Two seeds under which an unsorted label set does and does not start at alpha.

    The mutation this pins -- dropping a ``sorted`` -- is green on the clean tree
    under every seed and only becomes seed dependent once it is applied, which is
    exactly the shape of the instability that produced a false ``kill``.
    """
    script = "print(list({'alpha', 'beta', 'gamma'})[0])"
    stable: list[int] = []
    shifted: list[int] = []
    for seed in range(64):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = str(seed)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        bucket = stable if completed.stdout.strip() == "alpha" else shifted
        bucket.append(seed)
        if stable and shifted:
            return stable[0], shifted[0]
    raise AssertionError("no seed pair disagreed on set ordering")


# --------------------------------------------------------------------------
# Baseline: the harness can say kill, and only a kill exits zero.
# --------------------------------------------------------------------------


def test_a_covered_mutation_is_killed_and_exits_zero(sandbox: _Sandbox) -> None:
    code, report = _drive(sandbox, _mutant())
    mutant = _only(report)
    assert _text(mutant, "verdict") == "kill"
    assert _text(mutant, "reason") == "tests_failed"
    assert code == 0
    assert _text(report, "verdict") == "kill"
    assert sandbox.status() == ""


# --------------------------------------------------------------------------
# Trap 1: a run that collected nothing is void, never kill.
# --------------------------------------------------------------------------


def test_an_empty_selection_is_void_not_kill(sandbox: _Sandbox) -> None:
    narrow = {"declared": "narrow", "nodes": ["-k", "no_such_test_name"]}
    code, report = _drive(sandbox, _mutant(home=narrow))
    mutant = _only(report)
    assert _text(mutant, "verdict") == "void"
    assert _text(mutant, "reason") == "no_tests_collected"
    # The empty home is caught on the clean baseline, so the mutation is never
    # applied: there is nothing to survive and nothing to restore.
    assert _number(_rows(mutant, "baselines")[0], "collected") == 0
    assert _rows(mutant, "seeds") == []
    assert not _flag(_entry(mutant, "checks"), "mutation_applied")
    assert code == 2


def test_a_missing_node_is_void_not_kill(sandbox: _Sandbox) -> None:
    narrow = {"declared": "narrow", "nodes": ["test_absent.py::test_gone"]}
    code, report = _drive(sandbox, _mutant(home=narrow))
    mutant = _only(report)
    assert _text(mutant, "verdict") == "void"
    assert _text(mutant, "reason") in {"no_tests_collected", "no_junit_report"}
    assert code == 2
    assert not _flag(_entry(mutant, "checks"), "collection_counted")


# --------------------------------------------------------------------------
# Trap 2: restore is proven over the whole tree, not over a list of files.
# --------------------------------------------------------------------------


def test_a_leftover_outside_the_target_is_a_loud_error(sandbox: _Sandbox) -> None:
    sandbox.add("sibling.txt", "clean\n")
    sandbox.add("test_side_effect.py", _TEST_SIDE_EFFECT)
    sandbox.commit()
    narrow = {"declared": "narrow", "nodes": ["test_side_effect.py"]}
    code, report = _drive(sandbox, _mutant(home=narrow))
    mutant = _only(report)
    assert _text(mutant, "verdict") == "error"
    assert _text(mutant, "reason") == "tree_not_restored"
    assert "sibling.txt" in _strings(mutant, "residual_paths")
    assert not _flag(_entry(mutant, "checks"), "restore_verified")
    assert code == 3
    assert (sandbox.root / "subject.py").read_text(encoding="utf-8") == _SUBJECT


# --------------------------------------------------------------------------
# Trap 3: a mutation that did not land yields no verdict at all.
# --------------------------------------------------------------------------


def test_a_missing_site_is_an_error(sandbox: _Sandbox) -> None:
    code, report = _drive(sandbox, _mutant(find="99 + 99"))
    assert _text(_only(report), "reason") == "find_not_found"
    assert code == 3


def test_an_ambiguous_site_is_an_error(sandbox: _Sandbox) -> None:
    code, report = _drive(sandbox, _mutant(find="return", replace="return  "))
    assert _text(_only(report), "reason") == "ambiguous_find"
    assert code == 3


def test_a_replacement_that_changes_nothing_is_an_error(sandbox: _Sandbox) -> None:
    code, report = _drive(sandbox, _mutant(replace="41 + 1"))
    mutant = _only(report)
    assert _text(mutant, "reason") == "mutation_not_applied"
    assert not _flag(_entry(mutant, "checks"), "mutation_applied")
    assert code == 3


def test_an_out_of_range_occurrence_is_an_error(sandbox: _Sandbox) -> None:
    code, report = _drive(sandbox, _mutant(occurrence=4))
    assert _text(_only(report), "reason") == "occurrence_out_of_range"
    assert code == 3


def test_an_already_red_home_yields_no_verdict(sandbox: _Sandbox) -> None:
    sandbox.add("test_broken.py", _TEST_BROKEN)
    sandbox.commit()
    narrow = {"declared": "narrow", "nodes": ["test_broken.py"]}
    code, report = _drive(sandbox, _mutant(home=narrow))
    mutant = _only(report)
    assert _text(mutant, "verdict") == "error"
    assert _text(mutant, "reason") == "home_already_red"
    assert not _flag(_entry(mutant, "checks"), "mutation_applied")
    assert code == 3
    assert (sandbox.root / "subject.py").read_text(encoding="utf-8") == _SUBJECT


# --------------------------------------------------------------------------
# Trap 4: a survivor in a narrow home is not a survivor.
# --------------------------------------------------------------------------


def test_a_narrow_home_downgrades_a_survivor(sandbox: _Sandbox) -> None:
    narrow = {"declared": "narrow", "nodes": ["test_other.py"]}
    code, report = _drive(sandbox, _mutant(home=narrow))
    mutant = _only(report)
    assert _text(mutant, "verdict") == "survive_narrow"
    assert _entry(mutant, "home")["kind"] == "narrow"
    assert code == 1
    full_code, full_report = _drive(sandbox, _mutant())
    assert _text(_only(full_report), "verdict") == "kill"
    assert full_code == 0


# --------------------------------------------------------------------------
# occurrence names a site, and the site it names is the one that changes.
# --------------------------------------------------------------------------


def _twin_sandbox(sandbox: _Sandbox) -> None:
    sandbox.add("twin.py", _TWIN)
    sandbox.add("test_twin.py", _TEST_TWIN)
    sandbox.commit()


def test_occurrence_one_reaches_the_pinned_site(sandbox: _Sandbox) -> None:
    _twin_sandbox(sandbox)
    twin = _mutant(target="twin.py", find="return 1 + 1", replace="return 1 + 2")
    code, report = _drive(sandbox, dict(twin, occurrence=1))
    assert _text(_only(report), "verdict") == "kill"
    assert code == 0


def test_occurrence_two_reaches_the_unpinned_site(sandbox: _Sandbox) -> None:
    _twin_sandbox(sandbox)
    twin = _mutant(target="twin.py", find="return 1 + 1", replace="return 1 + 2")
    _first_code, first_report = _drive(sandbox, dict(twin, occurrence=1))
    second_code, second_report = _drive(sandbox, dict(twin, occurrence=2))
    assert _text(_only(second_report), "verdict") == "survive"
    assert second_code == 1
    # Same file, same replacement, different site: the bytes must differ.
    assert _text(_only(first_report), "mutated_sha256") != _text(
        _only(second_report), "mutated_sha256"
    )


# --------------------------------------------------------------------------
# The purge spares exactly the trees it declares, and clears the rest.
# --------------------------------------------------------------------------


def test_the_purge_spares_the_directories_it_declares(sandbox: _Sandbox) -> None:
    for spared in (".git", ".venv"):
        cache = sandbox.root / spared / "__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "keep.pyc").write_bytes(b"keep")
    swept = sandbox.root / "__pycache__"
    swept.mkdir()
    (swept / "gone.pyc").write_bytes(b"gone")
    _drive(sandbox, _mutant())
    assert not swept.exists()
    assert (sandbox.root / ".git" / "__pycache__" / "keep.pyc").exists()
    assert (sandbox.root / ".venv" / "__pycache__" / "keep.pyc").exists()


# --------------------------------------------------------------------------
# A battery is worth exactly its weakest mutant.
# --------------------------------------------------------------------------


def test_a_battery_reports_its_weakest_mutant(sandbox: _Sandbox) -> None:
    narrow = {"declared": "narrow", "nodes": ["test_other.py"]}
    code, report = _drive(
        sandbox, _mutant(id="killed"), _mutant(id="survivor", home=narrow)
    )
    assert [_text(row, "verdict") for row in _rows(report, "mutants")] == [
        "kill",
        "survive_narrow",
    ]
    assert _text(report, "verdict") == "survive_narrow"
    assert code == 1


# --------------------------------------------------------------------------
# Trap 5: a verdict that depends on PYTHONHASHSEED is not a kill.
# --------------------------------------------------------------------------


def test_a_full_home_survivor_is_reported_as_survive(sandbox: _Sandbox) -> None:
    """A site no test reaches survives the full home, and survive is not narrow."""
    code, report = _drive(
        sandbox,
        _mutant(
            find='"""Return the label set in a stable order."""',
            replace='"""Return the labels."""',
        ),
    )
    mutant = _only(report)
    assert _text(mutant, "verdict") == "survive"
    assert _text(mutant, "reason") == "full_home_stayed_green"
    assert _entry(mutant, "home")["kind"] == "full"
    assert _flag(_entry(mutant, "checks"), "restore_verified")
    assert code == 1


def test_seed_disagreement_never_reports_a_kill(sandbox: _Sandbox) -> None:
    stable_seed, shifted_seed = _seeds_that_disagree_on_set_order()
    sandbox.add("test_labels.py", _TEST_LABELS)
    sandbox.commit()
    narrow = {"declared": "narrow", "nodes": ["test_labels.py"]}
    unsorted_mutant = _mutant(
        find='sorted({"alpha"',
        replace='list({"alpha"',
        home=narrow,
        seeds=[stable_seed, shifted_seed],
    )
    code, report = _drive(sandbox, unsorted_mutant)
    mutant = _only(report)
    assert _text(mutant, "verdict") == "survive_narrow"
    assert _text(mutant, "reason") == "unstable_across_seeds"
    verdicts = {_text(row, "verdict") for row in _rows(mutant, "seeds")}
    assert verdicts == {"kill", "survive_narrow"}
    assert {_text(row, "verdict") for row in _rows(mutant, "baselines")} == {
        "survive_narrow"
    }
    assert code == 1


# --------------------------------------------------------------------------
# Trap 6: exactly one mutation is live at a time.
# --------------------------------------------------------------------------


def test_a_battery_never_leaves_two_mutants_in_the_tree(
    sandbox: _Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = sandbox.control / "observed.log"
    monkeypatch.setenv("MUTATION_HARNESS_SELFTEST_LOG", str(log))
    sandbox.add("second.py", _SECOND)
    sandbox.add("test_observer.py", _TEST_OBSERVER)
    sandbox.commit()
    narrow = {"declared": "narrow", "nodes": ["test_observer.py"]}
    first = _mutant(id="first", home=narrow)
    second = _mutant(
        id="second", target="second.py", find="7 + 0", replace="7 + 1", home=narrow
    )
    _drive(sandbox, first, second)
    # One clean baseline, then one run per mutant.  Each run sees exactly one
    # mutated site and the original bytes at the other.
    clean, first_run, second_run = log.read_text(encoding="utf-8").splitlines()
    assert "41 + 1" in clean and "7 + 0" in clean
    assert "41 + 2" in first_run and "7 + 0" in first_run
    assert "41 + 1" in second_run and "7 + 1" in second_run
    assert sandbox.status() == ""


# --------------------------------------------------------------------------
# Trap 7: stale bytecode is purged, and the run writes none.
# --------------------------------------------------------------------------


def test_a_seeded_bytecode_cache_is_purged_before_the_run(sandbox: _Sandbox) -> None:
    stale = sandbox.root / "__pycache__"
    stale.mkdir()
    (stale / "subject.cpython-000.pyc").write_bytes(b"stale")
    _drive(sandbox, _mutant())
    assert not stale.exists()


def test_the_run_writes_no_bytecode_cache(sandbox: _Sandbox) -> None:
    _drive(sandbox, _mutant())
    assert list(sandbox.root.rglob("__pycache__")) == []


# --------------------------------------------------------------------------
# Trap 8: restore happens on every outcome, including a signal and a timeout.
# --------------------------------------------------------------------------


def test_a_timeout_restores_the_tree_and_refuses_a_verdict(sandbox: _Sandbox) -> None:
    sandbox.add("test_slow.py", _TEST_SLOW)
    sandbox.commit()
    narrow = {"declared": "narrow", "nodes": ["test_slow.py"]}
    code, report = _drive(sandbox, _mutant(home=narrow, timeout_seconds=2))
    mutant = _only(report)
    assert _text(mutant, "verdict") == "error"
    assert _text(mutant, "reason").startswith("timeout")
    assert code == 3
    assert (sandbox.root / "subject.py").read_text(encoding="utf-8") == _SUBJECT
    assert sandbox.status() == ""


def test_a_terminating_signal_restores_the_tree(sandbox: _Sandbox) -> None:
    sandbox.add("test_slow.py", _TEST_SLOW)
    sandbox.commit()
    narrow = {"declared": "narrow", "nodes": ["test_slow.py"]}
    plan = sandbox.plan([_mutant(home=narrow, timeout_seconds=120)])
    target = sandbox.root / "subject.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(_HARNESS),
            "--root",
            str(sandbox.root),
            "--plan",
            str(plan),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if "41 + 2" in target.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the mutation never reached the worktree")
        process.send_signal(signal.SIGTERM)
        stdout, _stderr = process.communicate(timeout=120)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert process.returncode == 3
    assert target.read_text(encoding="utf-8") == _SUBJECT
    assert sandbox.status() == ""
    payload = json.loads(stdout)
    assert isinstance(payload, dict)
    assert "interrupted" in _text(_only(payload), "reason")


# --------------------------------------------------------------------------
# Trap 9: "equivalent" is a justified annotation on a survivor, never a verdict.
# --------------------------------------------------------------------------

_JUSTIFICATION = (
    "The mutated ordering never reaches an observable output: every consumer "
    "re-sorts the sequence before serialising it."
)


def test_an_equivalence_claim_never_upgrades_a_survivor(sandbox: _Sandbox) -> None:
    narrow = {"declared": "narrow", "nodes": ["test_other.py"]}
    code, report = _drive(
        sandbox, _mutant(home=narrow, equivalence_claim=_JUSTIFICATION)
    )
    mutant = _only(report)
    assert _text(mutant, "verdict") == "survive_narrow"
    assert _flag(_entry(mutant, "equivalence"), "claimed")
    assert code == 1


def test_an_equivalence_claim_over_a_kill_is_an_error(sandbox: _Sandbox) -> None:
    code, report = _drive(sandbox, _mutant(equivalence_claim=_JUSTIFICATION))
    assert _text(_only(report), "reason") == "equivalence_claim_without_survivor"
    assert code == 3


def test_an_unjustified_equivalence_claim_is_an_error(sandbox: _Sandbox) -> None:
    narrow = {"declared": "narrow", "nodes": ["test_other.py"]}
    code, report = _drive(sandbox, _mutant(home=narrow, equivalence_claim="obvious"))
    assert _text(_only(report), "reason") == "equivalence_justification_too_short"
    assert code == 3


# --------------------------------------------------------------------------
# The git witness has a blind spot, and the harness refuses to stand in it.
# --------------------------------------------------------------------------


def test_a_git_ignored_target_is_refused(sandbox: _Sandbox) -> None:
    """git never reports an ignored path, so restore could not be proven there."""
    sandbox.add(".gitignore", _GITIGNORE + "ignored.py\n")
    sandbox.add("ignored.py", _SUBJECT)
    sandbox.commit()
    narrow = {"declared": "narrow", "nodes": ["test_other.py"]}
    code, report = _drive(sandbox, _mutant(target="ignored.py", home=narrow))
    mutant = _only(report)
    assert _text(mutant, "verdict") == "error"
    assert _text(mutant, "reason") == "target_is_git_ignored"
    assert not _flag(_entry(mutant, "checks"), "mutation_applied")
    assert (sandbox.root / "ignored.py").read_text(encoding="utf-8") == _SUBJECT
    assert code == 3


# --------------------------------------------------------------------------
# The protocol travels with the tool: no brief, no specs/ directory, no memory.
# --------------------------------------------------------------------------


def test_the_protocol_and_a_plan_template_travel_with_the_tool(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--protocol"]) == 0
    printed = capsys.readouterr().out
    for required in ('"home"', '"declared"', '"mutants"', "survive_narrow", "seeds"):
        assert required in printed


def test_a_call_without_a_plan_refuses_instead_of_defaulting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 3
    assert "--protocol" in capsys.readouterr().err


def test_every_non_kill_outcome_names_the_step_it_obliges(sandbox: _Sandbox) -> None:
    narrow = {"declared": "narrow", "nodes": ["test_other.py"]}
    _, survived = _drive(sandbox, _mutant(home=narrow))
    assert "full" in _text(_only(survived), "next_step")
    empty = {"declared": "narrow", "nodes": ["-k", "no_such_test_name"]}
    _, void = _drive(sandbox, _mutant(home=empty))
    assert "collected zero tests" in _text(_only(void), "next_step")
    _, killed = _drive(sandbox, _mutant())
    assert "mutation table" in _text(_only(killed), "next_step")


# --------------------------------------------------------------------------
# The plan is the contract: a typo must not become a default.
# --------------------------------------------------------------------------


def test_an_undeclared_home_is_rejected(sandbox: _Sandbox) -> None:
    spec = _mutant()
    del spec["home"]
    with pytest.raises(PlanError, match="home"):
        load_plan(sandbox.plan([spec]))


def test_a_misdeclared_home_is_rejected(sandbox: _Sandbox) -> None:
    spec = _mutant(home={"declared": "full", "nodes": ["test_other.py"]})
    with pytest.raises(PlanError, match="narrow"):
        load_plan(sandbox.plan([spec]))


def test_an_unknown_plan_key_is_rejected(sandbox: _Sandbox) -> None:
    with pytest.raises(PlanError, match="hoem"):
        load_plan(sandbox.plan([_mutant(hoem={"declared": "full"})]))


# --------------------------------------------------------------------------
# The digest is reproducible and sensitive to the mutation it describes.
# --------------------------------------------------------------------------


def test_the_digest_is_stable_and_mutation_sensitive(sandbox: _Sandbox) -> None:
    _, first = _drive(sandbox, _mutant())
    _, again = _drive(sandbox, _mutant())
    _, other = _drive(sandbox, _mutant(replace="41 + 3"))
    assert _text(_only(first), "digest") == _text(_only(again), "digest")
    assert _text(_only(first), "digest") != _text(_only(other), "digest")
    assert _text(first, "digest") == _text(again, "digest")

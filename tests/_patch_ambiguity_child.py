# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The ambiguous-declaration scenarios, and the child that runs them in a
fresh interpreter under one ``PYTHONHASHSEED``.

Two declarations under one ``(path, symbol)`` key are the case this pins: a
run reads them out of a ``frozenset`` (the store) or in document order (the
record), so any rule that picks one of them answers by traversal order --
measured 2026-10-19 on ``cxdup``: the stored index said ``_calc`` was 1 under
seeds 0, 1, 3, 5 and 4 under seeds 2, 4, 6, 7.  The order of a ``frozenset``
of strings only moves between interpreters, so the scenario runs in children
(``python -m tests._patch_ambiguity_child <work dir> <out.json>``), each
under its own seed, and the parent compares their answers byte for byte.

The child writes only under the work directory the parent handed it: the
analysed trees, their ``.codeclone/`` stores, and ``HOME`` / the XDG
directories, which the parent points there too.  It never opens a store it
did not create.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

#: ``cxdup``: two ``_calc`` in one module, cyclomatic complexity 1 and 4 --
#: the controller's population, byte for byte.
CXDUP_BEFORE = (
    "def _calc(value):\n    return value + 1\n\n\n"
    "def _calc(value):\n    if value > 1:\n        return 1\n"
    "    if value > 2:\n        return 2\n    if value > 3:\n        return 3\n"
    "    return 4\n\n\n"
    "def public(x):\n    return _calc(x)\n"
)
#: ``cxdup_after``: the second ``_calc`` grows from 4 to 8.
CXDUP_AFTER = (
    "def _calc(value):\n    return value + 1\n\n\n"
    "def _calc(value):\n"
    + "".join(f"    if value > {n}:\n        return {n}\n" for n in range(1, 8))
    + "    return 8\n\n\n"
    "def public(x):\n    return _calc(x)\n"
)
#: The controls: one ``_calc``, 4 then 8.
CXDUP_CONTROL_BEFORE = (
    "def _calc(value):\n"
    + "".join(f"    if value > {n}:\n        return {n}\n" for n in range(1, 4))
    + "    return 4\n\n\n"
    "def public(x):\n    return _calc(x)\n"
)
CXDUP_CONTROL_AFTER = (
    "def _calc(value):\n"
    + "".join(f"    if value > {n}:\n        return {n}\n" for n in range(1, 8))
    + "    return 8\n\n\n"
    "def public(x):\n    return _calc(x)\n"
)


def _branchy(name: str, branches: int) -> str:
    """A function of cyclomatic complexity ``branches + 1``."""
    body = "".join(
        f"    if value > {n}:\n        return {n}\n" for n in range(1, branches + 1)
    )
    return f"def {name}(value):\n{body}    return 0\n"


#: ``mixed``: the duplicated ``_calc`` (4 -> 8) beside a unique ``grow``
#: (2 -> 5) in the same module -- the guard must not swallow ``grow``.
MIXED_BEFORE = (
    "def _calc(value):\n    return value + 1\n\n\n"
    + _branchy("_calc", 3)
    + "\n\n"
    + _branchy("grow", 1)
    + "\n\ndef public(x):\n    return _calc(x) + grow(x)\n"
)
MIXED_AFTER = (
    "def _calc(value):\n    return value + 1\n\n\n"
    + _branchy("_calc", 7)
    + "\n\n"
    + _branchy("grow", 4)
    + "\n\ndef public(x):\n    return _calc(x) + grow(x)\n"
)
#: A module of four duplicated names nobody edits: several ambiguous keys,
#: so the order of the unresolved records is something a seed could move.
OTHER_MODULE = "".join(
    f"def {name}(value):\n    return value\n\n\n"
    f"def {name}(value):\n    return value + 1\n\n\n"
    for name in ("_a", "_b", "_c", "_d")
) + ("def use(value):\n    return _a(value) + _b(value) + _c(value) + _d(value)\n")

#: Three unique classes nobody edits: a class population of three measured
#: symbols, so the order the store road hands it over is one a seed could
#: lay out differently.
SHAPES_MODULE = (
    "class Alpha:\n    def run(self):\n        return Beta(), Gamma()\n\n\n"
    "class Beta:\n    def run(self):\n        return Gamma()\n\n\n"
    "class Gamma:\n    def run(self):\n        return 1\n\n"
    "    def other(self):\n        return 2\n"
)

#: ``cache_cls``: two classes ``C`` in one module, each coupled to one class.
CLASSES_BEFORE = (
    "class X:\n    pass\n\n\nclass Y:\n    pass\n\n\n"
    "class C:\n    def a(self):\n        return X()\n\n\n"
    "class C:\n    def b(self):\n        return Y()\n\n"
    "    def c(self):\n        return self.b()\n\n\n"
    "def public():\n    return C()\n"
)
#: The first ``C`` couples to both and splits in two: coupling 1 -> 2 and
#: cohesion 1 -> 2 on a declaration the last-wins index never showed.
CLASSES_AFTER = (
    "class X:\n    pass\n\n\nclass Y:\n    pass\n\n\n"
    "class C:\n    def a(self):\n        return X(), Y()\n\n"
    "    def d(self):\n        return 1\n\n\n"
    "class C:\n    def b(self):\n        return Y()\n\n"
    "    def c(self):\n        return self.b()\n\n\n"
    "def public():\n    return C()\n"
)
CLASSES_CONTROL_BEFORE = (
    CLASSES_BEFORE.replace("class C:", "class C1:", 1)
    .replace("class C:", "class C2:", 1)
    .replace("return C()", "return C1(), C2()")
)
CLASSES_CONTROL_AFTER = (
    CLASSES_AFTER.replace("class C:", "class C1:", 1)
    .replace("class C:", "class C2:", 1)
    .replace("return C()", "return C1(), C2()")
)

#: ``beside``: the duplicated ``_calc`` (1 and 4) untouched at the top of the
#: module, and a unique ``grow`` BELOW them that grows 2 -> 5: no line of
#: either ``_calc`` moves, so their measured positions and metrics are the
#: same on both sides and ``grow`` is verified as usual.
BESIDE_BEFORE = (
    "def _calc(value):\n    return value + 1\n\n\n"
    + _branchy("_calc", 3)
    + "\n\n"
    + _branchy("grow", 1)
    + "\n\ndef public(x):\n    return _calc(x) + grow(x)\n"
)
BESIDE_AFTER = (
    "def _calc(value):\n    return value + 1\n\n\n"
    + _branchy("_calc", 3)
    + "\n\n"
    + _branchy("grow", 4)
    + "\n\ndef public(x):\n    return _calc(x) + grow(x)\n"
)
#: ``shifted``: one line added ABOVE the duplicates and nothing else: every
#: ``_calc`` keeps its value and moves down one line -- a different
#: position, so the key is not ``no_measured_change`` (by design, until
#: declarations carry an identity of their own).
SHIFTED_AFTER = "CONSTANT = 1\n" + BESIDE_BEFORE

#: ``same_vector``: two ``_calc`` of one complexity (1 and 1) -- the same
#: vector at two positions; the patch deletes the second.
SAME_VECTOR_BEFORE = (
    "def _calc(value):\n    return value + 1\n\n\n"
    "def _calc(value):\n    return value + 2\n\n\n"
    "def public(x):\n    return _calc(x)\n"
)
SAME_VECTOR_AFTER = (
    "def _calc(value):\n    return value + 1\n\n\ndef public(x):\n    return _calc(x)\n"
)
#: ``grown_pair``: one ``_calc`` becomes two -- the first unchanged, a
#: second added below it.
GROWN_PAIR_BEFORE = SAME_VECTOR_AFTER
GROWN_PAIR_AFTER = SAME_VECTOR_BEFORE
#: ``gone``: both ``_calc`` removed (2 -> 0), and their mirror (0 -> 2).
GONE_BEFORE = SAME_VECTOR_BEFORE
GONE_AFTER = "def public(x):\n    return x\n"

#: ``class_coupling``: two ``class C`` whose methods share their names, so
#: every method key names two declarations too.  The patch makes the first
#: ``C.run`` build a ``Y`` as well, on the same line: no line moves, no
#: method's complexity changes, cohesion stays 1 -- only the first ``C``'s
#: coupling grows 1 -> 2.
CLASS_COUPLING_BEFORE = (
    "class X:\n    pass\n\n\nclass Y:\n    pass\n\n\n"
    "class C:\n    def run(self):\n        return X()\n\n\n"
    "class C:\n    def run(self):\n        return Y()\n\n\n"
    "def public():\n    return C()\n\n\n" + _branchy("grow", 1)
)
CLASS_COUPLING_AFTER = CLASS_COUPLING_BEFORE.replace(
    "        return X()\n", "        return X(), Y()\n", 1
)
#: The class control: the same two ``class C`` untouched, ``grow`` below
#: them grows -- the class key holds the same measured metrics at the same
#: positions, so only ``grow`` is compared.
CLASS_BESIDE_AFTER = CLASS_COUPLING_BEFORE.replace(
    _branchy("grow", 1), _branchy("grow", 4)
)

#: Every scenario the children run: (files before, files after, edited file).
SEED_SCENARIOS: Mapping[str, tuple[dict[str, str], dict[str, str], str]] = {
    "cxdup": (
        {"app/__init__.py": "", "app/mod.py": CXDUP_BEFORE},
        {"app/mod.py": CXDUP_AFTER},
        "app/mod.py",
    ),
    "mixed": (
        {
            "app/__init__.py": "",
            "app/mod.py": MIXED_BEFORE,
            "app/other.py": OTHER_MODULE,
            "app/shapes.py": SHAPES_MODULE,
        },
        {"app/mod.py": MIXED_AFTER},
        "app/mod.py",
    ),
    "beside": (
        {"app/__init__.py": "", "app/mod.py": BESIDE_BEFORE},
        {"app/mod.py": BESIDE_AFTER},
        "app/mod.py",
    ),
}

#: The verify fields the children report, in this order.
VERIFY_FIELDS: tuple[str, ...] = (
    "status",
    "reason",
    "worsened",
    "intent_worsened",
    "external_worsened",
    "unresolved",
    "intent_unresolved",
    "external_unresolved",
    "unpaired",
    "checks_not_performed",
    "limitations",
    "next_step",
)


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def write_tree(root: Path, files: Mapping[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")


def committed_tree(root: Path, files: Mapping[str, str]) -> Path:
    """A git repository holding ``files``, its own ``.codeclone/`` ignored."""
    root.mkdir(parents=True)
    write_tree(root, {**files, ".gitignore": ".codeclone/\n"})
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "tree")
    return root


def verify_fields(payload: Mapping[str, object]) -> dict[str, object]:
    """The verify answer's typed fields, each present one or absent."""
    return {key: payload[key] for key in VERIFY_FIELDS if key in payload}


def _serving(payload: Mapping[str, object]) -> dict[str, object]:
    serving = payload.get("serving")
    assert isinstance(serving, Mapping), payload
    return {key: serving.get(key) for key in ("source", "reason")}


def road_states(service: object, root: Path, run_id: str) -> dict[str, object]:
    """``current_state`` of one run on each road, read directly -- not the
    served answer, which falls back to memory whenever the roads differ."""
    from codeclone.api.run_store_serving import read_run_store_patch_run
    from codeclone.surfaces.mcp._patch_contract_runs import (
        PatchSession,
        RecordPatchRun,
        StorePatchRun,
    )
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    assert isinstance(service, CodeCloneMCPService)
    session = cast("PatchSession", service)
    record = service._runs.get_for_root(run_id, root=root)
    os.environ["CODECLONE_SERVE_FROM"] = "run_store"
    stored, outcome = read_run_store_patch_run(
        root=record.root, link=record.execution.run_snapshot_link
    )
    os.environ.pop("CODECLONE_SERVE_FROM", None)
    assert stored is not None, outcome
    return {
        "store": StorePatchRun(session, record, stored).current_state(),
        "record": RecordPatchRun(session, record).current_state(),
        # The stored population itself, in the order the store road hands
        # it over: a ``frozenset`` laid out by the seed unless it is sorted.
        "population": {
            family: [
                [list(key), None if span is None else list(span), value]
                for key, span, value in population
            ]
            for family, population in stored.metric_items.items()
        },
    }


def run_scenario(work: Path, name: str) -> dict[str, object]:
    """One controlled change over the scenario, every answer it gives."""
    from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    before_files, after_files, edited = SEED_SCENARIOS[name]
    root = committed_tree(work / name, before_files)
    service = CodeCloneMCPService(history_limit=4)
    os.environ.pop("CODECLONE_SERVE_FROM", None)
    before = str(
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
    )
    answers: dict[str, object] = {"roads:before": road_states(service, root, before)}
    for serve_from in ("run_store", "memory"):
        os.environ["CODECLONE_SERVE_FROM"] = serve_from
        budget = service.check_patch_contract(
            mode="budget", run_id=before, root=str(root)
        )
        answers[f"budget:{serve_from}"] = {
            "current_state": budget["current_state"],
            "serving": _serving(budget),
        }
    os.environ.pop("CODECLONE_SERVE_FROM", None)
    started = service.start_controlled_change(
        root=str(root), scope={"allowed_files": [edited]}, intent=f"seed {name}"
    )
    assert started.get("edit_allowed") is True, started
    intent_id = str(started["intent_id"])
    write_tree(root, after_files)
    after = str(
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))["run_id"]
    )
    answers["roads:after"] = road_states(service, root, after)
    for serve_from in ("run_store", "memory"):
        os.environ["CODECLONE_SERVE_FROM"] = serve_from
        verified = service.check_patch_contract(
            mode="verify",
            intent_id=intent_id,
            after_run_id=after,
            changed_files=[edited],
            root=str(root),
        )
        answers[f"verify:{serve_from}"] = {
            "fields": verify_fields(verified),
            "serving": _serving(verified),
        }
    os.environ["CODECLONE_SERVE_FROM"] = "run_store"
    for attempt in ("finish", "finish_again"):
        try:
            finished = service.finish_controlled_change(
                intent_id=intent_id, after_run_id=after, changed_files=[edited]
            )
        except Exception as refusal:  # a refusal is an answer, compared too
            answers[attempt] = {"__refused__": type(refusal).__name__}
            continue
        verification = finished.get("verification")
        answers[attempt] = {
            "status": finished.get("status"),
            "reason": finished.get("reason"),
            "user_action_required": finished.get("user_action_required"),
            "intent_cleared": finished.get("intent_cleared"),
            # A receipt carries its execution id and its time: whether one
            # was written is the answer, its bytes are not a seed's.
            "receipt": None if finished.get("receipt") is None else "written",
            "claims": finished.get("claims"),
            "verification": (
                verify_fields(verification)
                if isinstance(verification, Mapping)
                else None
            ),
        }
    return answers


#: The child's own positive control: ``--probe-live-store`` asks for a
#: database under the hosting checkout's ``.codeclone/`` -- read-only and
#: absent, so even an unguarded child would create nothing -- and the guard
#: must refuse it before SQLite is reached.
PROBE_LIVE_STORE = "--probe-live-store"


def main(argv: list[str]) -> int:
    work, out = Path(argv[1]), Path(argv[2])
    for variable in (
        "HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "TMPDIR",
    ):
        assert Path(os.environ[variable]).is_relative_to(work), variable
    # The fence the test session runs under, installed in this interpreter
    # too: a child is outside the session's in-process enforcement.
    from tests._live_state import HOSTING_CHECKOUT, LiveStateGuard

    guard = LiveStateGuard.install(hosting_checkout=HOSTING_CHECKOUT)
    if argv[3:] == [PROBE_LIVE_STORE]:
        import sqlite3

        live = HOSTING_CHECKOUT / ".codeclone" / "db" / "ambiguity-guard-probe.sqlite3"
        sqlite3.connect(f"file:{live}?mode=ro", uri=True)
        return 0
    os.environ["CODECLONE_RUN_STORE_ENABLED"] = "1"
    os.environ["CODECLONE_RUN_STORE_FORCE"] = "1"
    os.environ.pop("CODECLONE_RUN_STORE_PATH", None)
    result = {name: run_scenario(work, name) for name in SEED_SCENARIOS}
    if guard.violations:
        raise SystemExit(f"live state reached: {guard.violations}")
    out.write_text(json.dumps(result, sort_keys=False, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The recovery child's START/RESULT protocol, file by file.

Maintainer ruling 2026-10-26. The one recovery child announces each file
(START) and then sends its whole result (RESULT). The parent:

* confirms a file only after a complete RESULT for the file it announced
  has arrived and been validated -- a START confirms nothing;
* names the file in flight as the culprit when the child dies or hangs; a
  death between files, or before the first, has an UNKNOWN culprit and is
  never pinned on the last name it saw;
* gives every file its own deadline, not the queue one deadline;
* leaves no child process, zombie or descriptor behind, however it ended.

Every error names three classes: confirmed, culprit (or UNKNOWN), and not
processed. Children are real; deaths are ``os._exit``.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from collections.abc import Callable, Mapping
from functools import partial
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from types import SimpleNamespace

import pytest

import codeclone.core.worker_recovery as recovery
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.core._types import FileProcessResult
from codeclone.core.worker_recovery import WorkerRecoveryError, recover_in_isolation
from codeclone.paths.module_identity.inventory import build_module_registry
from tests import _worker_death_probe as probe

_WORKER_SETTINGS: dict[str, object] = {
    "cfg": NormalizationConfig(),
    "min_loc": 1,
    "min_stmt": 1,
    "collect_structural_findings": False,
    "collect_api_surface": False,
    "api_include_private_modules": False,
    "collect_near_miss": False,
    "collect_renamed_structure": False,
    "block_min_loc": 20,
    "block_min_stmt": 8,
    "segment_min_loc": 20,
    "segment_min_stmt": 10,
}


_REAL_WORKER: Callable[..., FileProcessResult] = probe._real


def _open_descriptors() -> int:
    return len(os.listdir("/dev/fd"))


def _warm_start_method() -> None:
    """Start the helpers a start method keeps for the life of this process --
    the resource tracker under spawn, the server under forkserver -- so the
    descriptor count measures the recovery and not them. Measured: the first
    spawned child opens exactly one descriptor, the tracker's, and every
    later child opens none."""

    child = multiprocessing.Process(target=int)
    child.start()
    child.join()
    child.close()


class _Recovery:
    """One ``recover_in_isolation`` over ``a.py``, ``b.py``, ``c.py``."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        invoke: Callable[..., FileProcessResult],
        *,
        reuse: Mapping[str, object] | None = None,
        timeout: float | None = None,
        script: tuple[tuple[object, ...], ...] | None = None,
    ) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        (tmp_path / probe.PROBE_DIR_NAME).mkdir()
        self.files = []
        for name in ("a", "b", "c"):
            path = root / f"{name}.py"
            path.write_text(f"def {name}():\n    return 1\n", "utf-8")
            self.files.append(str(path))
        if timeout is not None:
            monkeypatch.setattr(recovery, "ISOLATED_RECOVERY_TIMEOUT_SECONDS", timeout)
        self.pids: list[int] = []
        real_start = (
            recovery._start_recovery_process
            if script is None
            else partial(_start_scripted_child, script)
        )

        def _recording_start(args: tuple[object, ...]) -> object:
            child, receiver = real_start(args)
            self.pids.append(int(child.pid or 0))
            return child, receiver

        monkeypatch.setattr(recovery, "_start_recovery_process", _recording_start)
        self.accepted: list[str] = []
        self.advanced = 0
        self.error: WorkerRecoveryError | None = None
        _warm_start_method()
        descriptors = _open_descriptors()
        started = time.monotonic()
        try:
            recover_in_isolation(
                files=tuple(self.files),
                lost=frozenset(self.files),
                worker=partial(invoke, root=str(root), **_WORKER_SETTINGS),
                registry=build_module_registry(root=root),
                neutral_reuse=reuse if reuse is not None else {},  # type: ignore[arg-type]
                collect_phases=False,
                accept=lambda result: self.accepted.append(Path(result.filepath).name),
                on_advance=self._advance,
                root=str(root),
            )
        except WorkerRecoveryError as exc:
            self.error = exc
        self.elapsed = time.monotonic() - started
        self.leaked_descriptors = _open_descriptors() - descriptors

    def _advance(self) -> None:
        self.advanced += 1

    def names(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(Path(path).name for path in paths)

    def assert_released(self) -> None:
        """No child, no zombie, no descriptor outlives the recovery."""

        assert multiprocessing.active_children() == []
        for pid in self.pids:
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
        assert self.leaked_descriptors == 0


def _start_scripted_child(
    script: tuple[tuple[object, ...], ...], args: tuple[object, ...]
) -> tuple[BaseProcess, Connection]:
    """Start a child that speaks ``script`` instead of the real protocol:
    the parent's side, measured against a peer that breaks it on purpose."""

    receiver, sender = multiprocessing.Pipe(duplex=False)
    child = multiprocessing.Process(
        target=probe.speak, args=(sender, script, args[1], args[2]), daemon=True
    )
    child.start()
    sender.close()
    return child, receiver


_WHOLE_CONVERSATION = (
    ("start", 0),
    ("result", 0),
    ("start", 1),
    ("result", 1),
    ("start", 2),
    ("result", 2),
)


@pytest.mark.parametrize(
    "script",
    [(*_WHOLE_CONVERSATION, ("done",)), _WHOLE_CONVERSATION],
    ids=["done", "no-done"],
)
def test_a_scripted_child_that_answers_every_file_is_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: tuple[tuple[object, ...]]
) -> None:
    """Positive control for the scripted peer, and the end of the talk: a
    child that answered every file and then ends without DONE leaves nothing
    unverified -- it is ended, not blamed."""

    run = _Recovery(tmp_path, monkeypatch, probe.run_in_child, script=script)

    assert run.error is None
    assert run.accepted == ["a.py", "b.py", "c.py"]
    run.assert_released()


def test_the_parent_hears_the_child_out_before_closing_the_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child is slow to say DONE. The parent waits for it, so the child
    never writes into a channel nobody reads: no broken pipe, a clean exit."""

    script = (*_WHOLE_CONVERSATION, ("pause", 0.5), ("done",))
    run = _Recovery(tmp_path, monkeypatch, probe.run_in_child, script=script)

    assert run.error is None
    assert run.accepted == ["a.py", "b.py", "c.py"]
    assert not (tmp_path / probe.PROBE_DIR_NAME / probe.BROKEN_PIPE_MARKER).exists()
    run.assert_released()


def test_a_child_that_lingers_after_done_is_ended_after_its_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every file confirmed and DONE said, but the child does not exit: it
    gets its grace, then it is killed and reaped -- nothing outlives the
    recovery even when the recovery succeeded."""

    monkeypatch.setattr(recovery, "_CHILD_EXIT_GRACE_SECONDS", 0.5)
    script = (*_WHOLE_CONVERSATION, ("done",), ("pause", probe.HANG_SECONDS))
    run = _Recovery(tmp_path, monkeypatch, probe.run_in_child, script=script)

    assert run.error is None
    assert run.accepted == ["a.py", "b.py", "c.py"]
    assert run.elapsed < probe.HANG_SECONDS / 2
    run.assert_released()


def test_a_result_that_is_not_a_file_result_is_never_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(
        tmp_path,
        monkeypatch,
        probe.run_in_child,
        script=(("start", 0), ("result-not-a-result", 0)),
    )

    error = run.error
    assert error is not None
    assert run.accepted == []
    assert Path(str(error.culprit)).name == "a.py"
    assert "engine invariant: expected a file result, got str" in error.failure
    run.assert_released()


def test_a_message_that_is_not_a_message_has_an_unknown_culprit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(
        tmp_path, monkeypatch, probe.run_in_child, script=(("raw", "garbage"),)
    )

    error = run.error
    assert error is not None
    assert error.culprit is None
    assert "isolated process sent str" in error.failure
    assert run.names(error.not_processed) == ("a.py", "b.py", "c.py")
    run.assert_released()


def test_a_start_for_another_file_has_an_unknown_culprit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child announces ``c.py`` where ``b.py`` is due: the parent never
    saw ``b.py`` start, so it names no culprit rather than guess one."""

    script = (("start", 0), ("result", 0), ("start", 2))
    run = _Recovery(tmp_path, monkeypatch, probe.run_in_child, script=script)

    error = run.error
    assert error is not None
    assert run.accepted == ["a.py"]
    assert error.culprit is None
    assert "expected the start of" in error.failure
    assert run.names(error.not_processed) == ("b.py", "c.py")
    run.assert_released()


def test_a_result_cut_short_is_never_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(
        tmp_path,
        monkeypatch,
        probe.run_in_child,
        script=(("start", 0), ("result-only", 0)),
    )

    error = run.error
    assert error is not None
    assert run.accepted == []
    assert Path(str(error.culprit)).name == "a.py"
    assert "engine invariant: expected the result of" in error.failure
    assert run.names(error.not_processed) == ("b.py", "c.py")
    run.assert_released()


def test_a_recovered_queue_confirms_every_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(tmp_path, monkeypatch, probe.run_in_child)

    assert run.error is None
    assert run.accepted == ["a.py", "b.py", "c.py"]
    assert run.advanced == 3
    assert len(run.pids) == 1
    run.assert_released()


def test_a_death_mid_queue_splits_confirmed_culprit_and_unprocessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(tmp_path, monkeypatch, probe.die_in_child_on_b)

    error = run.error
    assert error is not None
    assert run.accepted == ["a.py"]
    assert Path(str(error.culprit)).name == "b.py"
    assert "exited with code 13" in error.failure
    assert error.attempts == 2
    assert run.names(error.confirmed) == ("a.py",)
    assert run.names(error.not_processed) == ("c.py",)
    # Progress moves for the confirmed file only, never for the culprit.
    assert run.advanced == 1
    message = " ".join(str(error).split())
    assert "b.py" in message
    assert "confirmed: 1 (a.py)" in message
    assert "not processed: 1 (c.py)" in message
    run.assert_released()


def test_a_death_between_files_has_an_unknown_culprit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(
        tmp_path, monkeypatch, probe.run_in_child, reuse=probe.DieOnLookup("b.py")
    )

    error = run.error
    assert error is not None
    assert run.accepted == ["a.py"]
    assert error.culprit is None
    assert "UNKNOWN" in str(error)
    assert run.names(error.confirmed) == ("a.py",)
    assert run.names(error.not_processed) == ("b.py", "c.py")
    run.assert_released()


def test_a_death_before_the_first_file_has_an_unknown_culprit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(
        tmp_path, monkeypatch, probe.run_in_child, reuse=probe.DieOnLookup("a.py")
    )

    error = run.error
    assert error is not None
    assert run.accepted == []
    assert error.culprit is None
    assert run.names(error.not_processed) == ("a.py", "b.py", "c.py")
    run.assert_released()


def test_one_hung_file_times_out_mid_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(tmp_path, monkeypatch, probe.hang_in_child_on_b, timeout=2.0)

    error = run.error
    assert error is not None
    assert run.accepted == ["a.py"]
    assert Path(str(error.culprit)).name == "b.py"
    assert "no result within 2 s" in error.failure
    assert run.names(error.not_processed) == ("c.py",)
    assert run.elapsed < probe.HANG_SECONDS / 2
    run.assert_released()


def test_the_deadline_is_per_file_not_per_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three files of 1.2 s each outlast a 2.5 s deadline together, never
    one at a time: a deadline over the queue would fail this run."""

    run = _Recovery(tmp_path, monkeypatch, probe.slow_in_child, timeout=2.5)

    assert run.error is None
    assert run.accepted == ["a.py", "b.py", "c.py"]
    assert run.elapsed > 3 * probe.SLOW_SECONDS
    run.assert_released()


def test_a_result_for_another_file_is_not_confirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _Recovery(tmp_path, monkeypatch, probe.answer_for_a_on_b)

    error = run.error
    assert error is not None
    assert run.accepted == ["a.py"]
    assert Path(str(error.culprit)).name == "b.py"
    assert "engine invariant" in error.failure
    run.assert_released()


@pytest.mark.parametrize(
    ("process", "words", "failure"),
    [
        (
            probe.RefusedProcess,
            "Resource temporarily unavailable",
            {"reason": "process_creation_unavailable", "errno": "EAGAIN"},
        ),
        (
            probe.UnstartableProcess,
            "the start method is misconfigured",
            {"reason": "process_creation_failed"},
        ),
    ],
    ids=["refused-by-the-os", "unproven-cause"],
)
def test_a_recovery_process_that_cannot_start_is_an_internal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    process: type[probe.RefusedProcess],
    words: str,
    failure: dict[str, str],
) -> None:
    """The process never starts -- refused by the operating system (a
    process limit, say), or for a cause nobody proved. Exit 5 either way; the
    recovery failure says which, as data."""

    monkeypatch.setattr(
        recovery,
        "multiprocessing",
        SimpleNamespace(Pipe=multiprocessing.Pipe, Process=process),
    )
    run = _Recovery(tmp_path, monkeypatch, probe.run_in_child)

    error = run.error
    assert error is not None
    assert run.accepted == []
    assert error.culprit is None
    assert "recovery process could not start" in error.failure
    assert words in error.failure
    recovery_failure = error.diagnosis()["recovery_failure"]
    assert isinstance(recovery_failure, dict)
    assert {key: recovery_failure[key] for key in failure} == failure
    assert run.names(error.not_processed) == ("a.py", "b.py", "c.py")
    assert run.leaked_descriptors == 0
    assert multiprocessing.active_children() == []


def test_the_child_speaks_start_and_result_for_every_file(tmp_path: Path) -> None:
    """The child's side of the protocol, run in this process: its messages
    are measured here, where coverage sees them."""

    root = tmp_path / "proj"
    root.mkdir()
    files = []
    for name in ("a", "b"):
        path = root / f"{name}.py"
        path.write_text(f"def {name}():\n    return 1\n", "utf-8")
        files.append(str(path))
    receiver, sender = multiprocessing.Pipe(duplex=False)
    try:
        recovery._recovery_child(
            sender,
            build_module_registry(root=root),
            partial(_REAL_WORKER, root=str(root), **_WORKER_SETTINGS),
            tuple(files),
            {},
            False,
        )
        messages: list[tuple[object, ...]] = []
        # The child closed its end after DONE: everything it sent is
        # buffered, and reading past DONE would be reading past the protocol.
        while not messages or messages[-1] != ("done",):
            messages.append(receiver.recv())
    finally:
        receiver.close()
        _close_quietly(sender)

    assert [message[:2] for message in messages] == [
        ("start", files[0]),
        ("result", files[0]),
        ("start", files[1]),
        ("result", files[1]),
        ("done",),
    ]
    assert all(
        isinstance(message[2], FileProcessResult) and message[2].filepath == message[1]
        for message in messages
        if message[0] == "result"
    )


def _close_quietly(connection: Connection) -> None:
    if not connection.closed:
        connection.close()

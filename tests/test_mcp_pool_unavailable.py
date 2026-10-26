# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What an MCP client receives when the worker pool cannot start.

Maintainer rulings 2026-10-26: the analysis did not run, so the answer is a
failed tool call (``isError``), never a success carrying a warning. It is
machine-readable: the reason, the completeness the client may assume, whether
the call may succeed later, and the remediation as data. A pool start that
fails for an unproven cause is NOT given that answer -- it stays the internal
failure it may be.

These tests read the response an MCP client really receives: the real
server, a real client session over the SDK's in-memory transport, the real
``CallToolResult`` -- not the function that builds the answer.
"""

from __future__ import annotations

import asyncio
import errno
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests._pool_refusal import (
    KILLER_FILE,
    PROBE_DIR_NAME,
    PROCESS_LIMIT_REFUSAL,
    crash_a_worker_and_refuse_recovery,
    files_for_a_pool,
    refuse_the_pool,
)

pytest.importorskip("mcp.server.fastmcp")

from mcp.shared.memory import (
    create_connected_server_and_client_session,
)
from mcp.types import CallToolResult, TextContent

from codeclone.contracts.errors import (
    ExecutionUnavailableError,
    IncompleteAnalysisError,
)
from codeclone.surfaces.mcp.server import build_mcp_server

_PROCESSES = 2


def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name, sub in (
        ("XDG_CONFIG_HOME", ".config"),
        ("XDG_CACHE_HOME", ".cache"),
        ("XDG_DATA_HOME", ".local/share"),
        ("XDG_STATE_HOME", ".local/state"),
    ):
        monkeypatch.setenv(name, str(home / sub))


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    for index in range(files_for_a_pool(_PROCESSES)):
        (root / f"m{index:02d}.py").write_text(
            f"def unused_{index}(value):\n    return value + {index}\n", "utf-8"
        )
    return root


def _call(tool: str, arguments: dict[str, object]) -> CallToolResult:
    server = build_mcp_server(history_limit=4)

    async def _round_trip() -> CallToolResult:
        async with create_connected_server_and_client_session(
            server._mcp_server
        ) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(_round_trip())


class _Response:
    """One real response, from a fresh project under a temporary home."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        prepare: Callable[[Path], None],
        *,
        tool: str = "analyze_repository",
        processes: int = _PROCESSES,
    ) -> None:
        _isolated_home(tmp_path, monkeypatch)
        root = _project(tmp_path)
        prepare(root)
        arguments: dict[str, object] = {"root": str(root), "processes": processes}
        if tool == "analyze_changed_paths":
            arguments["changed_paths"] = ["m00.py"]
        self.result = _call(tool, arguments)
        self.text = " ".join(
            block.text
            for block in self.result.content
            if isinstance(block, TextContent)
        )

    def failed(self) -> dict[str, object]:
        """The typed answer of a failed call -- the same JSON as its text."""

        assert self.result.isError is True
        answer = self.result.structuredContent
        assert answer is not None
        assert json.loads(self.text) == answer
        return answer


def _reason_and(failure: object, key: str) -> tuple[object, object]:
    assert isinstance(failure, dict)
    return failure["reason"], failure[key]


@pytest.mark.parametrize("tool", ["analyze_repository", "analyze_changed_paths"])
def test_a_pool_the_environment_refuses_is_a_failed_call_with_a_typed_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    response = _Response(
        tmp_path,
        monkeypatch,
        lambda _root: refuse_the_pool(monkeypatch, PROCESS_LIMIT_REFUSAL),
        tool=tool,
    )

    answer = response.failed()
    assert answer["status"] == "execution_unavailable"
    assert answer["reason"] == "process_pool_unavailable"
    assert answer["completeness"] == "unverified"
    assert answer["retryable"] is True
    assert answer["remediation"] == {"action": "use_sequential_mode", "processes": 1}
    assert "processes=1" in str(answer["next_step"])
    assert "Resource temporarily unavailable" in str(answer["detail"])
    assert "run_id" not in answer and "health" not in answer
    message = str(answer["message"])
    assert message.startswith("Could not start the worker process pool.")
    assert "processes=1" in message


@pytest.mark.parametrize(
    "error",
    [RuntimeError("pool bootstrap broke"), OSError(errno.EINVAL, "Invalid argument")],
    ids=["runtime-error", "einval"],
)
def test_a_pool_start_failure_of_unproven_cause_is_not_called_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    """The typed answer is for a cause proven to be the environment's. An
    internal error at pool start is still a failed call, with its own error
    -- never reason ``process_pool_unavailable`` and never ``retryable``."""

    response = _Response(
        tmp_path, monkeypatch, lambda _root: refuse_the_pool(monkeypatch, error)
    )

    assert response.result.isError is True
    assert response.result.structuredContent is None
    assert str(error) in response.text
    assert "process_pool_unavailable" not in response.text
    assert "retryable" not in response.text


def _crash_a_worker_then_refuse_recovery(
    monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    (root / KILLER_FILE).write_text("def killer():\n    return 0\n", "utf-8")
    (root.parent / PROBE_DIR_NAME).mkdir()
    crash_a_worker_and_refuse_recovery(monkeypatch)


def test_a_refused_recovery_answers_with_both_failures_and_no_false_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker died, then the recovery process was refused: an internal
    failure (exit 5 on the CLI), answered as a failed call that keeps both
    failures, the crash first -- and offers no ``processes=1``, which would
    only avoid the pool and leave the crash unexplained."""

    response = _Response(
        tmp_path,
        monkeypatch,
        lambda root: _crash_a_worker_then_refuse_recovery(monkeypatch, root),
    )

    answer = response.failed()
    assert (answer["status"], answer["reason"], answer["completeness"]) == (
        "analysis_failed",
        "worker_recovery_failed",
        "unverified",
    )
    assert _reason_and(answer["primary_failure"], "cause") == (
        "worker_crashed",
        "unknown",
    )
    assert _reason_and(answer["recovery_failure"], "errno") == (
        "process_creation_unavailable",
        "EAGAIN",
    )
    assert "remediation" not in answer
    assert "processes=1" not in response.text
    assert "use_sequential_mode" not in response.text


@pytest.mark.parametrize(
    ("error", "status", "reason"),
    [
        (
            ExecutionUnavailableError("a family the server has no words for"),
            "execution_unavailable",
            "execution_unavailable",
        ),
        (
            IncompleteAnalysisError("a family the server has no words for"),
            "analysis_failed",
            "analysis_incomplete",
        ),
    ],
    ids=["unverified", "incomplete"],
)
def test_a_marker_family_without_words_of_its_own_still_answers_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    status: str,
    reason: str,
) -> None:
    """The server reads the marker, not a list of families: a family it has
    no words for still fails the call with a typed answer, in its own words,
    claiming no remedy it does not have."""

    response = _Response(
        tmp_path, monkeypatch, lambda _root: refuse_the_pool(monkeypatch, error)
    )

    answer = response.failed()
    assert (answer["status"], answer["reason"]) == (status, reason)
    assert answer["completeness"] == "unverified"
    assert answer["message"] == str(error)
    assert answer.get("remediation", {}) == {}


def test_sequential_mode_answers_normally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control on the same server, tree and refused pool: the remedy
    the answer names -- ``processes=1`` -- never starts a pool and analyses."""

    response = _Response(
        tmp_path,
        monkeypatch,
        lambda _root: refuse_the_pool(monkeypatch, PROCESS_LIMIT_REFUSAL),
        processes=1,
    )

    assert response.result.isError is False
    assert response.result.structuredContent is not None
    assert response.result.structuredContent["run_id"]

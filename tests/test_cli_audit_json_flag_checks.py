# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``--audit-json`` is refused in every combination ``--audit`` is refused in.

The flag checks read ``--audit`` alone, while the query that runs before the
analysis answers both spellings and exits with the audit's own code. So
``--audit-json --patch-verify`` printed the audit summary and exited 0
without verifying anything -- a green gate for a check that never ran -- and
``--audit-json --update-baseline`` or a changed-scope flag was silently
ignored the same way.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codeclone.surfaces.cli import controller_queries
from codeclone.surfaces.cli.console import make_plain_console
from tests._cli_child import CHILD_TIMEOUT_SECONDS, child_env, run_codeclone
from tests._tmp_tree import write_files

# Records one ``analysis.completed`` event in the root's own audit store, in
# a child process: the audit writer is not this suite's subject.
_SEED_AUDIT_EVENT = """
import sys
from pathlib import Path
from codeclone.audit.analysis_completed import emit_analysis_completed
from codeclone.audit.validation import DEFAULT_AUDIT_PATH
from codeclone.audit.writer import SqliteAuditWriter

root = Path(sys.argv[1])
db_path = root / DEFAULT_AUDIT_PATH
db_path.parent.mkdir(parents=True, exist_ok=True)
writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
emit_analysis_completed(
    root_path=root,
    summary={"files": 1},
    source="cli",
    report_digest="sha256:" + "0" * 64,
    run_id="r" * 12,
    agent_pid=1,
    agent_start_epoch=1,
    agent_label="test",
    writer=writer,
)
writer.close()
"""


def _args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "blast_radius": None,
        "patch_verify": False,
        "session_stats": False,
        "audit": False,
        "audit_json": False,
        "strictness": "ci",
        "update_baseline": False,
        "changed_only": False,
        "diff_against": None,
        "paths_from_git_diff": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("combined", "message"),
    [
        ({"patch_verify": True}, "cannot be combined with --blast-radius"),
        ({"blast_radius": ["a.py"]}, "cannot be combined with --blast-radius"),
        ({"session_stats": True}, "--session-stats cannot be combined"),
        ({"update_baseline": True}, "cannot update baselines"),
        ({"changed_only": True}, "changed-scope flags"),
        ({"diff_against": "HEAD"}, "changed-scope flags"),
    ],
)
@pytest.mark.parametrize("audit_flag", ["audit", "audit_json"])
def test_both_audit_spellings_are_refused_alike(
    audit_flag: str,
    combined: dict[str, object],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        controller_queries.validate_controller_query_flags(
            args=_args(**{audit_flag: True}, **combined),
            printer=make_plain_console(),
        )

    assert exc.value.code == 2
    assert message in capsys.readouterr().out


@pytest.mark.parametrize("audit_flag", ["audit", "audit_json"])
def test_an_audit_query_alone_passes_the_checks(audit_flag: str) -> None:
    """Positive control: the refusal is about the combination, not the flag."""

    controller_queries.validate_controller_query_flags(
        args=_args(**{audit_flag: True}),
        printer=make_plain_console(),
    )


@pytest.mark.parametrize("audit_flag", ["--audit", "--audit-json"])
def test_an_audit_query_with_patch_verify_is_refused_end_to_end(
    tmp_path: Path, audit_flag: str
) -> None:
    root = tmp_path / "proj"
    write_files(
        root,
        ("mod.py", "VALUE = 1\n"),
        ("pyproject.toml", "[tool.codeclone]\naudit_enabled = true\n"),
    )
    # One recorded event, so the audit query alone answers exit 0.
    seeded = subprocess.run(
        [sys.executable, "-c", _SEED_AUDIT_EVENT, str(root)],
        cwd=str(tmp_path),
        env=child_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_TIMEOUT_SECONDS,
    )
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    alone = run_codeclone(tmp_path, str(root), audit_flag)
    assert alone.returncode == 0, alone.stdout + alone.stderr

    run = run_codeclone(tmp_path, str(root), audit_flag, "--patch-verify")

    output = run.stdout + run.stderr
    assert run.returncode == 2, output
    assert "cannot be combined with --blast-radius or --patch-verify" in output

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from ... import ui_messages as ui
from ...contracts import ExitCode
from ...utils import coerce as _coerce
from ...utils.git_diff import validate_git_diff_ref
from . import state as cli_state
from .types import ChangedCloneGate

_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

__all__ = ["ChangedCloneGate"]


def _validate_changed_scope_args(*, args: object) -> str | None:
    args_obj = cast("Any", args)
    console = cast("Any", cli_state.get_console())
    if args_obj.diff_against and args_obj.paths_from_git_diff:
        console.print(
            ui.fmt_contract_error(
                "Use --diff-against or --paths-from-git-diff, not both."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    if args_obj.paths_from_git_diff:
        args_obj.changed_only = True
        return str(args_obj.paths_from_git_diff)
    if args_obj.diff_against and not args_obj.changed_only:
        console.print(ui.fmt_contract_error("--diff-against requires --changed-only."))
        sys.exit(ExitCode.CONTRACT_ERROR)
    if args_obj.changed_only and not args_obj.diff_against:
        console.print(
            ui.fmt_contract_error(
                "--changed-only requires --diff-against or --paths-from-git-diff."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    return str(args_obj.diff_against) if args_obj.diff_against else None


def _normalize_changed_paths(
    *,
    root_path: Path,
    paths: Sequence[str],
) -> tuple[str, ...]:
    console = cast("Any", cli_state.get_console())
    normalized: set[str] = set()
    for raw_path in paths:
        candidate = raw_path.strip()
        if not candidate:
            continue
        candidate_path = Path(candidate)
        try:
            absolute_path = (
                candidate_path.resolve()
                if candidate_path.is_absolute()
                else (root_path / candidate_path).resolve()
            )
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(
                    f"Unable to resolve changed path '{candidate}': {exc}"
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        try:
            relative_path = absolute_path.relative_to(root_path)
        except ValueError:
            console.print(
                ui.fmt_contract_error(
                    f"Changed path '{candidate}' is outside the scan root."
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        cleaned = str(relative_path).replace("\\", "/").strip("/")
        if cleaned:
            normalized.add(cleaned)
    return tuple(sorted(normalized))


def _git_diff_changed_paths(*, root_path: Path, git_diff_ref: str) -> tuple[str, ...]:
    console = cast("Any", cli_state.get_console())
    try:
        validated_ref = validate_git_diff_ref(git_diff_ref)
    except ValueError as exc:
        console.print(ui.fmt_contract_error(str(exc)))
        sys.exit(ExitCode.CONTRACT_ERROR)
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", validated_ref, "--"],
            cwd=str(root_path),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        console.print(
            ui.fmt_contract_error(
                "Unable to resolve changed files from git diff ref "
                f"'{validated_ref}': {exc}"
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return _normalize_changed_paths(root_path=root_path, paths=lines)


def _path_matches(relative_path: str, changed_paths: Sequence[str]) -> bool:
    return any(
        relative_path == candidate or relative_path.startswith(candidate + "/")
        for candidate in changed_paths
    )


def _flatten_report_findings(
    report_document: Mapping[str, object],
) -> list[dict[str, object]]:
    findings = _as_mapping(report_document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clone_groups = _as_mapping(groups.get("clones"))
    return [
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(clone_groups.get("functions"))
        ],
        *[dict(_as_mapping(item)) for item in _as_sequence(clone_groups.get("blocks"))],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(clone_groups.get("segments"))
        ],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(
                _as_mapping(groups.get("structural")).get("groups")
            )
        ],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(_as_mapping(groups.get("dead_code")).get("groups"))
        ],
        *[
            dict(_as_mapping(item))
            for item in _as_sequence(_as_mapping(groups.get("design")).get("groups"))
        ],
    ]


def _finding_touches_changed_paths(
    finding: Mapping[str, object],
    *,
    changed_paths: Sequence[str],
) -> bool:
    for item in _as_sequence(finding.get("items")):
        relative_path = str(_as_mapping(item).get("relative_path", "")).strip()
        if relative_path and _path_matches(relative_path, changed_paths):
            return True
    return False


def _changed_clone_gate_from_report(
    report_document: Mapping[str, object],
    *,
    changed_paths: Sequence[str],
) -> ChangedCloneGate:
    findings = [
        finding
        for finding in _flatten_report_findings(report_document)
        if _finding_touches_changed_paths(finding, changed_paths=changed_paths)
    ]
    clone_findings = [
        finding
        for finding in findings
        if str(finding.get("family", "")).strip() == "clone"
        and str(finding.get("category", "")).strip() in {"function", "block"}
    ]
    new_func = frozenset(
        str(finding.get("id", ""))
        for finding in clone_findings
        if str(finding.get("category", "")).strip() == "function"
        and str(finding.get("novelty", "")).strip() == "new"
    )
    new_block = frozenset(
        str(finding.get("id", ""))
        for finding in clone_findings
        if str(finding.get("category", "")).strip() == "block"
        and str(finding.get("novelty", "")).strip() == "new"
    )
    findings_new = sum(
        1 for finding in findings if str(finding.get("novelty", "")).strip() == "new"
    )
    findings_known = sum(
        1 for finding in findings if str(finding.get("novelty", "")).strip() == "known"
    )
    return ChangedCloneGate(
        changed_paths=tuple(changed_paths),
        new_func=new_func,
        new_block=new_block,
        total_clone_groups=len(clone_findings),
        findings_total=len(findings),
        findings_new=findings_new,
        findings_known=findings_known,
    )

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

from ... import ui_messages as ui
from ...api.novelty import (
    CLONE_NOVELTY_KNOWN,
    CLONE_NOVELTY_NEW,
    CLONE_NOVELTY_UNAVAILABLE,
)
from ...contracts import GROUP_KEY_AUTHORITY, ExitCode
from ...utils import coerce as _coerce
from ...utils.finding_groups import (
    baseline_tracked_group_keys,
    flatten_finding_groups,
    groups_root_of_document,
)
from ...utils.git_diff import validate_git_diff_ref
from . import state as cli_state
from .attrs import bool_attr, optional_text_attr, set_bool_attr
from .types import ChangedCloneGate, require_status_console

_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence

__all__ = ["ChangedCloneGate"]


def _validate_changed_scope_args(*, args: object) -> str | None:
    console = require_status_console(cli_state.get_console())
    diff_against = optional_text_attr(args, "diff_against")
    paths_from_git_diff = optional_text_attr(args, "paths_from_git_diff")
    if bool_attr(args, "blast_radius"):
        return None
    if diff_against and paths_from_git_diff:
        console.print(
            ui.fmt_contract_error(
                "Use --diff-against or --paths-from-git-diff, not both."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    if paths_from_git_diff:
        set_bool_attr(args, "changed_only", True)
        return paths_from_git_diff
    if (
        diff_against
        and not bool_attr(args, "changed_only")
        and not bool_attr(args, "patch_verify")
    ):
        console.print(ui.fmt_contract_error("--diff-against requires --changed-only."))
        sys.exit(ExitCode.CONTRACT_ERROR)
    if bool_attr(args, "changed_only") and not diff_against:
        console.print(
            ui.fmt_contract_error(
                "--changed-only requires --diff-against or --paths-from-git-diff."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    return diff_against


def _normalize_changed_paths(
    *,
    root_path: Path,
    paths: Sequence[str],
) -> tuple[str, ...]:
    console = require_status_console(cli_state.get_console())
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
    console = require_status_console(cli_state.get_console())
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


def changed_scope_group_keys() -> tuple[str, ...]:
    """The family universe ``--changed-only`` counts.

    Deliberately not the full one: this gate has never counted the
    ``authority`` family, and ``ChangedCloneGate.findings_total`` is printed
    to the user. Widening it would move a published number, which is a
    contract decision and not a side effect of removing a duplicated walk --
    so the omission is stated here, as a named subset of the owner's universe,
    instead of being invisible inside a hand-written list. Derived on each
    call so the subset cannot outlive the universe it is taken from.
    """

    return baseline_tracked_group_keys(exclude=(GROUP_KEY_AUTHORITY,))


def _path_matches(relative_path: str, changed_paths: Sequence[str]) -> bool:
    return any(
        relative_path == candidate or relative_path.startswith(candidate + "/")
        for candidate in changed_paths
    )


def _flatten_report_findings(
    report_document: Mapping[str, object],
) -> list[dict[str, object]]:
    """The findings this gate counts, over its declared family subset."""

    return [
        dict(group)
        for group in flatten_finding_groups(
            groups_root_of_document(report_document),
            families=changed_scope_group_keys(),
        )
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
        and str(finding.get("novelty", "")).strip() == CLONE_NOVELTY_NEW
    )
    new_block = frozenset(
        str(finding.get("id", ""))
        for finding in clone_findings
        if str(finding.get("category", "")).strip() == "block"
        and str(finding.get("novelty", "")).strip() == CLONE_NOVELTY_NEW
    )
    # Every counter matches its own vocabulary value explicitly. The third
    # state is never derived as ``total - new - known``: a remainder would
    # silently absorb any future vocabulary value, and a new novelty value is
    # a contract change that must fail loudly, not be swallowed (`G4`).
    findings_new = sum(
        1
        for finding in findings
        if str(finding.get("novelty", "")).strip() == CLONE_NOVELTY_NEW
    )
    findings_known = sum(
        1
        for finding in findings
        if str(finding.get("novelty", "")).strip() == CLONE_NOVELTY_KNOWN
    )
    findings_unavailable = sum(
        1
        for finding in findings
        if str(finding.get("novelty", "")).strip() == CLONE_NOVELTY_UNAVAILABLE
    )
    return ChangedCloneGate(
        changed_paths=tuple(changed_paths),
        new_func=new_func,
        new_block=new_block,
        total_clone_groups=len(clone_findings),
        findings_total=len(findings),
        findings_new=findings_new,
        findings_known=findings_known,
        findings_unavailable=findings_unavailable,
    )

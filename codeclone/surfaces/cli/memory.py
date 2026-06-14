# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig, resolve_memory_config
from ...config.memory_defaults import DEFAULT_MEMORY_STATEMENT_PREVIEW_CHARS
from ...contracts import ExitCode
from ...memory.embedding import EmbeddingProvider, resolve_embedding_provider
from ...memory.exceptions import MemoryContractError, MemorySemanticUnavailableError
from ...memory.governance import approve_record, archive_record, reject_record
from ...memory.ingest import InitOptions
from ...memory.ingest.runner import run_memory_init
from ...memory.jobs import (
    execute_enqueue_projection_rebuild,
    execute_projection_rebuild_status,
    execute_run_projection_jobs_once,
)
from ...memory.models import MemoryProject, MemoryQuery
from ...memory.paths import normalize_memory_scope_path
from ...memory.project import resolve_memory_db_path, resolve_project_identity
from ...memory.retrieval import query_engineering_memory, query_records_for_repo_path
from ...memory.retrieval.semantic import semantic_search
from ...memory.semantic import (
    execute_semantic_index_rebuild,
    resolve_semantic_index,
)
from ...memory.semantic.models import SemanticSearchResult
from ...memory.semantic.rebuild_workflow import (
    RebuildSemanticIndexOkPayload,
    RebuildSemanticIndexSkippedPayload,
    RebuildSemanticIndexUnavailablePayload,
    execute_semantic_projection_probe,
)
from ...memory.sqlite_store import SqliteEngineeringMemoryStore
from ...memory.status_report import build_memory_status_report
from ...memory.trajectory.cli_render import (
    render_projection_run,
    render_trajectory_agents,
    render_trajectory_anomalies,
    render_trajectory_detail,
    render_trajectory_list,
    render_trajectory_search_results,
    render_trajectory_status,
)
from ...memory.trajectory.export import (
    export_trajectories_jsonl,
    resolve_export_output_path,
)
from ...memory.vacuum import run_memory_vacuum
from ...observability import (
    bootstrap,
    is_observability_enabled,
    operation,
    shutdown,
    span,
)
from .memory_analysis import load_report_for_memory_init
from .memory_render import (
    memory_console,
    render_coverage_report,
    render_draft_candidates,
    render_governance_result,
    render_init_note,
    render_init_result,
    render_path_results,
    render_search_results,
    render_stale_records,
    render_status_report,
    render_vacuum_report,
)
from .types import PrinterLike

_CLI_GOVERNANCE_BREAK_GLASS_FLAG = "--i-know-what-im-doing"
_CLI_GOVERNANCE_BREAK_GLASS_MESSAGE = (
    "Direct CLI memory governance is disabled by default. Use the IDE "
    "governance channel, or pass --i-know-what-im-doing for an explicit "
    "human break-glass action."
)


def _print_memory_contract_error(console: PrinterLike, exc: MemoryContractError) -> int:
    console.print(str(exc))
    return int(ExitCode.CONTRACT_ERROR)


def _normalize_memory_cli_path(console: PrinterLike, raw_path: str) -> str | None:
    try:
        return normalize_memory_scope_path(raw_path)
    except MemoryContractError as exc:
        _print_memory_contract_error(console, exc)
        return None


def memory_main(argv: list[str]) -> int:
    console = memory_console()
    parser = _build_parser()
    args = parser.parse_args(argv)
    root_path = Path(args.root).expanduser().resolve()
    if not root_path.is_dir():
        console.print(f"Repository root does not exist: {root_path}")
        return int(ExitCode.CONTRACT_ERROR)
    return _run_memory_with_observability(
        root_path=root_path,
        args=args,
        handler=lambda: _dispatch_memory_command(
            console=console, root_path=root_path, args=args
        ),
    )


def _memory_operation_name(args: argparse.Namespace) -> str:
    command = str(args.command)
    if command == "semantic":
        return f"cli.memory.semantic.{args.semantic_action}"
    if command == "trajectory":
        return f"cli.memory.trajectory.{args.trajectory_action}"
    if command == "jobs":
        return f"cli.memory.jobs.{args.jobs_action}"
    return f"cli.memory.{command}"


def _run_memory_with_observability(
    *,
    root_path: Path,
    args: argparse.Namespace,
    handler: Callable[[], int],
) -> int:
    from ...config.observability import resolve_observability_config

    config = resolve_observability_config()
    if not config.enabled:
        return handler()
    owns_observability = not is_observability_enabled()
    if owns_observability:
        bootstrap(config, root=root_path)
    try:
        with operation(name=_memory_operation_name(args), surface="cli"):
            return handler()
    finally:
        if owns_observability:
            shutdown()


def _dispatch_memory_command(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    if args.command == "status":
        return _render_status(console=console, root_path=root_path)
    if args.command == "init":
        return _run_init(console=console, root_path=root_path, args=args)
    if args.command == "for-path":
        return _run_for_path(console=console, root_path=root_path, args=args)
    if args.command == "search":
        return _run_search(console=console, root_path=root_path, args=args)
    if args.command == "stale":
        return _run_stale(console=console, root_path=root_path, args=args)
    if args.command == "vacuum":
        return _run_vacuum(console=console, root_path=root_path)
    if args.command == "coverage":
        return _run_coverage(console=console, root_path=root_path, args=args)
    if args.command == "review-candidates":
        return _run_review_candidates(console=console, root_path=root_path, args=args)
    if args.command == "approve":
        return _run_approve(console=console, root_path=root_path, args=args)
    if args.command == "reject":
        return _run_reject(console=console, root_path=root_path, args=args)
    if args.command == "archive":
        return _run_archive(console=console, root_path=root_path, args=args)
    if args.command == "semantic":
        return _run_semantic(console=console, root_path=root_path, args=args)
    if args.command == "trajectory":
        return _run_trajectory(console=console, root_path=root_path, args=args)
    if args.command == "jobs":
        return _run_jobs(console=console, root_path=root_path, args=args)
    return int(ExitCode.CONTRACT_ERROR)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeclone memory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def _add_root(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--root", default=".", help="Repository root path.")

    init_parser = subparsers.add_parser("init", help="Initialize engineering memory.")
    _add_root(init_parser)
    init_parser.add_argument("--dry-run", action="store_true")
    init_parser.add_argument("--refresh", action="store_true")
    init_parser.add_argument("--from-report", metavar="PATH")
    init_parser.add_argument("--no-docs", action="store_true")
    init_parser.add_argument("--no-tests", action="store_true")

    status_parser = subparsers.add_parser(
        "status",
        help="Show engineering memory status.",
    )
    _add_root(status_parser)

    for_path = subparsers.add_parser(
        "for-path", help="List memory records linked to a source path."
    )
    _add_root(for_path)
    for_path.add_argument("path", help="Repo-relative source file path.")
    for_path.add_argument("--limit", type=int, default=20)

    search_parser = subparsers.add_parser(
        "search",
        help="Search engineering memory records by keyword.",
    )
    _add_root(search_parser)
    search_parser.add_argument("query", help="Keyword query.")
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument(
        "--match",
        choices=("any", "all"),
        default="any",
        help="Match any token (default) or require all tokens.",
    )
    search_parser.add_argument(
        "--active-only",
        action="store_true",
        help="Exclude stale records from search results.",
    )
    search_parser.add_argument(
        "--semantic",
        action="store_true",
        help="Blend semantic proximity into ranking (requires the index).",
    )

    stale_parser = subparsers.add_parser(
        "stale",
        help="List stale engineering memory records.",
    )
    _add_root(stale_parser)
    stale_parser.add_argument("--limit", type=int, default=50)

    vacuum_parser = subparsers.add_parser(
        "vacuum",
        help="Purge expired stale/draft/rejected/archived records.",
    )
    _add_root(vacuum_parser)

    coverage_parser = subparsers.add_parser(
        "coverage",
        help="Show memory coverage for repo-relative paths.",
    )
    _add_root(coverage_parser)
    coverage_parser.add_argument(
        "paths",
        nargs="+",
        help="Repo-relative paths to inspect.",
    )

    review_parser = subparsers.add_parser(
        "review-candidates",
        help="List draft memory candidates awaiting review.",
    )
    _add_root(review_parser)
    review_parser.add_argument("--limit", type=int, default=50)

    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve a draft memory record.",
    )
    _add_root(approve_parser)
    approve_parser.add_argument("record_id")
    approve_parser.add_argument("--by", default="human")
    approve_parser.add_argument(_CLI_GOVERNANCE_BREAK_GLASS_FLAG, action="store_true")

    reject_parser = subparsers.add_parser(
        "reject",
        help="Reject a draft memory record.",
    )
    _add_root(reject_parser)
    reject_parser.add_argument("record_id")
    reject_parser.add_argument("--by", default="human")
    reject_parser.add_argument("--reason")
    reject_parser.add_argument(_CLI_GOVERNANCE_BREAK_GLASS_FLAG, action="store_true")

    archive_parser = subparsers.add_parser(
        "archive",
        help="Archive an active memory record.",
    )
    _add_root(archive_parser)
    archive_parser.add_argument("record_id")
    archive_parser.add_argument("--by", default="human")
    archive_parser.add_argument(_CLI_GOVERNANCE_BREAK_GLASS_FLAG, action="store_true")

    semantic_parser = subparsers.add_parser(
        "semantic",
        help="Semantic retrieval index (status / rebuild / search).",
    )
    semantic_sub = semantic_parser.add_subparsers(dest="semantic_action", required=True)
    sem_status = semantic_sub.add_parser("status", help="Show semantic index status.")
    _add_root(sem_status)
    sem_rebuild = semantic_sub.add_parser("rebuild", help="Rebuild the semantic index.")
    _add_root(sem_rebuild)
    sem_search = semantic_sub.add_parser(
        "search", help="Semantic free-text search over memory."
    )
    _add_root(sem_search)
    sem_search.add_argument("query", help="Free-text query.")
    sem_search.add_argument("--limit", type=int, default=10)
    sem_search.add_argument("--json", action="store_true", help="Emit results as JSON.")
    sem_probe = semantic_sub.add_parser(
        "probe",
        help="Measure semantic projection length distribution per lane.",
    )
    _add_root(sem_probe)
    sem_probe.add_argument(
        "--json", action="store_true", help="Emit probe payload as JSON."
    )

    trajectory_parser = subparsers.add_parser(
        "trajectory",
        help=(
            "Trajectory projections and analytics "
            "(status / rebuild / list / search / show / agents / "
            "anomalies / dashboard / export)."
        ),
    )
    trajectory_sub = trajectory_parser.add_subparsers(
        dest="trajectory_action",
        required=True,
    )
    traj_status = trajectory_sub.add_parser(
        "status",
        help="Show trajectory projection status.",
    )
    _add_root(traj_status)
    traj_rebuild = trajectory_sub.add_parser(
        "rebuild",
        help="Rebuild trajectory projections from audit event core.",
    )
    _add_root(traj_rebuild)
    traj_list = trajectory_sub.add_parser("list", help="List stored trajectories.")
    _add_root(traj_list)
    traj_list.add_argument("--limit", type=int, default=20)
    traj_search = trajectory_sub.add_parser(
        "search",
        help="Search stored trajectories by keyword.",
    )
    _add_root(traj_search)
    traj_search.add_argument("query", help="Keyword query.")
    traj_search.add_argument("--limit", type=int, default=10)
    traj_search.add_argument(
        "--match",
        choices=("any", "all"),
        default="any",
        help="Match any token (default) or require all tokens.",
    )
    traj_show = trajectory_sub.add_parser("show", help="Show one stored trajectory.")
    _add_root(traj_show)
    traj_show.add_argument("trajectory_id")
    traj_agents = trajectory_sub.add_parser(
        "agents",
        help="Aggregate trajectories by agent label.",
    )
    _add_root(traj_agents)
    traj_agents.add_argument(
        "--include-routine",
        action="store_true",
        help="Include routine analysis-only trajectories.",
    )
    traj_agents.add_argument("--json", action="store_true")
    traj_anomalies = trajectory_sub.add_parser(
        "anomalies",
        help="List trajectories with detected anomalies.",
    )
    _add_root(traj_anomalies)
    traj_anomalies.add_argument("--limit", type=int, default=25)
    traj_anomalies.add_argument(
        "--include-routine",
        action="store_true",
        help="Include routine analysis-only trajectories.",
    )
    traj_anomalies.add_argument("--json", action="store_true")
    traj_dashboard = trajectory_sub.add_parser(
        "dashboard",
        help="Combined trajectory status, agents, and anomalies summary.",
    )
    _add_root(traj_dashboard)
    traj_dashboard.add_argument("--limit", type=int, default=25)
    traj_dashboard.add_argument(
        "--include-routine",
        action="store_true",
        help="Include routine analysis-only trajectories.",
    )
    traj_dashboard.add_argument("--json", action="store_true")
    traj_export = trajectory_sub.add_parser(
        "export",
        help="Export trajectories to local JSONL (disabled by default).",
    )
    _add_root(traj_export)
    traj_export.add_argument(
        "--profile",
        required=True,
        help="Export profile name (for example agent-change-control-v1).",
    )
    traj_export.add_argument(
        "--out",
        required=True,
        help="Output JSONL path (repo-relative or absolute with --allow-external-out).",
    )
    traj_export.add_argument(
        "--allow-external-out",
        action="store_true",
        help="Allow writing outside the repository root.",
    )
    traj_export.add_argument(
        "--force",
        action="store_true",
        help="Run export even when trajectory_export_enabled=false.",
    )
    traj_export.add_argument("--json", action="store_true", help="Emit manifest JSON.")

    jobs_parser = subparsers.add_parser(
        "jobs",
        help="Projection rebuild jobs (status / enqueue / run-once / list).",
    )
    jobs_sub = jobs_parser.add_subparsers(dest="jobs_action", required=True)
    jobs_status = jobs_sub.add_parser(
        "status",
        help="Show projection rebuild job status.",
    )
    _add_root(jobs_status)
    jobs_enqueue = jobs_sub.add_parser(
        "enqueue",
        help="Enqueue a projection rebuild bundle job.",
    )
    _add_root(jobs_enqueue)
    jobs_enqueue.add_argument(
        "--force",
        action="store_true",
        help="Enqueue even when policy is off or stimulus unchanged.",
    )
    jobs_enqueue.add_argument(
        "--no-spawn",
        action="store_true",
        help="Do not spawn a background worker process.",
    )
    jobs_run = jobs_sub.add_parser(
        "run-once",
        help="Claim and run one pending projection rebuild job.",
    )
    _add_root(jobs_run)
    jobs_run.add_argument(
        "--not-before",
        dest="not_before",
        default=None,
        help=(
            "ISO-8601 UTC deadline to defer the run until before loading the "
            "embedding model (coalesced trailing-edge flush)."
        ),
    )
    jobs_list = jobs_sub.add_parser("list", help="List recent projection jobs.")
    _add_root(jobs_list)
    jobs_list.add_argument("--limit", type=int, default=20)
    jobs_list.add_argument("--json", action="store_true")

    return parser


def _render_status(*, console: PrinterLike, root_path: Path) -> int:
    config = resolve_memory_config(root_path)
    db_path = resolve_memory_db_path(root_path, config)
    report = build_memory_status_report(
        root_path=root_path,
        db_path=db_path,
        backend=config.backend,
    )
    render_status_report(console=console, report=report)
    return int(ExitCode.SUCCESS)


def _run_init(
    *,
    console: PrinterLike,
    root_path: Path,
    args: argparse.Namespace,
) -> int:
    try:
        loaded = load_report_for_memory_init(
            root_path=root_path,
            from_report=Path(args.from_report) if args.from_report else None,
        )
    except Exception as exc:
        console.print(f"Unable to load analysis report for memory init: {exc}")
        return int(ExitCode.CONTRACT_ERROR)

    if loaded.rejected_cache_reason:
        render_init_note(
            console=console,
            message=(
                "cached report rejected; running fresh analysis "
                f"({loaded.rejected_cache_reason})"
            ),
        )
    elif loaded.source == "fresh_analysis":
        render_init_note(
            console=console,
            message="no trusted cached report; running fresh analysis",
        )
    elif loaded.source == "trusted_cache":
        render_init_note(console=console, message="reusing trusted cached report")

    options = InitOptions(
        dry_run=bool(args.dry_run),
        refresh=bool(args.refresh),
        include_docs=not args.no_docs,
        include_tests=not args.no_tests,
    )
    try:
        result = run_memory_init(
            root_path=root_path,
            report_document=loaded.document,
            options=options,
        )
    except Exception as exc:
        console.print(f"Memory init failed: {exc}")
        return int(ExitCode.INTERNAL_ERROR)

    render_init_result(
        console=console,
        dry_run=bool(result.dry_run),
        project_id=result.project_id,
        db_path=str(result.db_path) if result.db_path else None,
        analysis_fingerprint=result.analysis_fingerprint,
        stats=result.stats,
        planned_counts=result.planned_counts,
    )
    return int(ExitCode.SUCCESS)


def _run_for_path(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    rel_path = _normalize_memory_cli_path(console, args.path)
    if rel_path is None:
        return int(ExitCode.CONTRACT_ERROR)
    try:
        store, _config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        records = query_records_for_repo_path(
            store,
            project_id=project.id,
            rel_path=rel_path,
            limit=max(1, int(args.limit)),
        )
    finally:
        store.close()

    render_path_results(console=console, rel_path=rel_path, records=records)
    return int(ExitCode.SUCCESS)


def _run_search(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    semantic = bool(args.semantic)
    index = resolve_semantic_index(config.semantic) if semantic else None
    provider: EmbeddingProvider | None = None
    semantic_reason: str | None = None
    if semantic:
        try:
            provider = resolve_embedding_provider(config.semantic)
        except MemorySemanticUnavailableError as exc:
            semantic_reason = str(exc)
    try:
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root_path,
            backend=config.backend,
            db_path=resolve_memory_db_path(root_path, config),
            mode="search",
            query=str(args.query),
            filters={"match_mode": str(args.match)},
            max_results=max(1, int(args.limit)),
            include_stale=not bool(args.active_only),
            semantic=semantic,
            semantic_index=index,
            embedding_provider=provider,
            provider_label=config.semantic.embedding_provider,
            semantic_reason=semantic_reason,
        )
    finally:
        store.close()

    payload = result.get("payload")
    if not isinstance(payload, dict):
        console.print("Memory search returned an unexpected payload.")
        return int(ExitCode.INTERNAL_ERROR)
    records = payload.get("records")
    if not isinstance(records, list):
        records = []
    typed_records = [item for item in records if isinstance(item, dict)]
    render_search_results(console=console, query=str(args.query), records=typed_records)
    _print_semantic_advisory(console, result.get("semantic"))
    return int(ExitCode.SUCCESS)


def _print_semantic_advisory(console: PrinterLike, semantic: object) -> None:
    if not isinstance(semantic, dict):
        return
    if semantic.get("used"):
        provider = str(semantic.get("provider") or "")
        quality = (
            "diagnostic, NOT semantic-quality" if provider == "diagnostic" else provider
        )
        console.print(f"semantic: on ({quality})", markup=False)
    else:
        console.print(f"semantic: off ({semantic.get('reason')})", markup=False)


def _open_store(
    root_path: Path,
) -> tuple[SqliteEngineeringMemoryStore, MemoryConfig, MemoryProject]:
    config = resolve_memory_config(root_path)
    db_path = resolve_memory_db_path(root_path, config)
    if not db_path.exists():
        raise FileNotFoundError(str(db_path))
    project = resolve_project_identity(root_path)
    return SqliteEngineeringMemoryStore(db_path), config, project


def _run_stale(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root_path,
            backend=config.backend,
            db_path=resolve_memory_db_path(root_path, config),
            mode="stale",
            max_results=max(1, int(args.limit)),
        )
    finally:
        store.close()
    payload = result.get("payload")
    records = payload.get("records") if isinstance(payload, dict) else None
    typed_records = [item for item in (records or []) if isinstance(item, dict)]
    render_stale_records(console=console, records=typed_records)
    return int(ExitCode.SUCCESS)


def _run_vacuum(*, console: PrinterLike, root_path: Path) -> int:
    try:
        store, config, _project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        report = run_memory_vacuum(store, config)
    finally:
        store.close()
    render_vacuum_report(console=console, report=report)
    return int(ExitCode.SUCCESS)


def _run_coverage(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    from ...memory.coverage import compute_scope_coverage

    try:
        store, _config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        report = compute_scope_coverage(
            store,
            project_id=project.id,
            scope_paths=args.paths,
        )
    except MemoryContractError as exc:
        return _print_memory_contract_error(console, exc)
    finally:
        store.close()
    render_coverage_report(console=console, report=report)
    return int(ExitCode.SUCCESS)


def _run_review_candidates(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, _config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        records = store.query_records(
            MemoryQuery(
                project_id=project.id,
                statuses=("draft",),
                limit=max(1, int(args.limit)),
            )
        )
    finally:
        store.close()
    render_draft_candidates(console=console, records=records)
    return int(ExitCode.SUCCESS)


def _run_approve(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    if not _confirm_cli_governance_break_glass(console, args):
        return int(ExitCode.CONTRACT_ERROR)
    try:
        store, _config, _project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        record = approve_record(
            store,
            record_id=str(args.record_id),
            approved_by=str(args.by),
        )
    except Exception as exc:
        console.print(f"Approve failed: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    finally:
        store.close()
    render_governance_result(
        console=console,
        action="approved",
        record_id=record.id,
        detail=f"Approved {record.id} -> active",
    )
    return int(ExitCode.SUCCESS)


def _run_reject(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    if not _confirm_cli_governance_break_glass(console, args):
        return int(ExitCode.CONTRACT_ERROR)
    try:
        store, _config, _project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        record = reject_record(
            store,
            record_id=str(args.record_id),
            rejected_by=str(args.by),
            reason=args.reason,
        )
    except Exception as exc:
        console.print(f"Reject failed: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    finally:
        store.close()
    render_governance_result(
        console=console,
        action="rejected",
        record_id=record.id,
        detail=f"Rejected {record.id}",
    )
    return int(ExitCode.SUCCESS)


def _run_archive(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    if not _confirm_cli_governance_break_glass(console, args):
        return int(ExitCode.CONTRACT_ERROR)
    try:
        store, _config, _project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        record = archive_record(
            store,
            record_id=str(args.record_id),
            archived_by=str(args.by),
        )
    except Exception as exc:
        console.print(f"Archive failed: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    finally:
        store.close()
    render_governance_result(
        console=console,
        action="archived",
        record_id=record.id,
        detail=f"Archived {record.id}",
    )
    return int(ExitCode.SUCCESS)


def _run_trajectory(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    action = str(args.trajectory_action)
    if action == "status":
        return _run_trajectory_status(console=console, root_path=root_path)
    if action == "rebuild":
        return _run_trajectory_rebuild(console=console, root_path=root_path)
    if action == "list":
        return _run_trajectory_list(console=console, root_path=root_path, args=args)
    if action == "search":
        return _run_trajectory_search(console=console, root_path=root_path, args=args)
    if action == "agents":
        return _run_trajectory_agents(console=console, root_path=root_path, args=args)
    if action == "anomalies":
        return _run_trajectory_anomalies(
            console=console, root_path=root_path, args=args
        )
    if action == "dashboard":
        return _run_trajectory_dashboard(
            console=console, root_path=root_path, args=args
        )
    if action == "export":
        return _run_trajectory_export(console=console, root_path=root_path, args=args)
    return _run_trajectory_show(console=console, root_path=root_path, args=args)


def _run_trajectory_status(*, console: PrinterLike, root_path: Path) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        count = store.count_trajectories(project_id=project.id)
        latest = store.latest_trajectory_projection_run(project_id=project.id)
    finally:
        store.close()
    render_trajectory_status(
        console=console,
        enabled=config.trajectories_enabled,
        count=count,
        latest_run=latest,
    )
    return int(ExitCode.SUCCESS)


def _run_trajectory_rebuild(*, console: PrinterLike, root_path: Path) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    if not config.trajectories_enabled:
        store.close()
        console.print("Trajectory projection is disabled.")
        return int(ExitCode.CONTRACT_ERROR)
    audit_db_path = resolve_audit_path(root_path=root_path, value=DEFAULT_AUDIT_PATH)
    try:
        result = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root_path,
            audit_db_path=audit_db_path,
        )
    except Exception as exc:
        console.print(f"Trajectory rebuild failed: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    finally:
        store.close()
    render_projection_run(console=console, run=result.run)
    return int(ExitCode.SUCCESS)


def _run_trajectory_list(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, _config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        items = store.list_trajectories(
            project_id=project.id,
            limit=max(1, int(args.limit)),
        )
    finally:
        store.close()
    render_trajectory_list(console=console, items=items)
    return int(ExitCode.SUCCESS)


def _run_trajectory_search(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root_path,
            backend=config.backend,
            db_path=resolve_memory_db_path(root_path, config),
            mode="trajectory_search",
            query=str(args.query),
            filters={"match_mode": str(args.match)},
            max_results=max(1, int(args.limit)),
        )
    finally:
        store.close()
    payload = result.get("payload")
    trajectories = payload.get("trajectories") if isinstance(payload, dict) else None
    typed = [item for item in (trajectories or []) if isinstance(item, dict)]
    render_trajectory_search_results(
        console=console,
        query=str(args.query),
        trajectories=typed,
    )
    return int(ExitCode.SUCCESS)


def _trajectory_query_filters(args: argparse.Namespace) -> dict[str, object] | None:
    if bool(getattr(args, "include_routine", False)):
        return {"include_routine": True}
    return None


def _run_trajectory_agents(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root_path,
            backend=config.backend,
            db_path=resolve_memory_db_path(root_path, config),
            mode="trajectory_agents",
            filters=_trajectory_query_filters(args),
        )
    finally:
        store.close()
    payload = result.get("payload")
    if not isinstance(payload, dict):
        console.print("Unexpected trajectory agents payload.")
        return int(ExitCode.INTERNAL_ERROR)
    if bool(getattr(args, "json", False)):
        console.print(json.dumps(payload, indent=2, sort_keys=True))
        return int(ExitCode.SUCCESS)
    render_trajectory_agents(console=console, payload=payload)
    return int(ExitCode.SUCCESS)


def _run_trajectory_anomalies(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root_path,
            backend=config.backend,
            db_path=resolve_memory_db_path(root_path, config),
            mode="trajectory_anomalies",
            filters=_trajectory_query_filters(args),
            max_results=max(1, int(args.limit)),
        )
    finally:
        store.close()
    payload = result.get("payload")
    if not isinstance(payload, dict):
        console.print("Unexpected trajectory anomalies payload.")
        return int(ExitCode.INTERNAL_ERROR)
    if bool(getattr(args, "json", False)):
        console.print(json.dumps(payload, indent=2, sort_keys=True))
        return int(ExitCode.SUCCESS)
    render_trajectory_anomalies(console=console, payload=payload)
    return int(ExitCode.SUCCESS)


def _run_trajectory_dashboard(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root_path,
            backend=config.backend,
            db_path=resolve_memory_db_path(root_path, config),
            mode="trajectory_dashboard",
            filters=_trajectory_query_filters(args),
            max_results=max(1, int(args.limit)),
        )
    finally:
        store.close()
    payload = result.get("payload")
    if not isinstance(payload, dict):
        console.print("Unexpected trajectory dashboard payload.")
        return int(ExitCode.INTERNAL_ERROR)
    if bool(getattr(args, "json", False)):
        console.print(json.dumps(payload, indent=2, sort_keys=True))
        return int(ExitCode.SUCCESS)
    status = payload.get("status")
    if isinstance(status, dict):
        latest = status.get("latest_projection")
        render_trajectory_status(
            console=console,
            enabled=config.trajectories_enabled,
            count=int(status.get("trajectory_count", 0)),
            latest_run=None,
        )
        if isinstance(latest, dict) and latest.get("finished_at_utc"):
            console.print(
                f"  latest projection finished: {latest.get('finished_at_utc')}",
                markup=False,
            )
    agents = payload.get("agents")
    if isinstance(agents, dict):
        console.print("")
        render_trajectory_agents(console=console, payload=agents)
    anomalies = payload.get("anomalies")
    if isinstance(anomalies, dict):
        console.print("")
        render_trajectory_anomalies(console=console, payload=anomalies)
    return int(ExitCode.SUCCESS)


def _run_trajectory_show(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, _config, _project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        trajectory = store.find_trajectory(str(args.trajectory_id))
    finally:
        store.close()
    if trajectory is None:
        console.print(f"Trajectory not found: {args.trajectory_id}")
        return int(ExitCode.CONTRACT_ERROR)
    render_trajectory_detail(console=console, trajectory=trajectory)
    return int(ExitCode.SUCCESS)


def _run_trajectory_export(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        store, config, project = _open_store(root_path)
    except FileNotFoundError as exc:
        console.print(f"Engineering memory database not found: {exc}")
        return int(ExitCode.CONTRACT_ERROR)
    try:
        output_path = resolve_export_output_path(
            root_path=root_path,
            raw_path=str(args.out),
            allow_external_out=bool(args.allow_external_out),
        )
        result = export_trajectories_jsonl(
            store=store,
            project=project,
            root_path=root_path,
            config=config,
            profile_name=str(args.profile),
            output_path=output_path,
            force_enabled=bool(args.force),
        )
    except MemoryContractError as exc:
        console.print(str(exc))
        return int(ExitCode.CONTRACT_ERROR)
    finally:
        store.close()
    if bool(args.json):
        console.print(json.dumps(result.manifest, sort_keys=True, indent=2))
    else:
        console.print(
            "Trajectory export complete: "
            f"{result.records_written} record(s) -> {result.output_path}"
        )
    return int(ExitCode.SUCCESS)


def _run_jobs(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    action = str(args.jobs_action)
    if action == "status":
        return _run_jobs_status(console=console, root_path=root_path)
    if action == "enqueue":
        return _run_jobs_enqueue(console=console, root_path=root_path, args=args)
    if action == "run-once":
        return _run_jobs_run_once(console=console, root_path=root_path, args=args)
    return _run_jobs_list(console=console, root_path=root_path, args=args)


def _run_jobs_json(
    *,
    console: PrinterLike,
    root_path: Path,
    action: Callable[[], dict[str, object]],
    fail_on: frozenset[str] = frozenset({"failed"}),
) -> int:
    try:
        payload = action()
    except MemoryContractError as exc:
        return _print_memory_contract_error(console, exc)
    console.print(json.dumps(payload, sort_keys=True, indent=2))
    if str(payload.get("status", "")) in fail_on:
        return int(ExitCode.CONTRACT_ERROR)
    return int(ExitCode.SUCCESS)


def _run_jobs_status(*, console: PrinterLike, root_path: Path) -> int:
    return _run_jobs_json(
        console=console,
        root_path=root_path,
        action=lambda: execute_projection_rebuild_status(root_path=root_path),
    )


def _run_jobs_enqueue(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    return _run_jobs_json(
        console=console,
        root_path=root_path,
        action=lambda: execute_enqueue_projection_rebuild(
            root_path=root_path,
            trigger="cli",
            force=bool(args.force),
            spawn_worker=not bool(args.no_spawn),
        ),
    )


def _run_jobs_run_once(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    not_before = getattr(args, "not_before", None)
    return _run_jobs_json(
        console=console,
        root_path=root_path,
        action=lambda: execute_run_projection_jobs_once(
            root_path=root_path, not_before_utc=not_before
        ),
        fail_on=frozenset({"failed"}),
    )


def _run_jobs_list(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    try:
        payload = execute_projection_rebuild_status(
            root_path=root_path,
            limit=max(1, int(args.limit)),
        )
    except MemoryContractError as exc:
        return _print_memory_contract_error(console, exc)
    exit_code = int(ExitCode.SUCCESS)
    if bool(args.json):
        console.print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        jobs = payload.get("jobs")
        if not isinstance(jobs, list) or not jobs:
            console.print("No projection rebuild jobs recorded.")
        else:
            for job in jobs:
                if isinstance(job, dict):
                    console.print(
                        f"{job.get('id')} {job.get('status')} "
                        f"trigger={job.get('trigger')} "
                        f"requested={job.get('requested_at_utc')}"
                    )
    return exit_code


def _confirm_cli_governance_break_glass(
    console: PrinterLike,
    args: argparse.Namespace,
) -> bool:
    if bool(getattr(args, "i_know_what_im_doing", False)):
        return True
    console.print(_CLI_GOVERNANCE_BREAK_GLASS_MESSAGE)
    return False


def _semantic_unavailable(console: PrinterLike, message: str) -> int:
    console.print(message)
    console.print(
        "Enable memory.semantic and install: pip install 'codeclone[semantic-lancedb]'",
        markup=False,
    )
    return int(ExitCode.CONTRACT_ERROR)


def _resolve_semantic_provider_or_fail(
    console: PrinterLike, config: MemoryConfig
) -> EmbeddingProvider | int:
    try:
        return resolve_embedding_provider(config.semantic)
    except MemorySemanticUnavailableError as exc:
        return _semantic_unavailable(
            console, f"Semantic embedding provider unavailable: {exc}"
        )


def _run_semantic(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    action = str(args.semantic_action)
    if action == "status":
        return _run_semantic_status(console=console, root_path=root_path)
    if action == "rebuild":
        return _run_semantic_rebuild(console=console, root_path=root_path)
    if action == "probe":
        return _run_semantic_probe(console=console, root_path=root_path, args=args)
    return _run_semantic_search(console=console, root_path=root_path, args=args)


def _run_semantic_status(*, console: PrinterLike, root_path: Path) -> int:
    config = resolve_memory_config(root_path)
    status = resolve_semantic_index(config.semantic).status()
    provider_status = "available"
    provider_reason: str | None = None
    if config.semantic.enabled:
        try:
            provider = resolve_embedding_provider(config.semantic)
        except MemorySemanticUnavailableError as exc:
            provider_status = "unavailable"
            provider_reason = str(exc)
        else:
            provider_status = provider.model_id
    state = (
        "available" if status.available and provider_reason is None else "unavailable"
    )
    console.print(f"semantic index: {state}")
    for reason in (status.reason, provider_reason):
        if reason:
            console.print(f"  reason: {reason}")
    console.print(f"  enabled: {config.semantic.enabled}")
    console.print(
        f"  embedding: {config.semantic.embedding_provider} "
        f"(dim {config.semantic.dimension})"
    )
    if config.semantic.enabled:
        console.print(f"  provider: {provider_status}", markup=False)
    return int(ExitCode.SUCCESS)


def _run_semantic_rebuild(*, console: PrinterLike, root_path: Path) -> int:
    config = resolve_memory_config(root_path)
    try:
        payload = execute_semantic_index_rebuild(root_path=root_path, config=config)
    except MemoryContractError as exc:
        console.print(str(exc))
        console.print("Run: codeclone memory init")
        return int(ExitCode.CONTRACT_ERROR)
    status = payload["status"]
    if status == "ok":
        ok = cast(RebuildSemanticIndexOkPayload, payload)
        console.print(
            f"Rebuilt semantic index: {ok['indexed']} indexed, {ok['deleted']} pruned."
        )
        console.print(
            "  embedded: "
            f"{ok['embedded']}, skipped unchanged: {ok['skipped_unchanged']}"
        )
        for name, count in sorted(ok["by_source"].items()):
            console.print(f"  {name}: {count}")
        return int(ExitCode.SUCCESS)
    if status == "skipped":
        skipped = cast(RebuildSemanticIndexSkippedPayload, payload)
        return _semantic_unavailable(
            console, f"Semantic indexing is disabled ({skipped['reason']})."
        )
    unavailable = cast(RebuildSemanticIndexUnavailablePayload, payload)
    return _semantic_unavailable(
        console, f"Semantic index rebuild unavailable: {unavailable['reason']}."
    )


def _run_semantic_probe(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    config = resolve_memory_config(root_path)
    try:
        payload = execute_semantic_projection_probe(root_path=root_path, config=config)
    except MemoryContractError as exc:
        console.print(str(exc))
        console.print("Run: codeclone memory init")
        return int(ExitCode.CONTRACT_ERROR)
    if args.json:
        console.print(json.dumps(payload, indent=2, sort_keys=True))
        return int(ExitCode.SUCCESS)
    if payload.get("status") in {"skipped", "unavailable"}:
        reason = str(payload.get("reason", "unknown"))
        return _semantic_unavailable(
            console,
            f"Semantic projection probe unavailable: {reason}.",
        )
    lanes_obj = payload.get("lanes")
    if not isinstance(lanes_obj, dict):
        return _semantic_unavailable(
            console, "Semantic projection probe returned invalid payload."
        )
    lanes = lanes_obj
    console.print("Semantic projection probe:")
    console.print(f"  estimator: {payload.get('estimator')}")
    console.print(f"  model_max_tokens: {payload.get('model_max_tokens')}")
    for lane in ("memory", "audit", "trajectory"):
        stats = lanes.get(lane, {})
        if not stats:
            continue
        chars = stats.get("chars", {})
        tokens = stats.get("tokens", {})
        overflow = stats.get("token_overflow", {})
        console.print(f"  {lane}: {stats.get('documents', 0)} documents")
        console.print(
            "    chars p50/p95/max: "
            f"{chars.get('p50')}/{chars.get('p95')}/{chars.get('max')}"
        )
        console.print(
            "    tokens p50/p95/max: "
            f"{tokens.get('p50')}/{tokens.get('p95')}/{tokens.get('max')}"
        )
        console.print(
            "    over_model_limit: "
            f"{overflow.get('over_model_limit')} "
            f"(max_overflow={overflow.get('max_overflow_tokens')})"
        )
    return int(ExitCode.SUCCESS)


def _run_semantic_search(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    config = resolve_memory_config(root_path)
    provider = _resolve_semantic_provider_or_fail(console, config)
    if isinstance(provider, int):
        return provider
    index = resolve_semantic_index(config.semantic)
    status = index.status()
    if not status.available:
        return _semantic_unavailable(
            console, f"Semantic search unavailable: {status.reason}."
        )
    db_path = resolve_memory_db_path(root_path, config)
    store = SqliteEngineeringMemoryStore(db_path) if db_path.exists() else None
    from ...memory.semantic import close_semantic_index

    try:
        with span(name="memory.semantic.search"):
            results = semantic_search(
                index=index,
                provider=provider,
                store=store,
                audit_db_path=resolve_audit_path(
                    root_path=root_path, value=DEFAULT_AUDIT_PATH
                ),
                query=str(args.query),
                limit=max(1, int(args.limit)),
                preview_chars=DEFAULT_MEMORY_STATEMENT_PREVIEW_CHARS,
            )
    except MemorySemanticUnavailableError as exc:
        # The embedding model loads lazily, so an unavailable model surfaces at
        # the first embed rather than at provider resolution.
        return _semantic_unavailable(console, f"Semantic search unavailable: {exc}.")
    finally:
        close_semantic_index(index)
        if store is not None:
            store.close()
    if bool(args.json):
        return _render_semantic_json(
            console=console, query=str(args.query), config=config, results=results
        )
    return _render_semantic_text(
        console=console,
        query=str(args.query),
        config=config,
        provider=provider,
        results=results,
    )


def _provider_note(config: MemoryConfig, provider: EmbeddingProvider) -> str:
    kind = config.semantic.embedding_provider
    quality = "diagnostic, NOT semantic-quality" if kind == "diagnostic" else kind
    return f"provider: {provider.model_id} ({quality})"


def _render_semantic_text(
    *,
    console: PrinterLike,
    query: str,
    config: MemoryConfig,
    provider: EmbeddingProvider,
    results: list[SemanticSearchResult],
) -> int:
    console.print(f"Semantic matches for: {query}", markup=False)
    console.print(_provider_note(config, provider), markup=False)
    if not results:
        console.print("  (no matches)")
        return int(ExitCode.SUCCESS)
    for rank, result in enumerate(results, start=1):
        console.print(
            f"{rank}. {result.source}/{result.source_id}  score={result.score:.3f}",
            markup=False,
        )
        meta = " · ".join(
            part for part in (result.kind, result.status, result.confidence) if part
        )
        console.print(f"   {meta}", markup=False)
        if result.subject_path:
            console.print(f"   subject: {result.subject_path}", markup=False)
        console.print(f'   "{result.preview}"', markup=False)
    return int(ExitCode.SUCCESS)


def _render_semantic_json(
    *,
    console: PrinterLike,
    query: str,
    config: MemoryConfig,
    results: list[SemanticSearchResult],
) -> int:
    import json

    kind = config.semantic.embedding_provider
    payload = {
        "query": query,
        "semantic": {"provider": kind, "diagnostic": kind == "diagnostic"},
        "results": [result.model_dump() for result in results],
    }
    console.print(json.dumps(payload, indent=2), markup=False)
    return int(ExitCode.SUCCESS)


__all__ = ["memory_main"]

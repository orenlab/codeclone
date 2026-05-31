# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from ...config.memory import MemoryConfig, resolve_memory_config
from ...contracts import ExitCode
from ...memory.governance import approve_record, archive_record, reject_record
from ...memory.ingest import InitOptions
from ...memory.ingest.runner import run_memory_init
from ...memory.models import MemoryProject, MemoryQuery
from ...memory.paths import normalize_repo_path
from ...memory.project import resolve_memory_db_path, resolve_project_identity
from ...memory.retrieval import query_engineering_memory, query_records_for_repo_path
from ...memory.sqlite_store import SqliteEngineeringMemoryStore
from ...memory.status_report import build_memory_status_report
from ...memory.vacuum import run_memory_vacuum
from .console import PlainConsole
from .memory_analysis import load_report_for_memory_init
from .types import PrinterLike


def memory_main(argv: list[str]) -> int:
    console = cast(PrinterLike, PlainConsole())
    parser = _build_parser()
    args = parser.parse_args(argv)
    root_path = Path(args.root).expanduser().resolve()
    if not root_path.is_dir():
        console.print(f"Repository root does not exist: {root_path}")
        return int(ExitCode.CONTRACT_ERROR)
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
    parser.print_help()
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
    search_parser.add_argument("--include-stale", action="store_true")

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

    reject_parser = subparsers.add_parser(
        "reject",
        help="Reject a draft memory record.",
    )
    _add_root(reject_parser)
    reject_parser.add_argument("record_id")
    reject_parser.add_argument("--by", default="human")
    reject_parser.add_argument("--reason")

    archive_parser = subparsers.add_parser(
        "archive",
        help="Archive an active memory record.",
    )
    _add_root(archive_parser)
    archive_parser.add_argument("record_id")
    archive_parser.add_argument("--by", default="human")

    return parser


def _render_status(*, console: PrinterLike, root_path: Path) -> int:
    config = resolve_memory_config(root_path)
    db_path = resolve_memory_db_path(root_path, config)
    report = build_memory_status_report(
        root_path=root_path,
        db_path=db_path,
        backend=config.backend,
    )
    console.print("Engineering Memory status")
    console.print(f"  root:             {report.project_root}")
    console.print(f"  backend:          {report.backend}")
    console.print(f"  db:               {report.db_path}")
    console.print(f"  db_exists:        {report.db_exists}")
    console.print(f"  schema_version:   {report.schema_version or 'n/a'}")
    console.print(f"  project_id:       {report.project_id or 'n/a'}")
    console.print(f"  analysis_fp:      {report.last_analysis_fingerprint or 'n/a'}")
    console.print(f"  last_init_run_id: {report.last_init_run_id or 'n/a'}")
    console.print(f"  record_count:     {report.record_count}")
    if report.records_by_type:
        console.print("  records_by_type:")
        for key, count in sorted(report.records_by_type.items()):
            console.print(f"    {key}: {count}")
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
        console.print(
            "  note: cached report rejected; running fresh analysis "
            f"({loaded.rejected_cache_reason})"
        )
    elif loaded.source == "fresh_analysis":
        console.print("  note: no trusted cached report; running fresh analysis")
    elif loaded.source == "trusted_cache":
        console.print("  note: reusing trusted cached report")

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

    if result.dry_run:
        console.print("Engineering Memory init dry-run")
        console.print(f"  project_id:          {result.project_id}")
        console.print(f"  analysis_fingerprint:{result.analysis_fingerprint}")
        console.print("  planned records:")
        for key, count in sorted(result.planned_counts.items()):
            console.print(f"    {key}: {count}")
        return int(ExitCode.SUCCESS)

    console.print("Engineering Memory initialized")
    console.print(f"  project_id: {result.project_id}")
    console.print(f"  db:         {result.db_path}")
    if result.stats:
        console.print("  upsert stats:")
        for key, count in sorted(result.stats.items()):
            console.print(f"    {key}: {count}")
    if result.planned_counts:
        console.print("  record types:")
        for key, count in sorted(result.planned_counts.items()):
            console.print(f"    {key}: {count}")
    return int(ExitCode.SUCCESS)


def _run_for_path(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    rel_path = normalize_repo_path(args.path)
    config = resolve_memory_config(root_path)
    db_path = resolve_memory_db_path(root_path, config)
    if not db_path.exists():
        console.print(f"Engineering memory database not found: {db_path}")
        console.print("Run: codeclone memory init")
        return int(ExitCode.CONTRACT_ERROR)

    project = resolve_project_identity(root_path)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        records = query_records_for_repo_path(
            store,
            project_id=project.id,
            rel_path=rel_path,
            limit=max(1, int(args.limit)),
        )
    finally:
        store.close()

    console.print(f"Engineering Memory for path: {rel_path}")
    if not records:
        console.print("  (no records)")
        return int(ExitCode.SUCCESS)
    for record in records:
        console.print(f"  - [{record.type}/{record.status}] {record.statement}")
    return int(ExitCode.SUCCESS)


def _run_search(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    config = resolve_memory_config(root_path)
    db_path = resolve_memory_db_path(root_path, config)
    if not db_path.exists():
        console.print(f"Engineering memory database not found: {db_path}")
        console.print("Run: codeclone memory init")
        return int(ExitCode.CONTRACT_ERROR)

    project = resolve_project_identity(root_path)
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        result = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=root_path,
            backend=config.backend,
            db_path=db_path,
            mode="search",
            query=str(args.query),
            max_results=max(1, int(args.limit)),
            include_stale=bool(args.include_stale),
        )
    finally:
        store.close()

    payload = result.get("payload")
    if not isinstance(payload, dict):
        console.print("Memory search returned an unexpected payload.")
        return int(ExitCode.INTERNAL_ERROR)
    records = payload.get("records")
    console.print(f"Engineering Memory search: {args.query!r}")
    if not isinstance(records, list) or not records:
        console.print("  (no records)")
        return int(ExitCode.SUCCESS)
    for item in records:
        if not isinstance(item, dict):
            continue
        record_type = item.get("type", "?")
        status = item.get("status", "?")
        statement = item.get("statement", "")
        console.print(f"  - [{record_type}/{status}] {statement}")
    return int(ExitCode.SUCCESS)


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
    console.print("Stale engineering memory records")
    if not isinstance(records, list) or not records:
        console.print("  (none)")
        return int(ExitCode.SUCCESS)
    for item in records:
        if not isinstance(item, dict):
            continue
        reason = item.get("stale_reason", "")
        console.print(f"  - [{item.get('type')}] {item.get('statement')} ({reason})")
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
    console.print("Engineering Memory vacuum complete")
    console.print(f"  deleted: {report.total_deleted}")
    for key, count in report.deleted_by_status.items():
        console.print(f"    {key}: {count}")
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
    finally:
        store.close()
    console.print("Engineering Memory coverage")
    console.print(
        f"  covered: {report.scope_paths_with_memory}/{report.scope_paths_total} "
        f"({report.scope_coverage_percent}%)"
    )
    if report.uncovered_paths:
        console.print("  uncovered:")
        for path in report.uncovered_paths:
            console.print(f"    - {path}")
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
    console.print("Draft memory candidates")
    if not records:
        console.print("  (none)")
        return int(ExitCode.SUCCESS)
    for record in records:
        console.print(f"  - {record.id} [{record.type}] {record.statement}")
    return int(ExitCode.SUCCESS)


def _run_approve(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
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
    console.print(f"Approved {record.id} -> active")
    return int(ExitCode.SUCCESS)


def _run_reject(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
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
    console.print(f"Rejected {record.id}")
    return int(ExitCode.SUCCESS)


def _run_archive(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
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
    console.print(f"Archived {record.id}")
    return int(ExitCode.SUCCESS)


__all__ = ["memory_main"]

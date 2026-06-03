# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
from pathlib import Path

from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig, resolve_memory_config
from ...config.memory_defaults import DEFAULT_MEMORY_STATEMENT_PREVIEW_CHARS
from ...contracts import ExitCode
from ...memory.embedding import EmbeddingProvider, resolve_embedding_provider
from ...memory.exceptions import MemoryContractError, MemorySemanticUnavailableError
from ...memory.governance import approve_record, archive_record, reject_record
from ...memory.ingest import InitOptions
from ...memory.ingest.runner import run_memory_init
from ...memory.models import MemoryProject, MemoryQuery
from ...memory.paths import normalize_memory_scope_path
from ...memory.project import resolve_memory_db_path, resolve_project_identity
from ...memory.retrieval import query_engineering_memory, query_records_for_repo_path
from ...memory.retrieval.semantic import semantic_search
from ...memory.semantic import (
    AuditIndexSource,
    IndexSource,
    MemoryIndexSource,
    rebuild_semantic_index,
    resolve_semantic_index,
    resolve_semantic_index_writer,
)
from ...memory.semantic.models import SemanticSearchResult
from ...memory.sqlite_store import SqliteEngineeringMemoryStore
from ...memory.status_report import build_memory_status_report
from ...memory.vacuum import run_memory_vacuum
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
    writer = resolve_semantic_index_writer(config.semantic)
    if writer is None:
        return _semantic_unavailable(
            console, "Semantic index is not available for writing."
        )
    db_path = resolve_memory_db_path(root_path, config)
    if not db_path.exists():
        console.print(f"Engineering memory database not found: {db_path}")
        console.print("Run: codeclone memory init")
        return int(ExitCode.CONTRACT_ERROR)
    project = resolve_project_identity(root_path)
    provider = _resolve_semantic_provider_or_fail(console, config)
    if isinstance(provider, int):
        return provider
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        report = rebuild_semantic_index(
            writer=writer,
            provider=provider,
            sources=_semantic_sources(root_path, config, store, project),
        )
    finally:
        store.close()
    console.print(
        f"Rebuilt semantic index: {report.indexed} indexed, {report.deleted} pruned."
    )
    for name, count in sorted(report.by_source.items()):
        console.print(f"  {name}: {count}")
    return int(ExitCode.SUCCESS)


def _run_semantic_search(
    *, console: PrinterLike, root_path: Path, args: argparse.Namespace
) -> int:
    config = resolve_memory_config(root_path)
    index = resolve_semantic_index(config.semantic)
    status = index.status()
    if not status.available:
        return _semantic_unavailable(
            console, f"Semantic search unavailable: {status.reason}."
        )
    provider = _resolve_semantic_provider_or_fail(console, config)
    if isinstance(provider, int):
        return provider
    db_path = resolve_memory_db_path(root_path, config)
    store = SqliteEngineeringMemoryStore(db_path) if db_path.exists() else None
    try:
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
    finally:
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


def _semantic_sources(
    root_path: Path,
    config: MemoryConfig,
    store: SqliteEngineeringMemoryStore,
    project: MemoryProject,
) -> list[IndexSource]:
    audit_db_path = resolve_audit_path(root_path=root_path, value=DEFAULT_AUDIT_PATH)
    sources: list[IndexSource] = [
        MemoryIndexSource(store, project_id=project.id),
        AuditIndexSource(enabled=config.semantic.index_audit, db_path=audit_db_path),
    ]
    return sources


__all__ = ["memory_main"]

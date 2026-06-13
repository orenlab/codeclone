# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Corpus analytics CLI subcommands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from ...analytics.capabilities import (
    AnalyticsCapability,
    check_capability,
    install_hint,
)
from ...analytics.clustering.models import NOISE_LABEL
from ...analytics.contracts import (
    INTENT_REPRESENTATION_DESCRIPTION,
    INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
)
from ...analytics.exceptions import AnalyticsCapabilityError, AnalyticsWorkflowError
from ...analytics.export.json_export import (
    export_clustering_json,
    export_sweep_comparison_json,
)
from ...analytics.report.html import render_analytics_html
from ...analytics.store.sqlite import SqliteCorpusAnalyticsStore
from ...analytics.workflow import (
    BuildResult,
    run_build,
    run_clustering,
    run_embed,
    run_snapshot,
    select_cluster_run,
)
from ...config.analytics import resolve_analytics_config
from ...contracts import ExitCode
from ...utils.json_io import write_json_document_atomically


def _representation_kind(raw: str) -> str:
    if raw == "description":
        return INTENT_REPRESENTATION_DESCRIPTION
    if raw == "description_with_frame":
        return INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME
    msg = f"unsupported representation: {raw}"
    raise AnalyticsWorkflowError(msg)


def _require_capability(capability: AnalyticsCapability) -> None:
    status = check_capability(capability)
    if not status.available:
        missing = ", ".join(status.missing_packages)
        raise AnalyticsCapabilityError(
            f"missing analytics dependencies: {missing}. "
            f"Install with: {install_hint(status.missing_packages)}"
        )


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: .)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeclone analytics")
    sub = parser.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot", help="Build immutable intent corpus snapshot")
    _add_root(snapshot)
    snapshot.add_argument(
        "--representation",
        choices=("description", "description_with_frame"),
        default="description",
    )
    snapshot.add_argument("--output-json", type=Path, default=None)

    embed = sub.add_parser("embed", help="Generate analytics embeddings for snapshot")
    _add_root(embed)
    embed.add_argument("--snapshot-id", required=True)

    cluster = sub.add_parser("cluster", help="Cluster embedded snapshot")
    _add_root(cluster)
    cluster.add_argument("--snapshot-id", required=True)
    cluster.add_argument("--embedding-generation-id", required=True)
    cluster.add_argument("--sweep", action="store_true")
    cluster.add_argument("--select-run", dest="select_run", default=None)

    build = sub.add_parser("build", help="Snapshot, embed, and cluster end-to-end")
    _add_root(build)
    build.add_argument(
        "--lane",
        choices=("intent",),
        default="intent",
    )
    build.add_argument(
        "--representation",
        choices=("description", "description_with_frame"),
        default="description",
    )
    build.add_argument("--sweep", action="store_true")
    build.add_argument("--use-recommended", action="store_true")
    build.add_argument("--html-out", type=Path, default=None)
    build.add_argument("--json-out", type=Path, default=None)

    clusters = sub.add_parser("clusters", help="List clustering runs for snapshot")
    _add_root(clusters)
    clusters.add_argument("--snapshot-id", required=True)

    cluster_show = sub.add_parser("cluster-show", help="Export one clustering run JSON")
    _add_root(cluster_show)
    cluster_show.add_argument("--snapshot-id", required=True)
    cluster_show.add_argument("--run-id", required=True)
    cluster_show.add_argument("--output", type=Path, default=None)

    outliers = sub.add_parser("outliers", help="Show noise cluster assignments")
    _add_root(outliers)
    outliers.add_argument("--snapshot-id", required=True)
    outliers.add_argument("--run-id", required=True)

    return parser


def _run_snapshot_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("base")
    snapshot_result = run_snapshot(
        root_path=root,
        representation_kind=_representation_kind(args.representation),
    )
    payload = {
        "snapshot_id": snapshot_result.snapshot_id,
        "source_digest": snapshot_result.source_digest,
        "record_count": snapshot_result.record_count,
    }
    if args.output_json is not None:
        write_json_document_atomically(args.output_json, payload)
    else:
        print(payload)
    return ExitCode.SUCCESS


def _run_embed_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("embed")
    embed_result = run_embed(root_path=root, snapshot_id=args.snapshot_id)
    print(
        {
            "embedding_generation_id": embed_result.embedding_generation_id,
            "item_count": embed_result.item_count,
        }
    )
    return ExitCode.SUCCESS


def _run_cluster_command(args: argparse.Namespace, root: Path) -> int:
    if args.select_run:
        _require_capability("base")
        select_cluster_run(root_path=root, clustering_run_id=args.select_run)
        print({"selected_run_id": args.select_run})
        return ExitCode.SUCCESS
    _require_capability("cluster")
    run_ids = run_clustering(
        root_path=root,
        snapshot_id=args.snapshot_id,
        embedding_generation_id=args.embedding_generation_id,
        sweep=args.sweep,
    )
    print({"clustering_run_ids": list(run_ids)})
    return ExitCode.SUCCESS


def _write_build_exports(
    *,
    args: argparse.Namespace,
    root: Path,
    build_result: BuildResult,
) -> None:
    config = resolve_analytics_config(root)
    store = SqliteCorpusAnalyticsStore.open(config.db_path)
    try:
        snapshot = store.get_snapshot(build_result.snapshot_id)
        if snapshot is None:
            raise AnalyticsWorkflowError("snapshot missing after build")
        primary_run_id = build_result.recommended_run_id or (
            build_result.clustering_run_ids[0]
            if build_result.clustering_run_ids
            else None
        )
        if args.json_out is not None and primary_run_id is not None:
            if args.sweep and not args.use_recommended:
                text = export_sweep_comparison_json(
                    store=store,
                    snapshot_id=build_result.snapshot_id,
                    embedding_generation_id=build_result.embedding_generation_id,
                )
            else:
                text = export_clustering_json(
                    store=store,
                    snapshot_id=build_result.snapshot_id,
                    clustering_run_id=primary_run_id,
                )
            args.json_out.write_text(text, encoding="utf-8")
        if args.html_out is not None and primary_run_id is not None:
            run = store.get_clustering_run(primary_run_id)
            if run is None:
                raise AnalyticsWorkflowError("clustering run missing after build")
            html = render_analytics_html(
                store=store,
                snapshot=snapshot,
                run=run,
                comparison_only=args.sweep and not args.use_recommended,
            )
            args.html_out.write_text(html, encoding="utf-8")
    finally:
        store.close()


def _run_build_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("full")
    build_result = run_build(
        root_path=root,
        representation_kind=_representation_kind(args.representation),
        sweep=args.sweep,
        use_recommended=args.use_recommended,
    )
    if args.json_out is not None or args.html_out is not None:
        _write_build_exports(args=args, root=root, build_result=build_result)
    print(
        {
            "snapshot_id": build_result.snapshot_id,
            "embedding_generation_id": build_result.embedding_generation_id,
            "clustering_run_ids": list(build_result.clustering_run_ids),
            "recommended_run_id": build_result.recommended_run_id,
        }
    )
    return ExitCode.SUCCESS


def _run_clusters_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("base")
    config = resolve_analytics_config(root)
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        runs = store.list_clustering_runs(snapshot_id=args.snapshot_id)
        print(
            [
                {
                    "clustering_run_id": run.clustering_run_id,
                    "recommended_by_heuristic": run.recommended_by_heuristic,
                    "selected_by_maintainer": run.selected_by_maintainer,
                    "status": run.status,
                }
                for run in runs
            ]
        )
    finally:
        store.close()
    return ExitCode.SUCCESS


def _run_cluster_show_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("base")
    config = resolve_analytics_config(root)
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        text = export_clustering_json(
            store=store,
            snapshot_id=args.snapshot_id,
            clustering_run_id=args.run_id,
        )
        if args.output is not None:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text)
    finally:
        store.close()
    return ExitCode.SUCCESS


def _run_outliers_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("base")
    config = resolve_analytics_config(root)
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        assignments = store.list_assignments(args.run_id)
        noise = [
            item.snapshot_item_id
            for item in assignments
            if item.cluster_label == NOISE_LABEL
        ]
        print({"noise_items": noise})
    finally:
        store.close()
    return ExitCode.SUCCESS


_CommandHandler = Callable[[argparse.Namespace, Path], int]

_COMMAND_HANDLERS: dict[str, _CommandHandler] = {
    "snapshot": _run_snapshot_command,
    "embed": _run_embed_command,
    "cluster": _run_cluster_command,
    "build": _run_build_command,
    "clusters": _run_clusters_command,
    "cluster-show": _run_cluster_show_command,
    "outliers": _run_outliers_command,
}


def analytics_main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    handler = _COMMAND_HANDLERS.get(args.command)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
        return ExitCode.INTERNAL_ERROR
    try:
        return handler(args, root)
    except AnalyticsCapabilityError as exc:
        print(str(exc), file=sys.stderr)
        return ExitCode.CONTRACT_ERROR
    except AnalyticsWorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return ExitCode.CONTRACT_ERROR


__all__ = ["analytics_main"]

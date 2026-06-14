# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Corpus analytics CLI subcommands."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

from ...analytics.capabilities import (
    AnalyticsCapability,
    check_capability,
    install_hint,
)
from ...analytics.clustering.models import NOISE_LABEL, ClusteringParameters
from ...analytics.contracts import (
    INTENT_REPRESENTATION_DESCRIPTION,
    INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
)
from ...analytics.exceptions import (
    AnalyticsCapabilityError,
    AnalyticsError,
    AnalyticsWorkflowError,
)
from ...analytics.export.json_export import (
    export_clustering_json,
    export_sweep_comparison_json,
)
from ...analytics.integrity import validate_persisted_run
from ...analytics.profiles.loader import (
    load_manifest_file,
    manifest_value,
    profile_manifest_digest,
)
from ...analytics.profiles.models import ProfileSearchSpace
from ...analytics.profiles.registry import (
    ProfileRegistry,
    get_profile,
    list_profiles,
    resolve_profile_registry,
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
from ...config.analytics import AnalyticsConfig, resolve_analytics_config
from ...config.observability import resolve_observability_config
from ...contracts import ExitCode
from ...observability import bootstrap, operation, shutdown, span
from ...utils.json_io import (
    json_text,
    write_json_document_atomically,
    write_json_text_atomically,
)
from ...utils.repo_paths import RepoPathPolicy, resolve_under_repo_root


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


def _add_clustering_controls(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--pca-dimensions", type=int, default=None)
    parser.add_argument("--min-cluster-size", type=int, default=None)
    parser.add_argument("--min-samples", type=int, default=None)
    parser.add_argument(
        "--cluster-selection-method",
        choices=("eom", "leaf"),
        default=None,
    )
    parser.add_argument("--sweep-pca", default=None)
    parser.add_argument("--sweep-min-cluster-size", default=None)
    parser.add_argument("--sweep-min-samples", default=None)
    parser.add_argument("--sweep-selection-method", default=None)


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
    cluster.add_argument("--snapshot-id")
    cluster.add_argument("--embedding-generation-id")
    _add_clustering_controls(cluster)
    cluster.add_argument("--select-run", dest="select_run", default=None)
    cluster.add_argument("--selection-rationale", default=None)
    cluster.add_argument(
        "--selected-by",
        default=None,
    )
    cluster.add_argument(
        "--selection-profile",
        default="none",
        help="Profile batch id, profile id, or none for global selection",
    )

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
    _add_clustering_controls(build)
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

    profiles = sub.add_parser("profiles", help="Inspect analytics profile registry")
    profile_sub = profiles.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list", help="List registered profiles")
    _add_root(profile_list)
    profile_show = profile_sub.add_parser("show", help="Show one profile manifest")
    _add_root(profile_show)
    profile_show.add_argument("--profile-id", required=True)
    profile_validate = profile_sub.add_parser(
        "validate",
        help="Validate one manifest or the resolved registry",
    )
    _add_root(profile_validate)
    profile_validate.add_argument("--path", type=Path, default=None)

    return parser


def _comma_ints(raw: str, *, flag: str) -> tuple[int, ...]:
    try:
        values = tuple(int(item.strip()) for item in raw.split(","))
    except ValueError as exc:
        raise AnalyticsWorkflowError(
            f"{flag} requires comma-separated positive integers"
        ) from exc
    if not values or any(value <= 0 for value in values):
        raise AnalyticsWorkflowError(
            f"{flag} requires comma-separated positive integers"
        )
    return tuple(sorted(set(values)))


def _comma_methods(
    raw: str,
) -> tuple[Literal["eom", "leaf"], ...]:
    values = tuple(sorted({item.strip() for item in raw.split(",") if item.strip()}))
    if not values or any(value not in {"eom", "leaf"} for value in values):
        raise AnalyticsWorkflowError(
            "--sweep-selection-method requires eom and/or leaf"
        )
    return cast("tuple[Literal['eom', 'leaf'], ...]", values)


def _single_parameter_flags_set(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, field, None) is not None
        for field in (
            "pca_dimensions",
            "min_cluster_size",
            "min_samples",
            "cluster_selection_method",
        )
    )


def _sweep_override_flags_set(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, field, None) is not None
        for field in (
            "sweep_pca",
            "sweep_min_cluster_size",
            "sweep_min_samples",
            "sweep_selection_method",
        )
    )


def _clustering_execution_args_set(args: argparse.Namespace) -> bool:
    return any(
        (
            getattr(args, "snapshot_id", None) is not None,
            getattr(args, "embedding_generation_id", None) is not None,
            bool(getattr(args, "sweep", False)),
            getattr(args, "profile", None) is not None,
            _single_parameter_flags_set(args),
            _sweep_override_flags_set(args),
        )
    )


def _validate_clustering_mode_args(args: argparse.Namespace) -> None:
    single = _single_parameter_flags_set(args)
    sweep_overrides = _sweep_override_flags_set(args)
    if getattr(args, "profile", None) is not None and single:
        raise AnalyticsWorkflowError(
            "profile sweep conflicts with explicit clustering parameters"
        )
    if sweep_overrides:
        args.sweep = True
    if getattr(args, "profile", None) is not None:
        args.sweep = True
    if args.sweep and single:
        raise AnalyticsWorkflowError(
            "sweep mode conflicts with explicit clustering parameters"
        )


def _clustering_parameters_from_args(
    args: argparse.Namespace,
    *,
    config: AnalyticsConfig,
) -> ClusteringParameters | None:
    if not _single_parameter_flags_set(args):
        return None
    return ClusteringParameters(
        pca_dimensions=(
            args.pca_dimensions
            if args.pca_dimensions is not None
            else config.default_pca_dimensions
        ),
        min_cluster_size=(
            args.min_cluster_size
            if args.min_cluster_size is not None
            else config.default_min_cluster_size
        ),
        min_samples=(
            args.min_samples
            if args.min_samples is not None
            else config.default_min_samples
        ),
        cluster_selection_method=(
            args.cluster_selection_method
            if args.cluster_selection_method is not None
            else config.default_cluster_selection_method
        ),
    )


def _sweep_grid_from_args(
    args: argparse.Namespace,
    *,
    config: AnalyticsConfig,
) -> ProfileSearchSpace | None:
    if not _sweep_override_flags_set(args):
        return None
    return ProfileSearchSpace(
        pca_dimensions=(
            _comma_ints(args.sweep_pca, flag="--sweep-pca")
            if args.sweep_pca is not None
            else config.sweep_pca_dimensions
        ),
        min_cluster_size=(
            _comma_ints(
                args.sweep_min_cluster_size,
                flag="--sweep-min-cluster-size",
            )
            if args.sweep_min_cluster_size is not None
            else config.sweep_min_cluster_sizes
        ),
        min_samples=(
            _comma_ints(args.sweep_min_samples, flag="--sweep-min-samples")
            if args.sweep_min_samples is not None
            else config.sweep_min_samples
        ),
        cluster_selection_method=(
            _comma_methods(args.sweep_selection_method)
            if args.sweep_selection_method is not None
            else config.sweep_selection_methods
        ),
    )


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
        _print_json(payload)
    return ExitCode.SUCCESS


def _run_embed_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("embed")
    embed_result = run_embed(root_path=root, snapshot_id=args.snapshot_id)
    _print_json(
        {
            "embedding_generation_id": embed_result.embedding_generation_id,
            "item_count": embed_result.item_count,
        }
    )
    return ExitCode.SUCCESS


def _run_cluster_command(args: argparse.Namespace, root: Path) -> int:
    if args.select_run:
        if _clustering_execution_args_set(args):
            raise AnalyticsWorkflowError(
                "--select-run cannot be combined with clustering execution arguments"
            )
        _require_capability("base")
        profile_batch_id, selection_profile_id = _selection_scope(
            getattr(args, "selection_profile", "none")
        )
        requested_selected_by = getattr(args, "selected_by", None)
        selected_by = (
            requested_selected_by
            if requested_selected_by is not None
            else os.environ.get("USER") or "local-maintainer"
        )
        selection = select_cluster_run(
            root_path=root,
            clustering_run_id=args.select_run,
            profile_batch_id=profile_batch_id,
            selection_profile_id=selection_profile_id,
            selected_by=selected_by,
            rationale=getattr(args, "selection_rationale", None),
        )
        _print_json(
            {
                "selected_run_id": args.select_run,
                "selection_id": selection.selection_id,
            }
        )
        return ExitCode.SUCCESS
    if (
        getattr(args, "selection_rationale", None) is not None
        or getattr(args, "selection_profile", "none") != "none"
        or getattr(args, "selected_by", None) is not None
    ):
        raise AnalyticsWorkflowError(
            "--selection-rationale, --selection-profile, and --selected-by "
            "require --select-run"
        )
    if not args.snapshot_id or not args.embedding_generation_id:
        raise AnalyticsWorkflowError(
            "--snapshot-id and --embedding-generation-id are required "
            "unless --select-run is used"
        )
    _validate_clustering_mode_args(args)
    _require_capability("cluster")
    config = resolve_analytics_config(root)
    run_ids = run_clustering(
        root_path=root,
        snapshot_id=args.snapshot_id,
        embedding_generation_id=args.embedding_generation_id,
        requested=_clustering_parameters_from_args(args, config=config),
        sweep=args.sweep,
        sweep_grid=_sweep_grid_from_args(args, config=config),
        profile_id=getattr(args, "profile", None),
        config=config,
    )
    payload: dict[str, object] = {"clustering_run_ids": list(run_ids)}
    if not config.db_path.exists():
        _print_json(payload)
        return ExitCode.SUCCESS
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        runs = store.list_clustering_runs(
            snapshot_id=args.snapshot_id,
            embedding_generation_id=args.embedding_generation_id,
        )
        recommended = next(
            (run.clustering_run_id for run in runs if run.recommended_by_heuristic),
            None,
        )
        if recommended is not None:
            payload["recommended_run_id"] = recommended
        resolved_profile_id = _resolved_profile_id(
            config,
            getattr(args, "profile", None),
        )
        if resolved_profile_id is not None:
            batch = store.get_latest_profile_batch(
                snapshot_id=args.snapshot_id,
                embedding_generation_id=args.embedding_generation_id,
                profile_id=resolved_profile_id,
            )
            if batch is not None:
                payload.update(
                    {
                        "profile_batch_id": batch.profile_batch_id,
                        "recommended_for_profile_run_id": (
                            batch.recommended_clustering_run_id
                        ),
                        "profile_id": batch.profile_id,
                        "batch_status": batch.status,
                    }
                )
    finally:
        store.close()
    _print_json(payload)
    return ExitCode.SUCCESS


def _selection_scope(raw: str) -> tuple[str | None, str | None]:
    normalized = raw.strip()
    if normalized == "none":
        return None, None
    if normalized.startswith("pbatch-"):
        return normalized, None
    return None, normalized


def _resolved_profile_id(
    config: AnalyticsConfig,
    profile_id: str | None,
) -> str | None:
    if profile_id is None:
        return None
    if profile_id == "auto":
        if config.default_profile_id is None:
            raise AnalyticsWorkflowError("default_profile_id not configured")
        return config.default_profile_id
    return profile_id


def _write_build_exports(
    *,
    args: argparse.Namespace,
    root: Path,
    build_result: BuildResult,
) -> None:
    config = resolve_analytics_config(root)
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        snapshot = store.get_snapshot(build_result.snapshot_id)
        if snapshot is None:
            raise AnalyticsWorkflowError("snapshot missing after build")
        primary_run_id = (
            build_result.recommended_for_profile_run_id
            if args.use_recommended and build_result.profile_id is not None
            else build_result.recommended_run_id
            if args.use_recommended
            else None
        ) or (
            build_result.clustering_run_ids[0]
            if build_result.clustering_run_ids
            else None
        )
        comparison_export = args.sweep and (
            not args.use_recommended
            or (
                build_result.profile_id is not None
                and build_result.recommended_for_profile_run_id is None
            )
        )
        if primary_run_id is None and comparison_export and args.html_out is not None:
            runs = store.list_clustering_runs(
                snapshot_id=build_result.snapshot_id,
                embedding_generation_id=build_result.embedding_generation_id,
            )
            primary_run_id = runs[0].clustering_run_id if runs else None
        with span(name="analytics.report"):
            if args.json_out is not None and (
                comparison_export or primary_run_id is not None
            ):
                if comparison_export:
                    text = export_sweep_comparison_json(
                        store=store,
                        snapshot_id=build_result.snapshot_id,
                        embedding_generation_id=build_result.embedding_generation_id,
                        profile_id=build_result.profile_id,
                        profile_batch_id=build_result.profile_batch_id,
                    )
                else:
                    if primary_run_id is None:
                        raise AnalyticsWorkflowError(
                            "clustering run missing after build"
                        )
                    text = export_clustering_json(
                        store=store,
                        snapshot_id=build_result.snapshot_id,
                        clustering_run_id=primary_run_id,
                        profile_id=build_result.profile_id,
                        profile_batch_id=build_result.profile_batch_id,
                    )
                args.json_out.parent.mkdir(parents=True, exist_ok=True)
                write_json_text_atomically(args.json_out, text)
            if args.html_out is not None:
                if primary_run_id is None:
                    raise AnalyticsWorkflowError("clustering run missing after build")
                run = store.get_clustering_run(primary_run_id)
                if run is None:
                    raise AnalyticsWorkflowError("clustering run missing after build")
                rendered = render_analytics_html(
                    store=store,
                    snapshot=snapshot,
                    run=run,
                    comparison_only=comparison_export,
                    profile_id=build_result.profile_id,
                    profile_batch_id=build_result.profile_batch_id,
                )
                args.html_out.parent.mkdir(parents=True, exist_ok=True)
                write_json_text_atomically(args.html_out, rendered)
    finally:
        store.close()


def _run_build_command(args: argparse.Namespace, root: Path) -> int:
    _validate_clustering_mode_args(args)
    if args.use_recommended and not args.sweep:
        raise AnalyticsWorkflowError("--use-recommended requires --sweep")
    _require_capability("full")
    config = resolve_analytics_config(root)
    build_result = run_build(
        root_path=root,
        representation_kind=_representation_kind(args.representation),
        sweep=args.sweep,
        use_recommended=args.use_recommended,
        requested=_clustering_parameters_from_args(args, config=config),
        sweep_grid=_sweep_grid_from_args(args, config=config),
        profile_id=getattr(args, "profile", None),
        config=config,
    )
    if args.json_out is not None or args.html_out is not None:
        _write_build_exports(args=args, root=root, build_result=build_result)
    _print_json(
        {
            "snapshot_id": build_result.snapshot_id,
            "embedding_generation_id": build_result.embedding_generation_id,
            "clustering_run_ids": list(build_result.clustering_run_ids),
            "recommended_run_id": build_result.recommended_run_id,
            "profile_id": build_result.profile_id,
            "profile_batch_id": build_result.profile_batch_id,
            "recommended_for_profile_run_id": (
                build_result.recommended_for_profile_run_id
            ),
        }
    )
    return ExitCode.SUCCESS


def _run_clusters_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("base")
    config = resolve_analytics_config(root)
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        if store.get_snapshot(args.snapshot_id) is None:
            raise AnalyticsWorkflowError(f"unknown snapshot: {args.snapshot_id}")
        runs = store.list_clustering_runs(snapshot_id=args.snapshot_id)
        _print_json(
            [
                {
                    "clustering_run_id": run.clustering_run_id,
                    "recommended_by_heuristic": run.recommended_by_heuristic,
                    "selected_by_maintainer": run.selected_by_maintainer,
                    "profile_batch_ids": (
                        list(
                            store.list_profile_batch_ids_for_run(
                                clustering_run_id=run.clustering_run_id
                            )
                        )
                        if hasattr(store, "list_profile_batch_ids_for_run")
                        else []
                    ),
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
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_json_text_atomically(args.output, text)
        else:
            print(text, end="")
    finally:
        store.close()
    return ExitCode.SUCCESS


def _run_outliers_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("base")
    config = resolve_analytics_config(root)
    store = SqliteCorpusAnalyticsStore.open_readonly(config.db_path)
    try:
        validate_persisted_run(
            store=store,
            snapshot_id=args.snapshot_id,
            clustering_run_id=args.run_id,
        )
        assignments = store.list_assignments(args.run_id)
        noise = [
            item.snapshot_item_id
            for item in assignments
            if item.cluster_label == NOISE_LABEL
        ]
        _print_json({"noise_items": noise})
    finally:
        store.close()
    return ExitCode.SUCCESS


def _profile_registry(root: Path) -> tuple[AnalyticsConfig, ProfileRegistry]:
    config = resolve_analytics_config(root)
    registry = resolve_profile_registry(
        profile_paths=config.profile_paths,
        default_profile_id=config.default_profile_id,
    )
    return config, registry


def _run_profiles_command(args: argparse.Namespace, root: Path) -> int:
    _require_capability("base")
    _config, registry = _profile_registry(root)
    if args.profile_command == "list":
        _print_json(
            {
                "profiles": [
                    {
                        "profile_id": profile_id,
                        "label": registry.profiles[profile_id].label,
                        "profile_version": (
                            registry.profiles[profile_id].profile_version
                        ),
                        "source": registry.sources[profile_id],
                        "manifest_digest": profile_manifest_digest(
                            registry.profiles[profile_id]
                        ),
                    }
                    for profile_id in list_profiles(registry)
                ]
            }
        )
        return ExitCode.SUCCESS
    if args.profile_command == "show":
        profile = get_profile(registry, args.profile_id)
        payload = manifest_value(profile)
        payload["manifest_digest"] = profile_manifest_digest(profile)
        payload["source"] = registry.sources[profile.profile_id]
        _print_json(payload)
        return ExitCode.SUCCESS
    if args.path is not None:
        path = resolve_under_repo_root(
            root,
            args.path,
            policy=RepoPathPolicy(
                allow_absolute=True,
                must_exist=True,
                must_be_file=True,
            ),
        )
        profile = load_manifest_file(path)
        _print_json(
            {
                "valid": True,
                "profile_id": profile.profile_id,
                "manifest_digest": profile_manifest_digest(profile),
            }
        )
        return ExitCode.SUCCESS
    _print_json(
        {
            "valid": True,
            "profiles": [
                {
                    "profile_id": profile_id,
                    "manifest_digest": profile_manifest_digest(
                        registry.profiles[profile_id]
                    ),
                }
                for profile_id in list_profiles(registry)
            ],
        }
    )
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
    "profiles": _run_profiles_command,
}


def analytics_main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"repository root is not a directory: {root}", file=sys.stderr)
        return ExitCode.CONTRACT_ERROR
    handler = _COMMAND_HANDLERS[args.command]
    try:
        bootstrap(resolve_observability_config(), root=root)
        with operation(name=f"cli.analytics.{args.command}", surface="cli"):
            return handler(args, root)
    except (AnalyticsError, OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return ExitCode.CONTRACT_ERROR
    finally:
        shutdown()


def _print_json(payload: object) -> None:
    print(json_text(payload, sort_keys=True))


__all__ = ["analytics_main"]

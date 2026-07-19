# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from argparse import Namespace
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

import pytest

import codeclone.core.parallelism as parallelism_module
import codeclone.core.worker as worker_module
import codeclone.paths.module_identity.inventory as inventory_module
import codeclone.paths.module_identity.manifest as manifest_module
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.cache.reuse import source_content_digest
from codeclone.cache.store import Cache, file_stat_signature
from codeclone.core._types import (
    BootstrapResult,
    DiscoveryResult,
    FileProcessResult,
    OutputPaths,
)
from codeclone.core.discovery import discover
from codeclone.core.parallelism import process
from codeclone.models import ImportMount, PackagePrefix
from codeclone.paths.module_identity.inventory import (
    ModuleRegistryCollisionError,
    build_module_registry,
)
from codeclone.scanner import discover_python_files, iter_py_files


def _write(root: Path, relative: str, source: str = "value = 1\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, "utf-8")
    return path


def test_inventory_keeps_analysis_excludes_and_drops_hard_excludes(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "pkg/live.py")
    _write(tmp_path, "migrations/old.py")
    _write(tmp_path, ".git/hidden.py")

    registry = build_module_registry(root=tmp_path)

    assert tuple(registry.entries_by_path) == (
        "migrations/old.py",
        "pkg/live.py",
    )
    excluded = registry.entries_by_path["migrations/old.py"]
    assert excluded.analyzed is False
    assert excluded.internality == "known_internal_not_analyzed"
    assert excluded.identity.python_module is not None
    assert excluded.identity.python_module.module == "migrations.old"
    assert registry.entries_by_path["pkg/live.py"].analyzed is True
    assert ".git/hidden.py" not in registry.entries_by_path


def test_inventory_null_modules_and_namespace_prefixes_are_separate(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "src/acme/service.py")
    _write(tmp_path, "scripts/not-a-module.py")

    registry = build_module_registry(root=tmp_path, source_roots=("src",))

    assert (
        registry.entries_by_path["scripts/not-a-module.py"].identity.python_module
        is None
    )
    assert "" not in registry.entries_by_module
    assert registry.package_prefixes == (
        PackagePrefix(
            module="acme",
            node_kind="namespace_package",
            mount_paths=("src",),
            contributing_paths=("src/acme/service.py",),
        ),
    )


def test_duplicate_modules_and_equal_mounts_fail_before_registry_freeze(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "one/pkg/mod.py")
    _write(tmp_path, "two/pkg/mod.py")
    with pytest.raises(ModuleRegistryCollisionError, match=r"module:pkg\.mod"):
        build_module_registry(
            root=tmp_path,
            import_mounts=(
                ImportMount(path="one", module_prefix="", origin="explicit"),
                ImportMount(path="two", module_prefix="", origin="explicit"),
            ),
            strategy="explicit",
        )

    with pytest.raises(ModuleRegistryCollisionError, match="mount:one"):
        build_module_registry(
            root=tmp_path,
            import_mounts=(
                ImportMount(path="one", module_prefix="", origin="explicit"),
                ImportMount(path="one", module_prefix="alternate", origin="explicit"),
            ),
            strategy="explicit",
        )


def test_empty_import_mount_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py")
    with pytest.raises(ValueError, match="import mount paths"):
        build_module_registry(
            root=tmp_path,
            import_mounts=(ImportMount(path="", module_prefix="", origin="explicit"),),
            strategy="explicit",
        )


def test_registry_digest_is_creation_order_stable_and_handle_is_picklable(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    for root, paths in (
        (left, ("z.py", "pkg/a.py", "pkg/__init__.py")),
        (right, ("pkg/__init__.py", "pkg/a.py", "z.py")),
    ):
        for path in paths:
            _write(root, path)

    left_registry = build_module_registry(root=left)
    right_registry = build_module_registry(root=right)

    assert left_registry.digest == right_registry.digest
    assert left_registry == right_registry
    assert pickle.loads(pickle.dumps(left_registry)) == left_registry


def test_registry_digest_is_hash_seed_stable(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/mod.py")
    script = (
        "from pathlib import Path; "
        "from codeclone.paths.module_identity.inventory import build_module_registry; "
        "import sys; "
        "print(build_module_registry(root=Path(sys.argv[1])).digest.value)"
    )
    digests = []
    for seed in ("1", "731"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            (sys.executable, "-c", script, str(tmp_path)),
            cwd=Path(__file__).parents[1],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        digests.append(completed.stdout.strip())
    assert len(set(digests)) == 1


class _RecordedSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.status = "ok"
        self.counters: dict[str, int] = {}

    def set_counter(self, key: str, value: int) -> None:
        self.counters[key] = value


class _SpanFactory(Protocol):
    def __call__(self, *, name: str) -> AbstractContextManager[_RecordedSpan]: ...


def _recording_span_factory(recorded: list[_RecordedSpan]) -> _SpanFactory:
    @contextmanager
    def recording_span(*, name: str) -> Iterator[_RecordedSpan]:
        observed = _RecordedSpan(name)
        recorded.append(observed)
        try:
            yield observed
        except Exception:
            observed.status = "error"
            raise

    return recording_span


def test_registry_build_has_one_bounded_span_and_one_discovery_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "pkg/live.py")
    _write(tmp_path, "migrations/old.py")
    recorded: list[_RecordedSpan] = []
    manifest_recorded: list[_RecordedSpan] = []
    walks = 0
    real_discover = discover_python_files

    def _discover_once(
        root: str, *, hard_excludes: tuple[str, ...], max_files: int
    ) -> tuple[tuple[str, ...], int]:
        nonlocal walks
        walks += 1
        return real_discover(
            root,
            hard_excludes=hard_excludes,
            max_files=max_files,
        )

    monkeypatch.setattr(inventory_module, "span", _recording_span_factory(recorded))
    monkeypatch.setattr(
        manifest_module,
        "span",
        _recording_span_factory(manifest_recorded),
    )
    monkeypatch.setattr(inventory_module, "discover_python_files", _discover_once)

    registry = build_module_registry(root=tmp_path)

    assert walks == 1
    assert registry.entries_by_module["pkg.live"].analyzed is True
    assert len(recorded) == 1
    assert len(manifest_recorded) == 1
    assert manifest_recorded[0].name == "manifest.build"
    assert recorded[0].name == "registry.build"
    assert recorded[0].status == "ok"
    assert recorded[0].counters == {
        "registry_analyzed": 1,
        "registry_collisions": 0,
        "registry_discovered": 2,
        "registry_hard_excluded": 0,
        "registry_inventoried": 2,
        "registry_known_internal_not_analyzed": 1,
        "registry_null_modules": 0,
        "registry_worker_installs": 0,
    }


def test_registry_observer_is_fact_neutral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "pkg/live.py")
    enabled = build_module_registry(root=tmp_path)
    monkeypatch.setattr(
        inventory_module,
        "span",
        _recording_span_factory([]),
    )
    observed = build_module_registry(root=tmp_path)
    assert observed == enabled


def test_registry_owner_has_no_second_walk_or_legacy_module_derivation() -> None:
    inventory_source = Path(inventory_module.__file__).read_text("utf-8")
    discovery_source = (
        Path(__file__).parents[1] / "codeclone/core/discovery.py"
    ).read_text("utf-8")
    assert "os.walk" not in inventory_source
    assert "iter_py_files" not in discovery_source
    assert "module_name_from_path" not in inventory_source
    assert "module_name_from_path" not in discovery_source


def test_discovery_analyzed_set_remains_byte_neutral(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/live.py")
    _write(tmp_path, "migrations/old.py")
    legacy_paths = tuple(iter_py_files(str(tmp_path)))
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(skip_metrics=True, source_roots=(".",)),
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )

    result = discover(
        boot=boot,
        cache=Cache(tmp_path / "cache.json", root=tmp_path),
    )

    assert result.all_file_paths == legacy_paths
    assert result.files_to_process == legacy_paths
    assert result.files_found == len(legacy_paths)
    assert result.module_registry is not None
    assert "migrations/old.py" in result.module_registry.entries_by_path
    assert result.module_registry.entries_by_path["migrations/old.py"].analyzed is False


def _recording_executor_factory(
    *,
    initializers: list[Callable[..., None] | None],
    initargs_seen: list[tuple[object, ...]],
    submitted_kwargs: list[dict[str, object]],
) -> Callable[..., AbstractContextManager[SimpleNamespace]]:
    @contextmanager
    def _executor(
        *,
        max_workers: int,
        initializer: Callable[..., None] | None = None,
        initargs: tuple[object, ...] = (),
    ) -> Iterator[SimpleNamespace]:
        assert max_workers == 2
        initializers.append(initializer)
        initargs_seen.append(initargs)
        if initializer is not None:
            initializer(*initargs)
            initializer(*initargs)

        def _submit(
            function: Callable[..., FileProcessResult],
            *args: object,
            **kwargs: object,
        ) -> Future[FileProcessResult]:
            submitted_kwargs.append(kwargs)
            future: Future[FileProcessResult] = Future()
            future.set_result(function(*args, **kwargs))
            return future

        yield SimpleNamespace(submit=_submit)

    return _executor


def _successful_worker(
    filepath: str,
    *_args: object,
    **_kwargs: object,
) -> FileProcessResult:
    return FileProcessResult(
        filepath=filepath,
        success=True,
        source_content_digest=source_content_digest(Path(filepath).read_bytes()),
        units=[],
        blocks=[],
        segments=[],
        lines=1,
        stat=file_stat_signature(filepath),
    )


def test_process_pool_installs_one_registry_per_worker_not_per_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filepaths = tuple(
        str(_write(tmp_path, f"pkg/module_{index}.py")) for index in range(17)
    )
    registry = build_module_registry(root=tmp_path)
    discovery = DiscoveryResult(
        files_found=len(filepaths),
        cache_hits=0,
        files_skipped=0,
        all_file_paths=filepaths,
        cached_units=(),
        cached_blocks=(),
        cached_segments=(),
        cached_class_metrics=(),
        cached_module_deps=(),
        cached_dead_candidates=(),
        cached_referenced_names=frozenset(),
        files_to_process=filepaths,
        skipped_warnings=(),
        module_registry=registry,
    )
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(
            processes=2,
            min_loc=1,
            min_stmt=1,
            block_min_loc=20,
            block_min_stmt=8,
            segment_min_loc=20,
            segment_min_stmt=10,
            skip_metrics=True,
        ),
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    initializers: list[Callable[..., None] | None] = []
    initargs_seen: list[tuple[object, ...]] = []
    submitted_kwargs: list[dict[str, object]] = []
    monkeypatch.setattr(
        parallelism_module,
        "ProcessPoolExecutor",
        _recording_executor_factory(
            initializers=initializers,
            initargs_seen=initargs_seen,
            submitted_kwargs=submitted_kwargs,
        ),
    )
    monkeypatch.setattr(parallelism_module, "as_completed", lambda futures: futures)
    monkeypatch.setattr(parallelism_module, "_invoke_process_file", _successful_worker)
    counters: list[tuple[str, int]] = []
    monkeypatch.setattr(
        parallelism_module,
        "record_counter",
        lambda key, value: counters.append((key, value)),
    )

    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    cache.bind_module_registry(registry)
    result = process(
        boot=boot,
        discovery=discovery,
        cache=cache,
    )

    assert result.files_analyzed == len(filepaths)
    assert initializers == [worker_module._install_module_registry]
    assert initargs_seen == [(registry,)]
    assert worker_module._WORKER_MODULE_REGISTRY is registry
    assert counters == [("registry_worker_installs", 2)]
    assert len(submitted_kwargs) == len(filepaths)
    assert all(registry not in submitted.values() for submitted in submitted_kwargs)

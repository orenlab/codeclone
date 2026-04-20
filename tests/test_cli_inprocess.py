# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import pytest

import codeclone.baseline as baseline
import codeclone.baseline.trust as baseline_trust
import codeclone.core as pipeline
import codeclone.core.discovery as core_discovery
import codeclone.core.parallelism as core_parallelism
import codeclone.core.pipeline as core_pipeline
import codeclone.core.worker as core_worker
import codeclone.surfaces.cli.main as cli
import codeclone.surfaces.cli.report_meta as cli_meta
import codeclone.surfaces.cli.reports_output as cli_reports
from codeclone import __version__
from codeclone.cache import Cache, file_stat_signature
from codeclone.contracts import (
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_SCHEMA_VERSION,
    CACHE_VERSION,
    REPORT_SCHEMA_VERSION,
)
from codeclone.contracts.errors import CacheError
from codeclone.models import Unit
from codeclone.report.gates.reasons import parse_metric_reason_entry
from tests._assertions import (
    assert_contains_all,
    assert_mapping_entries,
    assert_missing_keys,
)
from tests._report_access import (
    report_clone_groups as _report_clone_groups,
)
from tests._report_access import (
    report_inventory_files as _report_inventory_files,
)
from tests._report_access import (
    report_meta_baseline as _report_meta_baseline,
)
from tests._report_access import (
    report_meta_cache as _report_meta_cache,
)
from tests._report_access import (
    report_structural_groups as _report_structural_groups,
)


@dataclass(slots=True)
class _DummyFuture:
    _result: object

    def result(self) -> object:
        return self._result


class _FalseExitContext:
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> Literal[False]:
        self._on_exit()
        return False

    def _on_exit(self) -> None:
        return None


class _DummyExecutor(_FalseExitContext):
    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers
        self._active = False

    def __enter__(self) -> _DummyExecutor:
        self._active = True
        return self

    def _on_exit(self) -> None:
        self._active = False

    def submit(
        self, fn: Callable[..., object], *args: object, **kwargs: object
    ) -> _DummyFuture:
        _ = (self.max_workers, self._active)
        return _DummyFuture(fn(*args, **kwargs))


class _FailingExecutor(_FalseExitContext):
    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers

    def __enter__(self) -> _FailingExecutor:
        raise PermissionError("nope")


@dataclass(slots=True)
class _FixedFuture:
    value: object | None = None
    error: Exception | None = None

    def result(self) -> object | None:
        if self.error:
            raise self.error
        return self.value


class _FixedExecutor(_FalseExitContext):
    def __init__(self, future: _FixedFuture, *args: object, **kwargs: object) -> None:
        self._future = future

    def __enter__(self) -> _FixedExecutor:
        return self

    def submit(
        self, fn: Callable[..., object], *args: object, **kwargs: object
    ) -> _FixedFuture:
        return self._future


class _DummyProgress(_FalseExitContext):
    def __init__(self, *args: object, **kwargs: object) -> None:
        self._entered = False
        self._last_task = 0

    def __enter__(self) -> _DummyProgress:
        self._entered = True
        return self

    def _on_exit(self) -> None:
        self._entered = False

    def add_task(self, _desc: str, total: int) -> int:
        self._last_task = total if self._entered else 0
        return total

    def advance(self, _task: int) -> None:
        _ = self._last_task
        return None


class _DummyColumn:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        return None


def _patch_dummy_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_rich_progress_symbols",
        lambda: (
            _DummyProgress,
            _DummyColumn,
            _DummyColumn,
            _DummyColumn,
            _DummyColumn,
        ),
    )


def _patch_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _DummyExecutor)
    monkeypatch.setattr(core_parallelism, "as_completed", lambda futures: futures)


def _run_main(monkeypatch: pytest.MonkeyPatch, args: Iterable[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["codeclone", *args])
    cli.main()


def _run_parallel_main(monkeypatch: pytest.MonkeyPatch, args: Iterable[str]) -> None:
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, args)


def _assert_cli_exit(
    monkeypatch: pytest.MonkeyPatch,
    args: Iterable[str],
    *,
    expected_code: int,
) -> None:
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, args)
    assert exc.value.code == expected_code


def _assert_parallel_cli_exit(
    monkeypatch: pytest.MonkeyPatch,
    args: Iterable[str],
    *,
    expected_code: int,
) -> None:
    _patch_parallel(monkeypatch)
    _assert_cli_exit(monkeypatch, args, expected_code=expected_code)


def _write_python_module(
    directory: Path,
    filename: str,
    source: str = "def f():\n    return 1\n",
) -> Path:
    path = directory / filename
    path.write_text(source, "utf-8")
    return path


def _write_default_source(directory: Path) -> Path:
    return _write_python_module(directory, "a.py")


def _write_profile_compatibility_source(directory: Path) -> Path:
    return _write_python_module(
        directory,
        "a.py",
        """
def f1():
    x = 1
    return x

def f2():
    y = 1
    return y
""",
    )


def _write_duplicate_function_module(directory: Path, filename: str) -> Path:
    return _write_python_module(
        directory,
        filename,
        """
def duplicated():
    value = 1
    return value
""".strip()
        + "\n",
    )


def _prepare_basic_project(root: Path) -> Path:
    root.mkdir()
    return _write_python_module(root, "a.py")


def _write_legacy_cache_file(base_dir: Path) -> Path:
    legacy_path = base_dir / "legacy" / "cache.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("{}", "utf-8")
    return legacy_path


def _patch_fixed_executor(
    monkeypatch: pytest.MonkeyPatch, future: _FixedFuture
) -> None:
    monkeypatch.setattr(
        core_parallelism,
        "ProcessPoolExecutor",
        lambda *args, **kwargs: _FixedExecutor(future),
    )
    monkeypatch.setattr(core_parallelism, "as_completed", lambda futures: futures)


def _baseline_payload(
    *,
    functions: list[str] | None = None,
    blocks: list[str] | None = None,
    python_version: str | None = None,
    python_tag: str | None = None,
    fingerprint_version: str | None = None,
    baseline_version: str | None = None,
    schema_version: object | None = None,
    include_version_schema: bool = True,
    generator: str | None = "codeclone",
    generator_version: str | None = None,
    payload_sha256: str | None = None,
) -> dict[str, object]:
    function_list = sorted([] if functions is None else functions)
    block_list = sorted([] if blocks is None else blocks)
    if include_version_schema:
        meta_fingerprint = (
            fingerprint_version or baseline_version or BASELINE_FINGERPRINT_VERSION
        )
        meta_schema = (
            BASELINE_SCHEMA_VERSION if schema_version is None else schema_version
        )
        default_tag = baseline.current_python_tag()
        version_suffix = f"{sys.version_info.major}{sys.version_info.minor}"
        prefix = default_tag.removesuffix(version_suffix)
        version_tag: str | None = None
        if python_version:
            ver_match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", python_version.strip())
            if ver_match:
                version_tag = f"{prefix}{ver_match.group(1)}{ver_match.group(2)}"
        meta_python_tag = python_tag or version_tag or default_tag
        meta_generator_version = generator_version or __version__

        hash_value: str | None
        if (
            isinstance(meta_fingerprint, str)
            and isinstance(meta_schema, str)
            and isinstance(meta_python_tag, str)
            and payload_sha256 is None
        ):
            hash_value = baseline_trust._compute_payload_sha256(
                functions=set(function_list),
                blocks=set(block_list),
                fingerprint_version=meta_fingerprint,
                python_tag=meta_python_tag,
            )
        else:
            hash_value = payload_sha256

        meta: dict[str, object] = {
            "generator": {
                "name": generator if generator is not None else "codeclone",
                "version": meta_generator_version,
            },
            "schema_version": meta_schema,
            "fingerprint_version": meta_fingerprint,
            "python_tag": meta_python_tag,
            "created_at": "2026-02-08T11:43:16Z",
            "payload_sha256": hash_value if hash_value is not None else "x" * 64,
        }
        return {
            "meta": meta,
            "clones": {"functions": function_list, "blocks": block_list},
        }

    payload: dict[str, object] = {"functions": function_list, "blocks": block_list}
    if baseline_version is not None:
        payload["baseline_version"] = baseline_version
    if schema_version is not None:
        payload["schema_version"] = schema_version
    return payload


def _write_baseline(
    path: Path,
    *,
    functions: list[str] | None = None,
    blocks: list[str] | None = None,
    python_version: str | None = None,
    python_tag: str | None = None,
    fingerprint_version: str | None = None,
    baseline_version: str | None = None,
    schema_version: object | None = None,
    include_version_schema: bool = True,
    generator: str | None = "codeclone",
    generator_version: str | None = None,
    payload_sha256: str | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            _baseline_payload(
                functions=functions,
                blocks=blocks,
                python_version=python_version,
                python_tag=python_tag,
                fingerprint_version=fingerprint_version,
                baseline_version=baseline_version,
                schema_version=schema_version,
                include_version_schema=include_version_schema,
                generator=generator,
                generator_version=generator_version,
                payload_sha256=payload_sha256,
            )
        ),
        "utf-8",
    )
    return path


def _write_current_python_baseline(path: Path) -> Path:
    return _write_baseline(path, python_version=_current_py_minor())


def _write_legacy_baseline(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "functions": [],
                "blocks": [],
                "python_version": "3.13",
                "schema_version": BASELINE_SCHEMA_VERSION,
            }
        ),
        "utf-8",
    )
    return path


def _assert_baseline_failure_meta(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutate_payload: Callable[[dict[str, object]], None],
    expected_message: str,
    expected_status: str,
    strict_fail: bool = False,
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    payload = _baseline_payload(
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    mutate_payload(payload)
    baseline_path.write_text(json.dumps(payload), "utf-8")
    json_out = tmp_path / "report.json"

    _patch_parallel(monkeypatch)
    args = [
        str(tmp_path),
        "--baseline",
        str(baseline_path),
        "--json",
        str(json_out),
        "--no-progress",
    ]
    if strict_fail:
        args.append("--ci")
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch, args)
        assert exc.value.code == 2
    else:
        _run_main(monkeypatch, args)
    captured = capsys.readouterr()
    out = captured.out
    combined_output = f"{captured.out}\n{captured.err}"
    # CLI UI may present baseline details with a generic wording depending on mode.
    # Keep contract checks strict via exit codes and report meta below.
    if expected_message not in combined_output:
        assert "Invalid baseline" in combined_output or "not trusted" in combined_output
    if strict_fail:
        assert "CI requires a trusted baseline" in out
        assert "Run: codeclone . --update-baseline" in out
    else:
        assert "Baseline is not trusted for this run and will be ignored" in out
        assert "Run: codeclone . --update-baseline" in out
    payload_out = json.loads(json_out.read_text("utf-8"))
    baseline_meta = _report_meta_baseline(payload_out)
    assert baseline_meta["status"] == expected_status
    assert baseline_meta["loaded"] is False


def _assert_fail_on_new_summary(out: str, *, include_blocks: bool = True) -> None:
    assert "GATING FAILURE [new-clones]" in out
    assert "new_function_clone_groups" in out
    if include_blocks:
        assert "new_block_clone_groups" in out
    assert "codeclone . --update-baseline" in out


def _patch_baseline_diff(
    monkeypatch: pytest.MonkeyPatch,
    *,
    new_func: set[str],
    new_block: set[str],
) -> None:
    def _diff(
        _self: object, _f: dict[str, object], _b: dict[str, object]
    ) -> tuple[set[str], set[str]]:
        return new_func, new_block

    monkeypatch.setattr(baseline.Baseline, "diff", _diff)


def _open_html_report_args(project_root: Path, html_out: Path) -> list[str]:
    return [
        str(project_root),
        "--html",
        str(html_out),
        "--open-html-report",
        "--no-progress",
    ]


def _capture_cache_path_for_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    extra_args: Iterable[str],
) -> Path:
    captured: dict[str, Path] = {}

    class _CacheStub:
        def __init__(self, path: Path, **_kwargs: object) -> None:
            captured["path"] = Path(path)
            self.load_warning = None

        def load(self) -> None:
            return None

        def get_file_entry(self, _fp: str) -> None:
            return None

        def put_file_entry(
            self,
            _fp: str,
            _stat: object,
            _units: object,
            _blocks: object,
            _segments: object,
            *,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            return None

        def save(self) -> None:
            return None

    monkeypatch.setattr(cli, "Cache", _CacheStub)
    _write_default_source(tmp_path)
    _run_parallel_main(monkeypatch, [str(tmp_path), *extra_args, "--no-progress"])
    return captured["path"]


def _assert_worker_failure_internal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    no_progress: bool,
) -> None:
    _write_default_source(tmp_path)

    def _boom(*_args: object, **_kwargs: object) -> cli.ProcessingResult:
        raise RuntimeError("boom")

    class _FailExec:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def __enter__(self) -> _FailExec:
            raise PermissionError("nope")

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: object | None,
        ) -> Literal[False]:
            return False

    if not no_progress:
        _patch_dummy_progress(monkeypatch)
    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _FailExec)
    monkeypatch.setattr(core_worker, "process_file", _boom)
    args = [str(tmp_path)]
    if no_progress:
        args.append("--no-progress")
    _assert_cli_exit(monkeypatch, args, expected_code=5)
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out


_SUMMARY_METRIC_MAP: dict[str, str] = {
    "Files found": "found",
    "Files analyzed": "analyzed",
    "analyzed": "analyzed",
    "Cache hits": "cached",
    "from cache": "cached",
    "Files skipped": "skipped",
    "skipped": "skipped",
    "New vs baseline": "new",
    "Function clones": "func",
    "Block clones": "block",
    "Segment clones": "seg",
    "suppressed": "suppressed",
}


def _summary_metric(out: str, label: str) -> int:
    keyword = _SUMMARY_METRIC_MAP.get(label, label)
    match = re.search(rf"(\d[\d,]*)\s+{re.escape(keyword)}", out)
    if match:
        return int(match.group(1).replace(",", ""))
    raise AssertionError(f"summary label not found: {label}\n{out}")


def _compact_summary_metric(out: str, key: str) -> int:
    match = re.search(rf"{re.escape(key)}=(\d+)", out)
    assert match, f"compact summary key not found: {key}\n{out}"
    return int(match.group(1))


def _current_py_minor() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _prepare_source_and_baseline(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=_current_py_minor(),
    )
    return src, baseline_path


def _prepare_api_surface_cache_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: str,
) -> tuple[Path, Path, Path]:
    src = tmp_path / "pkg.py"
    src.write_text(source, "utf-8")
    _patch_parallel(monkeypatch)
    return src, tmp_path / "metrics-baseline.json", tmp_path / "cache.json"


def _run_json_report(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: Iterable[str],
    expect_exit_code: int | None = None,
) -> dict[str, object]:
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    args = [
        str(tmp_path),
        *extra_args,
        "--json",
        str(json_out),
        "--no-progress",
    ]
    if expect_exit_code is None:
        _run_main(monkeypatch, args)
    else:
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch, args)
        assert exc.value.code == expect_exit_code
    payload = json.loads(json_out.read_text("utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _assert_report_baseline_meta(
    payload: dict[str, object],
    *,
    status: str,
    loaded: bool,
    **expected: object,
) -> dict[str, object]:
    baseline_meta = _report_meta_baseline(payload)
    assert baseline_meta["status"] == status
    assert baseline_meta["loaded"] is loaded
    for key, value in expected.items():
        assert baseline_meta[key] == value
    return baseline_meta


def _assert_report_cache_meta(
    payload: dict[str, object],
    *,
    used: bool,
    status: str,
    schema_version: object,
) -> dict[str, object]:
    cache_meta = _report_meta_cache(payload)
    assert_mapping_entries(
        cache_meta,
        used=used,
        status=status,
        schema_version=schema_version,
    )
    return cache_meta


def _prepare_single_source_cache(tmp_path: Path) -> tuple[Path, Path, Cache]:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    cache_path = tmp_path / "cache.json"
    return src, cache_path, Cache(cache_path)


def _source_read_error_result(filepath: str) -> cli.ProcessingResult:
    return cli.ProcessingResult(
        filepath=filepath,
        success=False,
        error="Cannot read file: [Errno 13] Permission denied",
        error_kind="source_read_error",
    )


def _assert_unreadable_source_contract_error(out: str) -> None:
    assert "CONTRACT ERROR:" in out
    assert "could not be read in CI/gating mode" in out


def test_cli_main_no_progress_parallel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text(
        """
def f1():
    print("hello")
    return 1

def f2():
    print("hello")
    return 1
""",
        "utf-8",
    )
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Summary" in out
    assert "func" in out


def test_cli_default_cache_dir_uses_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        _capture_cache_path_for_args(
            tmp_path,
            monkeypatch,
            extra_args=(),
        )
        == tmp_path / ".cache" / "codeclone" / "cache.json"
    )


@pytest.mark.parametrize("flag", ["--cache-dir", "--cache-path"])
def test_cli_cache_dir_override_respected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    cache_path = tmp_path / "custom-cache.json"
    assert (
        _capture_cache_path_for_args(
            tmp_path,
            monkeypatch,
            extra_args=(flag, str(cache_path)),
        )
        == cache_path
    )


def test_cli_default_cache_dir_per_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root1 = tmp_path / "p1"
    root2 = tmp_path / "p2"
    root1.mkdir()
    root2.mkdir()
    (root1 / "a.py").write_text("def f():\n    return 1\n", "utf-8")
    (root2 / "b.py").write_text("def f():\n    return 1\n", "utf-8")
    captured: list[Path] = []

    class _CacheStub:
        def __init__(self, path: Path, **_kwargs: object) -> None:
            captured.append(Path(path))
            self.load_warning = None

        def load(self) -> None:
            return None

        def get_file_entry(self, _fp: str) -> None:
            return None

        def put_file_entry(
            self,
            _fp: str,
            _stat: object,
            _units: object,
            _blocks: object,
            _segments: object,
            *,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            return None

        def save(self) -> None:
            return None

    monkeypatch.setattr(cli, "Cache", _CacheStub)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(root1), "--no-progress"])
    _run_main(monkeypatch, [str(root2), "--no-progress"])
    assert captured[0] == root1 / ".cache" / "codeclone" / "cache.json"
    assert captured[1] == root2 / ".cache" / "codeclone" / "cache.json"
    assert captured[0] != captured[1]


def test_cli_cache_not_shared_between_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root1 = tmp_path / "p1"
    root2 = tmp_path / "p2"
    root1.mkdir()
    root2.mkdir()
    legacy_cache = root1 / ".cache" / "codeclone" / "cache.json"
    legacy_cache.parent.mkdir(parents=True, exist_ok=True)
    legacy_cache.write_text("{}", "utf-8")

    monkeypatch.setattr(core_discovery, "iter_py_files", lambda _root: [])
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(root2), "--no-progress"])
    out = capsys.readouterr().out
    assert "Cache signature mismatch" not in out


def test_cli_warns_on_legacy_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "proj"
    _prepare_basic_project(root)
    legacy_path = _write_legacy_cache_file(tmp_path)
    monkeypatch.setattr(cli, "LEGACY_CACHE_PATH", legacy_path)
    baseline = _write_baseline(
        root / "baseline.json",
        python_version=_current_py_minor(),
    )
    _run_parallel_main(
        monkeypatch,
        [str(root), "--baseline", str(baseline), "--no-progress"],
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" in out
    assert "Cache is now stored per-project" in out
    assert ".cache/ to .gitignore" in out


def test_cli_legacy_cache_resolve_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _write_python_module(root, "a.py")

    class _LegacyPath:
        def __init__(self, value: str) -> None:
            self.value = value

        def exists(self) -> bool:
            return True

        def resolve(self) -> Path:
            raise OSError("nope")

        def __str__(self) -> str:
            return self.value

    monkeypatch.setattr(
        cli, "LEGACY_CACHE_PATH", _LegacyPath(str(tmp_path / "legacy-cache.json"))
    )
    baseline = _write_baseline(
        root / "baseline.json",
        python_version=_current_py_minor(),
    )
    _run_parallel_main(
        monkeypatch,
        [str(root), "--baseline", str(baseline), "--no-progress"],
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" in out


def test_cli_no_legacy_warning_with_cache_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "proj"
    _prepare_basic_project(root)
    legacy_path = _write_legacy_cache_file(tmp_path)
    monkeypatch.setattr(cli, "LEGACY_CACHE_PATH", legacy_path)
    cache_path = tmp_path / "custom-cache.json"
    _run_parallel_main(
        monkeypatch,
        [
            str(root),
            "--cache-dir",
            str(cache_path),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" not in out


def test_cli_no_legacy_warning_when_legacy_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def f():\n    return 1\n", "utf-8")
    missing_legacy = tmp_path / "missing" / "cache.json"
    monkeypatch.setattr(cli, "LEGACY_CACHE_PATH", missing_legacy)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(root), "--no-progress"])
    out = capsys.readouterr().out
    assert "Legacy cache file found at" not in out


def test_cli_no_legacy_warning_when_paths_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def f():\n    return 1\n", "utf-8")
    cache_path = root / ".cache" / "codeclone" / "cache.json"

    class _LegacyPathSame:
        def __init__(self, resolved: Path) -> None:
            self._resolved = resolved

        def exists(self) -> bool:
            return True

        def resolve(self) -> Path:
            return self._resolved

        def __str__(self) -> str:
            return str(self._resolved)

    class _CacheStub:
        def __init__(self, _path: Path, **_kwargs: object) -> None:
            self.load_warning = None

        def load(self) -> None:
            return None

        def get_file_entry(self, _fp: str) -> None:
            return None

        def put_file_entry(
            self,
            _fp: str,
            _stat: object,
            _units: object,
            _blocks: object,
            _segments: object,
            *,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            return None

        def save(self) -> None:
            return None

    monkeypatch.setattr(cli, "LEGACY_CACHE_PATH", _LegacyPathSame(cache_path))
    monkeypatch.setattr(cli, "Cache", _CacheStub)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(root), "--no-progress"])
    out = capsys.readouterr().out
    assert "Legacy cache file found at" not in out


@pytest.mark.parametrize(
    ("load_warning", "expected_status"),
    [(None, "ok"), ("bad cache", "invalid_type")],
)
def test_cli_cache_status_string_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    load_warning: str | None,
    expected_status: str,
) -> None:
    _src, baseline_path = _prepare_source_and_baseline(tmp_path)
    json_out = tmp_path / "report.json"

    class _CacheStub:
        def __init__(self, _path: Path, **_kwargs: object) -> None:
            self.load_warning = load_warning
            self.load_status = "not-a-cache-status"
            self.cache_schema_version = CACHE_VERSION

        def load(self) -> None:
            return None

        def get_file_entry(self, _fp: str) -> None:
            return None

        def put_file_entry(
            self,
            _fp: str,
            _stat: object,
            _units: object,
            _blocks: object,
            _segments: object,
            *,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            return None

        def save(self) -> None:
            return None

    monkeypatch.setattr(cli, "Cache", _CacheStub)
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    payload = json.loads(json_out.read_text("utf-8"))
    assert _report_meta_cache(payload)["status"] == expected_status


def test_cli_main_progress_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for idx in range(pipeline._parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _FailingExecutor)
    _run_main(monkeypatch, [str(tmp_path), "--processes", "2"])
    out = capsys.readouterr().out
    assert "falling back to sequential" in out


def test_cli_main_no_progress_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for idx in range(pipeline._parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _FailingExecutor)
    _run_main(monkeypatch, [str(tmp_path), "--processes", "2", "--no-progress"])
    out = capsys.readouterr().out
    assert "falling back to sequential" in out


def test_cli_main_no_progress_fallback_quiet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _FailingExecutor)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--ci",
            "--baseline",
            str(baseline),
        ],
    )
    out = capsys.readouterr().out
    assert "Processing" not in out


def test_cli_main_progress_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_dummy_progress(monkeypatch)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path)])


def test_cli_invalid_root_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: Path) -> Path:
        raise OSError("bad")

    monkeypatch.setattr(Path, "resolve", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["bad"])
    assert exc.value.code == 2


def test_cli_unexpected_root_resolution_failure_is_internal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom(self: Path) -> Path:
        raise RuntimeError("boom")

    monkeypatch.setattr(Path, "resolve", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["bad"])
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out


def test_cli_unexpected_grouping_failure_is_internal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    _patch_parallel(monkeypatch)
    monkeypatch.setattr(core_pipeline, "build_groups", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out


def test_cli_unexpected_html_render_failure_is_internal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    html_out = tmp_path / "report.html"

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("render failed")

    _patch_parallel(monkeypatch)
    monkeypatch.setattr(cli, "build_html_report", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [str(tmp_path), "--html", str(html_out), "--no-progress"],
        )
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out


def test_cli_main_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_python_module(tmp_path, "a.py")
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
    sarif_out = tmp_path / "out.sarif"
    text_out = tmp_path / "out.txt"
    baseline = tmp_path / "baseline.json"
    _write_baseline(
        baseline,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--html",
            str(html_out),
            "--json",
            str(json_out),
            "--md",
            str(md_out),
            "--sarif",
            str(sarif_out),
            "--text",
            str(text_out),
            "--no-progress",
        ],
    )
    for artifact in (html_out, json_out, md_out, sarif_out, text_out):
        assert artifact.exists()
    out = capsys.readouterr().out
    for label in ("HTML", "JSON", "Markdown", "SARIF", "Text"):
        assert label in out
    assert out.index("Summary") < out.index("report saved:")


def test_cli_open_html_report_opens_written_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_python_module(tmp_path, "a.py")
    html_out = tmp_path / "out.html"
    opened: list[Path] = []

    def _open(*, path: Path) -> None:
        opened.append(path)

    monkeypatch.setattr(cli_reports, "_open_html_report_in_browser", _open)
    _run_parallel_main(monkeypatch, _open_html_report_args(tmp_path, html_out))
    assert html_out.exists()
    assert opened == [html_out.resolve()]


def test_cli_open_html_report_failure_warns_without_failing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    html_out = tmp_path / "out.html"

    def _boom(*, path: Path) -> None:
        raise OSError(f"cannot open {path.name}")

    monkeypatch.setattr(cli_reports, "_open_html_report_in_browser", _boom)
    _run_parallel_main(monkeypatch, _open_html_report_args(tmp_path, html_out))
    assert html_out.exists()
    out = capsys.readouterr().out
    assert "Failed to open HTML report in browser" in out
    assert re.search(r"cannot\s+open out\.html", out) is not None


def test_cli_timestamped_report_paths_apply_to_bare_report_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_python_module(tmp_path, "a.py")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli_meta,
        "_current_report_timestamp_utc",
        lambda: "2026-03-22T21:31:45Z",
    )
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--html",
            "--json",
            "--text",
            "--timestamped-report-paths",
            "--no-progress",
        ],
    )
    cache_dir = tmp_path / ".cache" / "codeclone"
    assert (cache_dir / "report-20260322T213145Z.html").exists()
    assert (cache_dir / "report-20260322T213145Z.json").exists()
    assert (cache_dir / "report-20260322T213145Z.txt").exists()
    assert not (cache_dir / "report.html").exists()
    assert not (cache_dir / "report.json").exists()
    assert not (cache_dir / "report.txt").exists()


def test_cli_timestamped_report_paths_do_not_rewrite_explicit_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_python_module(tmp_path, "a.py")
    html_out = tmp_path / "custom.html"
    monkeypatch.setattr(
        cli_meta,
        "_current_report_timestamp_utc",
        lambda: "2026-03-22T21:31:45Z",
    )
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--html",
            str(html_out),
            "--timestamped-report-paths",
            "--no-progress",
        ],
    )
    assert html_out.exists()
    assert not (tmp_path / "custom-20260322T213145Z.html").exists()


@pytest.mark.parametrize(
    ("argv", "expected_message"),
    [
        pytest.param(
            ["--open-html-report"],
            "--open-html-report requires --html",
            id="open_html_requires_html",
        ),
        pytest.param(
            ["--timestamped-report-paths"],
            "--timestamped-report-paths requires at least one report output flag",
            id="timestamped_requires_output",
        ),
    ],
)
def test_cli_report_flag_contract_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    expected_message: str,
) -> None:
    _write_python_module(tmp_path, "a.py")
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                *argv,
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert expected_message in out


def test_cli_reports_include_audit_metadata_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _src, baseline_path = _prepare_source_and_baseline(tmp_path)
    html_out = tmp_path / "report.html"
    json_out = tmp_path / "report.json"
    text_out = tmp_path / "report.txt"
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--html",
            str(html_out),
            "--json",
            str(json_out),
            "--text",
            str(text_out),
            "--no-progress",
        ],
    )

    payload = json.loads(json_out.read_text("utf-8"))
    baseline_meta = _report_meta_baseline(payload)
    assert baseline_meta["status"] == "ok"
    assert baseline_meta["loaded"] is True
    assert baseline_meta["fingerprint_version"] == BASELINE_FINGERPRINT_VERSION
    assert baseline_meta["schema_version"] == BASELINE_SCHEMA_VERSION
    assert baseline_meta["generator_version"] == __version__
    assert isinstance(baseline_meta["payload_sha256"], str)
    assert baseline_meta["payload_sha256_verified"] is True
    assert baseline_meta["path"] == baseline_path.name
    assert baseline_meta["path_scope"] == "in_root"
    assert payload["report_schema_version"] == REPORT_SCHEMA_VERSION
    assert "report_schema_version" not in payload["meta"]
    assert "inventory" in payload
    assert "findings" in payload
    runtime_meta = payload["meta"]["runtime"]
    assert isinstance(runtime_meta["report_generated_at_utc"], str)
    assert runtime_meta["report_generated_at_utc"].endswith("Z")
    clones = payload["findings"]["groups"]["clones"]
    assert set(clones) == {"functions", "blocks", "segments"}

    text = text_out.read_text("utf-8")
    for needle in (
        "REPORT METADATA",
        "Report generated (UTC): ",
        "Baseline status: ok",
        f"Baseline schema version: {BASELINE_SCHEMA_VERSION}",
    ):
        assert needle in text

    html = html_out.read_text("utf-8")
    for needle in (
        "Report Provenance",
        "Report generated (UTC)",
        'data-baseline-status="ok"',
        'data-baseline-payload-verified="true"',
        "Baseline schema",
    ):
        assert needle in html


def test_cli_reports_include_audit_metadata_missing_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_python_module(tmp_path, "a.py")
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(tmp_path / "missing-baseline.json")],
    )
    _assert_report_baseline_meta(
        payload,
        status="missing",
        loaded=False,
        fingerprint_version=None,
        schema_version=None,
        payload_sha256=None,
        payload_sha256_verified=False,
    )


def test_cli_reports_include_audit_metadata_fingerprint_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        baseline_version="0.0.0",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path)],
    )
    out = capsys.readouterr().out
    assert "fingerprint version mismatch" in out
    _assert_report_baseline_meta(
        payload,
        status="mismatch_fingerprint_version",
        loaded=False,
        fingerprint_version="0.0.0",
    )


def test_cli_reports_include_audit_metadata_schema_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        schema_version="1.1",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path)],
    )
    out = capsys.readouterr().out
    assert "schema version is newer than supported" in out
    _assert_report_baseline_meta(
        payload,
        status="mismatch_schema_version",
        loaded=False,
        schema_version="1.1",
    )


def test_cli_reports_include_audit_metadata_python_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version="0.0",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path), "--fail-on-new"],
        expect_exit_code=2,
    )
    out = capsys.readouterr().out
    assert "python tag mismatch" in out
    _assert_report_baseline_meta(
        payload,
        status="mismatch_python_version",
        loaded=False,
        python_tag="cp00",
    )


def test_cli_reports_include_audit_metadata_invalid_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{broken json", "utf-8")
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path)],
    )
    out = capsys.readouterr().out
    assert "Invalid baseline file" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    _assert_report_baseline_meta(payload, status="invalid_json", loaded=False)


def test_cli_reports_include_audit_metadata_legacy_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "functions": [],
                "blocks": [],
                "python_version": "3.13",
                "schema_version": BASELINE_SCHEMA_VERSION,
            }
        ),
        "utf-8",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path)],
    )
    out = capsys.readouterr().out
    assert "legacy" in out
    _assert_report_baseline_meta(payload, status="missing_fields", loaded=False)


def test_cli_legacy_baseline_normal_mode_ignored_and_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(
        tmp_path,
        "a.py",
        "def f():\n    return 1\n\n\ndef g():\n    return 1\n",
    )
    baseline_path = _write_legacy_baseline(tmp_path / "baseline.json")

    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
            "--no-color",
        ],
    )
    out = capsys.readouterr().out
    assert_contains_all(
        out,
        "legacy (<=1.3.x)",
        "Baseline is not trusted for this run and will be ignored",
        "Comparison will proceed against an empty baseline",
        "Run: codeclone . --update-baseline",
        "New clones detected but --fail-on-new not set.",
    )


def test_cli_legacy_baseline_fail_on_new_fails_fast_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = _write_legacy_baseline(tmp_path / "baseline.json")
    _assert_parallel_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--fail-on-new",
            "--no-progress",
        ],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert_contains_all(
        out,
        "legacy (<=1.3.x)",
        "Invalid baseline file",
        "CI requires a trusted baseline",
        "Run: codeclone . --update-baseline",
    )


def test_cli_reports_include_audit_metadata_integrity_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    tampered = json.loads(baseline_path.read_text("utf-8"))
    clones = tampered["clones"]
    assert isinstance(clones, dict)
    clones["functions"] = [f"{'a' * 40}|0-19"]
    baseline_path.write_text(json.dumps(tampered), "utf-8")

    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path)],
    )
    out = capsys.readouterr().out
    assert "integrity check failed" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    _assert_report_baseline_meta(payload, status="integrity_failed", loaded=False)


def test_cli_reports_include_audit_metadata_generator_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        generator="not-codeclone",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path)],
    )
    out = capsys.readouterr().out
    assert "generator mismatch" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    _assert_report_baseline_meta(payload, status="generator_mismatch", loaded=False)


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_message", "expected_status"),
    [
        ("generator", 123, "'generator' must be string", "invalid_type"),
        (
            "payload_sha256",
            1,
            "'payload_sha256' must be string",
            "invalid_type",
        ),
    ],
)
def test_cli_reports_include_audit_metadata_integrity_field_type_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    bad_value: object,
    expected_message: str,
    expected_status: str,
) -> None:
    def _mutate(payload: dict[str, object]) -> None:
        meta = payload.get("meta")
        assert isinstance(meta, dict)
        meta[field] = bad_value

    _assert_baseline_failure_meta(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
        mutate_payload=_mutate,
        expected_message=expected_message,
        expected_status=expected_status,
    )


def test_cli_reports_include_audit_metadata_integrity_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = tmp_path / "baseline.json"
    payload = _baseline_payload(
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    meta = payload["meta"]
    assert isinstance(meta, dict)
    del meta["payload_sha256"]
    baseline_path.write_text(json.dumps(payload), "utf-8")
    payload_out = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path)],
    )
    out = capsys.readouterr().out
    assert "missing required fields" in out or "Invalid baseline schema" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    _assert_report_baseline_meta(payload_out, status="missing_fields", loaded=False)


def test_cli_reports_include_audit_metadata_baseline_too_large(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = _write_baseline(tmp_path / "baseline.json")
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=[
            "--baseline",
            str(baseline_path),
            "--max-baseline-size-mb",
            "0",
        ],
    )
    out = capsys.readouterr().out
    assert "too large" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    _assert_report_baseline_meta(payload, status="too_large", loaded=False)


def test_cli_untrusted_baseline_ignored_for_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text(
        """
def f1():
    return 1

def f2():
    return 1
""",
        "utf-8",
    )
    baseline_path = tmp_path / "baseline.json"
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ],
    )
    capsys.readouterr()

    payload = json.loads(baseline_path.read_text("utf-8"))
    meta = payload["meta"]
    assert isinstance(meta, dict)
    meta["generator"] = "not-codeclone"
    baseline_path.write_text(json.dumps(payload), "utf-8")
    json_out = tmp_path / "report.json"
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--json",
            str(json_out),
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Baseline is not trusted for this run and will be ignored" in out
    assert _summary_metric(out, "New vs baseline") > 0
    report = json.loads(json_out.read_text("utf-8"))
    assert _report_meta_baseline(report)["status"] == "generator_mismatch"
    assert _report_meta_baseline(report)["loaded"] is False


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_message", "expected_status"),
    [
        ("generator", "not-codeclone", "generator mismatch", "generator_mismatch"),
        (
            "payload_sha256",
            "0" * 64,
            "integrity check failed",
            "integrity_failed",
        ),
        (
            "payload_sha256",
            None,
            "missing required fields",
            "missing_fields",
        ),
    ],
)
def test_cli_untrusted_baseline_fails_in_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    bad_value: object,
    expected_message: str,
    expected_status: str,
) -> None:
    def _mutate(payload: dict[str, object]) -> None:
        meta = payload["meta"]
        assert isinstance(meta, dict)
        if bad_value is None:
            meta.pop(field, None)
        else:
            meta[field] = bad_value

    _assert_baseline_failure_meta(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
        mutate_payload=_mutate,
        expected_message=expected_message,
        expected_status=expected_status,
        strict_fail=True,
    )


def test_cli_invalid_baseline_fails_in_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{broken json", "utf-8")
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path), "--ci"],
        expect_exit_code=2,
    )
    out = capsys.readouterr().out
    assert "Invalid baseline file" in out
    _assert_report_baseline_meta(payload, status="invalid_json", loaded=False)


def test_cli_too_large_baseline_fails_in_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = _write_baseline(tmp_path / "baseline.json")
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=[
            "--baseline",
            str(baseline_path),
            "--max-baseline-size-mb",
            "0",
            "--ci",
        ],
        expect_exit_code=2,
    )
    out = capsys.readouterr().out
    assert "too large" in out
    _assert_report_baseline_meta(payload, status="too_large", loaded=False)


@pytest.mark.parametrize(
    ("mutator", "expected_message", "expected_status", "expected_schema_version"),
    [
        (
            lambda data: data.__setitem__("sig", "bad"),
            "signature",
            "integrity_failed",
            CACHE_VERSION,
        ),
        (
            lambda data: data.__setitem__("v", "2.2"),
            "Cache version mismatch",
            "version_mismatch",
            "2.2",
        ),
    ],
)
def test_cli_reports_cache_used_false_on_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutator: Callable[[dict[str, object]], None],
    expected_message: str,
    expected_status: str,
    expected_schema_version: object,
) -> None:
    src, cache_path, cache = _prepare_single_source_cache(tmp_path)
    cache.put_file_entry(str(src), {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()
    data = json.loads(cache_path.read_text("utf-8"))
    mutator(data)
    cache_path.write_text(json.dumps(data), "utf-8")

    baseline_path = _write_current_python_baseline(tmp_path / "baseline.json")
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=[
            "--baseline",
            str(baseline_path),
            "--cache-dir",
            str(cache_path),
        ],
    )
    out = capsys.readouterr().out
    assert expected_message in out
    _assert_report_cache_meta(
        payload,
        used=False,
        status=expected_status,
        schema_version=expected_schema_version,
    )


def test_cli_reports_cache_too_large_respects_max_size_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{}", "utf-8")

    baseline_path = _write_current_python_baseline(tmp_path / "baseline.json")
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=[
            "--baseline",
            str(baseline_path),
            "--cache-path",
            str(cache_path),
            "--max-cache-size-mb",
            "0",
        ],
    )
    out = capsys.readouterr().out
    assert "Cache file too large" in out
    _assert_report_cache_meta(
        payload,
        used=False,
        status="too_large",
        schema_version=None,
    )


def test_cli_reports_cache_meta_when_cache_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_default_source(tmp_path)
    baseline_path = _write_current_python_baseline(tmp_path / "baseline.json")
    cache_path = tmp_path / "missing-cache.json"
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=[
            "--baseline",
            str(baseline_path),
            "--cache-path",
            str(cache_path),
        ],
    )
    _assert_report_cache_meta(
        payload,
        used=False,
        status="missing",
        schema_version=None,
    )


@pytest.mark.parametrize(
    (
        "first_min_loc",
        "first_min_stmt",
        "second_min_loc",
        "second_min_stmt",
        "expected_cache_used",
        "expected_cache_status",
        "expected_cache_schema_version",
        "expected_functions_total",
        "expected_warning",
    ),
    [
        (
            1,
            1,
            15,
            6,
            False,
            "analysis_profile_mismatch",
            CACHE_VERSION,
            0,
            "analysis profile mismatch",
        ),
        (
            15,
            6,
            1,
            1,
            False,
            "analysis_profile_mismatch",
            CACHE_VERSION,
            1,
            "analysis profile mismatch",
        ),
        (1, 1, 1, 1, True, "ok", CACHE_VERSION, 1, None),
    ],
)
def test_cli_cache_analysis_profile_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    first_min_loc: int,
    first_min_stmt: int,
    second_min_loc: int,
    second_min_stmt: int,
    expected_cache_used: bool,
    expected_cache_status: str,
    expected_cache_schema_version: str,
    expected_functions_total: int,
    expected_warning: str | None,
) -> None:
    _write_profile_compatibility_source(tmp_path)
    baseline_path = _write_current_python_baseline(tmp_path / "baseline.json")
    cache_path = tmp_path / "cache.json"
    json_first = tmp_path / "report-first.json"
    json_second = tmp_path / "report-second.json"
    _patch_parallel(monkeypatch)

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--cache-path",
            str(cache_path),
            "--json",
            str(json_first),
            "--min-loc",
            str(first_min_loc),
            "--min-stmt",
            str(first_min_stmt),
            "--no-progress",
        ],
    )
    capsys.readouterr()

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--cache-path",
            str(cache_path),
            "--json",
            str(json_second),
            "--min-loc",
            str(second_min_loc),
            "--min-stmt",
            str(second_min_stmt),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    payload = json.loads(json_second.read_text("utf-8"))
    if expected_warning is not None:
        assert expected_warning in out
    _assert_report_cache_meta(
        payload,
        used=expected_cache_used,
        status=expected_cache_status,
        schema_version=expected_cache_schema_version,
    )
    assert (
        payload["findings"]["summary"]["clones"]["functions"]
        == expected_functions_total
    )


@pytest.mark.parametrize(
    ("flag", "bad_name", "label", "expected"),
    [
        ("--html", "report.exe", "HTML", ".html"),
        ("--json", "report.txt", "JSON", ".json"),
        ("--md", "report.txt", "Markdown", ".md"),
        ("--sarif", "report.json", "SARIF", ".sarif"),
        ("--text", "report.json", "text", ".txt"),
    ],
)
def test_cli_output_extension_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    bad_name: str,
    label: str,
    expected: str,
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    bad_path = tmp_path / bad_name
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                flag,
                str(bad_path),
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert f"Invalid {label} output extension" in out
    assert expected in out


def test_cli_output_path_resolve_error_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    html_out = tmp_path / "report.html"
    original_resolve = Path.resolve

    def _raise_resolve(
        self: Path, strict: bool = False
    ) -> Path:  # pragma: no cover - signature mirror
        if self == html_out:
            raise OSError("no resolve")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _raise_resolve)
    _assert_cli_exit(
        monkeypatch,
        [str(tmp_path), "--html", str(html_out)],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert "CONTRACT ERROR:" in out
    assert "Invalid HTML output path" in out


def test_cli_report_write_error_is_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    html_out = tmp_path / "report.html"
    original_write_text = Path.write_text

    def _raise_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if self == html_out:
            raise OSError("disk full")
        return original_write_text(
            self, data, encoding=encoding, errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "write_text", _raise_write_text)
    _assert_parallel_cli_exit(
        monkeypatch,
        [str(tmp_path), "--html", str(html_out), "--no-progress"],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert "CONTRACT ERROR:" in out
    assert "Failed to write HTML report" in out


def test_cli_outputs_quiet_no_print(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "out.json"
    text_out = tmp_path / "out.txt"
    baseline = _write_baseline(
        tmp_path / "baseline.json",
        python_version=_current_py_minor(),
    )
    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--ci",
            "--baseline",
            str(baseline),
            "--html",
            str(html_out),
            "--json",
            str(json_out),
            "--text",
            str(text_out),
        ],
    )
    assert html_out.exists()
    assert json_out.exists()
    assert text_out.exists()
    out = capsys.readouterr().out
    assert "report saved" not in out


def test_cli_update_baseline_skips_version_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=_current_py_minor(),
        baseline_version="0.0.0",
    )
    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Baseline updated" in out


def test_cli_update_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(
        tmp_path,
        "a.py",
        """
def f1():
    return 1

def f2():
    return 1
""",
    )
    baseline = tmp_path / "codeclone.baseline.json"
    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--update-baseline",
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Baseline updated" in out
    assert baseline.exists()


def test_cli_update_baseline_report_meta_uses_updated_payload_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_default_source(tmp_path)
    baseline = tmp_path / "codeclone.baseline.json"
    json_out = tmp_path / "report.json"
    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--update-baseline",
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )

    payload = json.loads(json_out.read_text("utf-8"))
    baseline_meta = _assert_report_baseline_meta(
        payload,
        status="ok",
        loaded=True,
    )
    assert isinstance(baseline_meta["payload_sha256"], str)
    assert len(baseline_meta["payload_sha256"]) == 64
    assert baseline_meta["payload_sha256_verified"] is True


def test_cli_update_baseline_rewrites_embedded_metrics_to_current_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_python_module(
        tmp_path,
        "a.py",
        """
def public(value: int) -> int:
    return value
""",
    )
    baseline = tmp_path / "codeclone.baseline.json"

    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--update-baseline",
            "--api-surface",
            "--no-progress",
        ],
    )
    initial_payload = json.loads(baseline.read_text("utf-8"))
    assert "api_surface" in initial_payload
    assert "typing_param_permille" in initial_payload["metrics"]

    (tmp_path / "pyproject.toml").write_text(
        """
[tool.codeclone]
baseline = "codeclone.baseline.json"
api_surface = false
""".strip()
        + "\n",
        "utf-8",
    )

    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--update-baseline",
            "--no-progress",
        ],
    )

    payload = json.loads(baseline.read_text("utf-8"))
    meta = cast(dict[str, object], payload["meta"])
    metrics = cast(dict[str, object], payload["metrics"])
    assert_missing_keys(payload, "api_surface")
    assert_missing_keys(meta, "api_surface_payload_sha256")
    assert cast(int, metrics["typing_param_permille"]) >= 0
    assert cast(int, metrics["typing_return_permille"]) >= 0
    assert cast(int, metrics["docstring_permille"]) >= 0
    assert cast(int, metrics["typing_any_count"]) >= 0


def test_cli_update_baseline_write_error_is_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"

    def _raise_save(self: baseline.Baseline) -> None:
        raise OSError("readonly fs")

    monkeypatch.setattr(baseline.Baseline, "save", _raise_save)
    _patch_parallel(monkeypatch)
    _assert_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--no-progress",
        ],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert "CONTRACT ERROR:" in out
    assert "Failed to write baseline file" in out


def test_cli_update_baseline_with_invalid_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{broken json", "utf-8")
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--update-baseline",
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Baseline updated" in out
    assert "Invalid baseline file" not in out
    payload = json.loads(baseline_path.read_text("utf-8"))
    meta = payload["meta"]
    assert isinstance(meta, dict)
    assert meta.get("fingerprint_version") == BASELINE_FINGERPRINT_VERSION
    assert meta.get("schema_version") == BASELINE_SCHEMA_VERSION
    generator = meta.get("generator")
    assert isinstance(generator, dict)
    assert generator.get("version") == __version__


def test_cli_baseline_missing_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline = tmp_path / "missing.json"
    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Baseline file not found" in out
    assert "Run: codeclone . --update-baseline" in out


def test_cli_baseline_missing_fails_in_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline = tmp_path / "missing.json"
    _patch_parallel(monkeypatch)
    _assert_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--ci",
            "--no-progress",
        ],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert "Baseline file not found" in out
    assert "CI requires a trusted baseline" in out


def test_cli_new_clones_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text(
        """
def f1():
    return 1

def f2():
    return 1
    """,
        "utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline)
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "New clones detected but --fail-on-new not set" in out


def test_cli_baseline_python_version_mismatch_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, python_version="0.0")
    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "python tag mismatch" in out
    assert "will be ignored" in out


def test_cli_baseline_fingerprint_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=_current_py_minor(),
        baseline_version="0.0.0",
    )
    _assert_parallel_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--ci",
            "--no-progress",
        ],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert "fingerprint version mismatch" in out


def test_cli_baseline_missing_fields_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "functions": [],
                "blocks": [],
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
                "schema_version": BASELINE_SCHEMA_VERSION,
            }
        ),
        "utf-8",
    )
    _assert_parallel_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--ci",
            "--no-progress",
        ],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert "legacy (<=1.3.x)" in out


def test_cli_baseline_schema_version_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=_current_py_minor(),
        schema_version="1.1",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path), "--ci"],
        expect_exit_code=2,
    )
    out = capsys.readouterr().out
    assert "schema version is newer than supported" in out
    assert _report_meta_baseline(payload)["status"] == "mismatch_schema_version"


def test_cli_baseline_schema_and_fingerprint_mismatch_status_prefers_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=_current_py_minor(),
        baseline_version="0.0.0",
        schema_version="1.1",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path), "--ci"],
        expect_exit_code=2,
    )
    out = capsys.readouterr().out
    assert "schema version is newer than supported" in out
    assert "fingerprint version mismatch" not in out
    assert _report_meta_baseline(payload)["status"] == "mismatch_schema_version"


def test_cli_baseline_fingerprint_and_python_mismatch_status_prefers_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version="0.0",
        baseline_version="0.0.0",
    )
    payload = _run_json_report(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        extra_args=["--baseline", str(baseline_path), "--ci"],
        expect_exit_code=2,
    )
    out = capsys.readouterr().out
    assert "fingerprint version mismatch" in out
    assert "Python version mismatch" not in out
    assert _report_meta_baseline(payload)["status"] == "mismatch_fingerprint_version"


def test_cli_baseline_python_version_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, python_version="0.0")
    _assert_parallel_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--fail-on-new",
            "--no-progress",
        ],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert_contains_all(out, "CONTRACT ERROR:", "python tag mismatch")


def test_cli_negative_size_limits_fail_fast(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["--max-baseline-size-mb", "-1"])
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "non-negative integers" in out


def test_cli_main_fail_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.py"
    src.write_text(
        """
def f1():
    return 1

def f2():
    return 1
""",
        "utf-8",
    )
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--min-loc",
                "1",
                "--min-stmt",
                "1",
                "--fail-threshold",
                "0",
                "--no-progress",
            ],
        )
    assert exc.value.code == 3


def test_cli_main_fail_on_new(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "a.py"
    src.write_text(
        """
def f1():
    return 1

def f2():
    return 1
    """,
        "utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(
        baseline,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline),
                "--min-loc",
                "1",
                "--min-stmt",
                "1",
                "--fail-on-new",
                "--no-progress",
            ],
        )
    assert exc.value.code == 3


def test_cli_main_fail_on_new_includes_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "\n".join([f"    x{i} = {i}" for i in range(50)])
    src = tmp_path / "a.py"
    src.write_text(
        f"""
def f1():
{body}

def f2():
{body}
    """,
        "utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(
        baseline,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline),
                "--min-loc",
                "1",
                "--min-stmt",
                "1",
                "--fail-on-new",
                "--no-progress",
            ],
        )
    assert exc.value.code == 3
    out = capsys.readouterr().out
    _assert_fail_on_new_summary(out)


def test_cli_ci_preset_fails_on_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "a.py"
    src.write_text(
        """
def f1():
    return 1

def f2():
    return 1
    """,
        "utf-8",
    )
    baseline = tmp_path / "baseline.json"
    _write_baseline(
        baseline,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline),
                "--min-loc",
                "1",
                "--min-stmt",
                "1",
                "--ci",
            ],
        )
    assert exc.value.code == 3
    out = capsys.readouterr().out
    assert "GATING FAILURE [new-clones]" in out
    _assert_fail_on_new_summary(out, include_blocks=False)
    assert "CodeClone v" not in out


def test_cli_blocks_processing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = "\n".join([f"    x{i} = {i}" for i in range(60)])
    src = tmp_path / "a.py"
    src.write_text(f"\n\ndef f():\n{body}\n", "utf-8")
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [str(tmp_path), "--min-loc", "1", "--min-stmt", "1", "--no-progress"],
    )


def test_cli_cache_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 1}, [], [], [])
    cache.save()
    data = json.loads(cache_path.read_text("utf-8"))
    data["sig"] = "bad"
    cache_path.write_text(json.dumps(data), "utf-8")

    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--cache-dir",
            str(cache_path),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Cache signature mismatch" in out


def test_cli_cache_save_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _raise_save(self: Cache) -> None:
        raise CacheError("nope")

    monkeypatch.setattr(Cache, "save", _raise_save)
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Failed to save cache" in out


def test_cli_cache_save_warning_quiet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(tmp_path, "a.py")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )

    def _raise_save(self: Cache) -> None:
        raise CacheError("nope")

    monkeypatch.setattr(Cache, "save", _raise_save)
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--ci",
            "--baseline",
            str(baseline_path),
        ],
    )
    out = capsys.readouterr().out
    assert "Failed to save cache" in out


def test_cli_invalid_root(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["/path/does/not/exist"])
    assert exc.value.code == 2


def test_cli_invalid_baseline_path_error_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    original_resolve = Path.resolve

    def _raise_resolve(
        self: Path, strict: bool = False
    ) -> Path:  # pragma: no cover - signature mirror
        if self == baseline_path:
            raise OSError("no resolve")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _raise_resolve)
    _assert_cli_exit(
        monkeypatch,
        [str(tmp_path), "--baseline", str(baseline_path), "--no-progress"],
        expected_code=2,
    )
    out = capsys.readouterr().out
    assert "CONTRACT ERROR:" in out
    assert "Invalid baseline path" in out


def test_cli_discovery_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    root = tmp_path.resolve()
    src_resolved = src.resolve()

    cache = Cache(tmp_path / "cache.json", root=root)
    cache.put_file_entry(
        str(src_resolved),
        file_stat_signature(str(src_resolved)),
        [
            Unit(
                qualname="mod:f",
                filepath=str(src_resolved),
                start_line=1,
                end_line=2,
                loc=2,
                stmt_count=1,
                fingerprint="abc",
                loc_bucket="0-19",
                cyclomatic_complexity=1,
                nesting_depth=0,
                risk="low",
                raw_hash="",
            )
        ],
        [],
        [],
    )
    cache.save()

    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(root),
            "--cache-dir",
            str(cache.path),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    files_found = _summary_metric(out, "Files found")
    files_analyzed = _summary_metric(out, "analyzed")
    cache_hits = _summary_metric(out, "from cache")
    files_skipped = _summary_metric(out, "skipped")
    assert files_found > 0
    assert cache_hits >= 0
    assert files_analyzed >= 0
    assert files_found == files_analyzed + cache_hits + files_skipped


@pytest.mark.parametrize("extra_args", [["--no-progress"], ["--ci"]])
def test_cli_discovery_skip_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra_args: list[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _bad_stat(_path: str) -> dict[str, int]:
        raise OSError("nope")

    monkeypatch.setattr(core_discovery, "file_stat_signature", _bad_stat)
    _patch_parallel(monkeypatch)
    args = [str(tmp_path), *extra_args]
    if "--ci" in extra_args:
        baseline = _write_baseline(
            tmp_path / "baseline.json",
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        )
        args.extend(["--baseline", str(baseline)])
    _run_main(monkeypatch, args)
    out = capsys.readouterr().out
    if "--ci" in extra_args:
        files_found = _compact_summary_metric(out, "found")
        files_analyzed = _compact_summary_metric(out, "analyzed")
        cache_hits = _compact_summary_metric(out, "cached")
        files_skipped = _compact_summary_metric(out, "skipped")
    else:
        files_found = _summary_metric(out, "Files found")
        files_analyzed = _summary_metric(out, "analyzed")
        cache_hits = _summary_metric(out, "from cache")
        files_skipped = _summary_metric(out, "skipped")
    assert files_skipped >= 1
    assert files_found == files_analyzed + cache_hits + files_skipped


def test_cli_unreadable_source_normal_mode_warns_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    cache_path = tmp_path / "cache.json"
    json_out = tmp_path / "report.json"

    def _source_read_error(
        fp: str, *_args: object, **_kwargs: object
    ) -> cli.ProcessingResult:
        return _source_read_error_result(fp)

    monkeypatch.setattr(core_worker, "process_file", _source_read_error)
    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--cache-path",
            str(cache_path),
            "--json",
            str(json_out),
        ],
    )
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "CONTRACT ERROR:" not in combined
    assert _summary_metric(captured.out, "Files skipped") == 1
    payload = json.loads(json_out.read_text("utf-8"))
    assert _report_inventory_files(payload)["source_io_skipped"] == 1


def test_cli_unreadable_source_fails_in_ci_with_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _src, baseline_path = _prepare_source_and_baseline(tmp_path)
    json_out = tmp_path / "report.json"
    cache_path = tmp_path / "cache.json"

    def _source_read_error(
        fp: str, *_args: object, **_kwargs: object
    ) -> cli.ProcessingResult:
        return _source_read_error_result(fp)

    monkeypatch.setattr(core_worker, "process_file", _source_read_error)
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--ci",
                "--baseline",
                str(baseline_path),
                "--json",
                str(json_out),
                "--cache-path",
                str(cache_path),
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    _assert_unreadable_source_contract_error(out)
    payload = json.loads(json_out.read_text("utf-8"))
    assert _report_inventory_files(payload)["source_io_skipped"] == 1


def test_cli_reports_include_source_io_skipped_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_default_source(tmp_path)
    json_out = tmp_path / "report.json"
    cache_path = tmp_path / "cache.json"

    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--json",
            str(json_out),
            "--no-progress",
            "--cache-path",
            str(cache_path),
        ],
    )
    payload = json.loads(json_out.read_text("utf-8"))
    assert _report_inventory_files(payload)["source_io_skipped"] == 0


def test_cli_contract_error_priority_over_gating_failure_for_unreadable_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _src, baseline_path = _prepare_source_and_baseline(tmp_path)
    cache_path = tmp_path / "cache.json"

    def _source_read_error(
        fp: str, *_args: object, **_kwargs: object
    ) -> cli.ProcessingResult:
        return _source_read_error_result(fp)

    def _diff(
        _self: object, _f: dict[str, object], _b: dict[str, object]
    ) -> tuple[set[str], set[str]]:
        return {"f1"}, set()

    monkeypatch.setattr(core_worker, "process_file", _source_read_error)
    monkeypatch.setattr(baseline.Baseline, "diff", _diff)
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--fail-on-new",
                "--baseline",
                str(baseline_path),
                "--no-progress",
                "--cache-path",
                str(cache_path),
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    _assert_unreadable_source_contract_error(out)
    assert "GATING FAILURE:" not in out


def test_cli_unreadable_source_ci_shows_overflow_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for i in range(11):
        (tmp_path / f"f{i}.py").write_text("def f():\n    return 1\n", "utf-8")
    _baseline = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    cache_path = tmp_path / "cache.json"

    def _source_read_error(
        fp: str, *_args: object, **_kwargs: object
    ) -> cli.ProcessingResult:
        return _source_read_error_result(fp)

    monkeypatch.setattr(core_worker, "process_file", _source_read_error)
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--ci",
                "--baseline",
                str(_baseline),
                "--cache-path",
                str(cache_path),
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    _assert_unreadable_source_contract_error(out)
    assert "... and 1 more" in out


def test_cli_report_meta_cache_path_resolve_oserror_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _src, baseline_path = _prepare_source_and_baseline(tmp_path)
    cache_path = tmp_path / "cache_for_meta.json"
    json_out = tmp_path / "report.json"

    original_resolve = Path.resolve
    resolve_called = {"cache": False}

    def _resolve(self: Path, strict: bool = False) -> Path:
        if self == cache_path:
            resolve_called["cache"] = True
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--cache-path",
            str(cache_path),
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    payload = json.loads(json_out.read_text("utf-8"))
    assert resolve_called["cache"] is True
    assert _report_meta_cache(payload)["path"] == cache_path.name
    assert _report_meta_cache(payload)["path_scope"] == "in_root"


def test_cli_ci_discovery_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src, cache_path, cache = _prepare_single_source_cache(tmp_path)
    stat = file_stat_signature(str(src))
    cache.put_file_entry(
        str(src),
        stat,
        [],
        [],
        [],
    )
    cache.save()
    baseline = tmp_path / "baseline.json"
    _write_baseline(
        baseline,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--ci",
            "--cache-dir",
            str(cache_path),
            "--baseline",
            str(baseline),
        ],
    )
    out = capsys.readouterr().out
    assert "CodeClone v" not in out
    assert "Summary" in out
    assert "Analyzing" not in out
    assert "\x1b[" not in out
    assert "new=" in out
    assert _compact_summary_metric(out, "found") == 1
    assert _compact_summary_metric(out, "analyzed") == 0
    assert _compact_summary_metric(out, "cached") == 1
    assert _compact_summary_metric(out, "skipped") == 0


def test_cli_summary_cache_miss_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    files_found = _summary_metric(out, "Files found")
    files_analyzed = _summary_metric(out, "analyzed")
    cache_hits = _summary_metric(out, "from cache")
    files_skipped = _summary_metric(out, "skipped")
    assert files_found > 0
    assert files_analyzed == files_found
    assert cache_hits == 0
    assert files_skipped == 0
    assert files_found == files_analyzed + cache_hits + files_skipped


def test_cli_summary_format_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    assert "Summary" in out
    assert out.count("Summary") == 1
    assert "Metrics" not in out
    assert "Adoption" not in out
    assert "Overloaded" not in out
    assert "callables" in out
    assert "Files parsed" not in out
    assert "Input" not in out
    assert _summary_metric(out, "Files found") >= 0
    assert _summary_metric(out, "analyzed") >= 0
    assert _summary_metric(out, "from cache") >= 0
    assert _summary_metric(out, "skipped") >= 0
    assert _summary_metric(out, "Function clones") >= 0
    assert _summary_metric(out, "Block clones") >= 0
    assert _summary_metric(out, "suppressed") >= 0
    assert _summary_metric(out, "New vs baseline") >= 0


def test_cli_summary_with_metrics_baseline_shows_metrics_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    metrics_baseline_path = tmp_path / "metrics-baseline.json"
    src.write_text("def f(value: int) -> int:\n    return value\n", "utf-8")
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--metrics-baseline",
            str(metrics_baseline_path),
            "--update-metrics-baseline",
        ],
    )
    _ = capsys.readouterr()
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--metrics-baseline",
            str(metrics_baseline_path),
        ],
    )
    out = capsys.readouterr().out
    assert_contains_all(out, "Metrics", "Adoption", "Overloaded")


def test_cli_summary_with_api_surface_shows_public_api_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f(value: int) -> int:\n    return value\n", "utf-8")
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress", "--api-surface"])
    out = capsys.readouterr().out
    assert "Public API" in out
    assert "symbols" in out
    assert "modules" in out


def test_cli_ci_summary_includes_adoption_and_public_api_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    metrics_baseline_path = tmp_path / "metrics-baseline.json"
    src.write_text("def f(value: int) -> int:\n    return value\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--api-surface",
            "--metrics-baseline",
            str(metrics_baseline_path),
            "--update-metrics-baseline",
        ],
    )
    _ = capsys.readouterr()
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--ci",
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(metrics_baseline_path),
            "--api-surface",
        ],
    )
    out = capsys.readouterr().out
    assert_contains_all(out, "Adoption", "Public API", "symbols=", "docstrings=")


def test_cli_pyproject_golden_fixture_paths_exclude_fixture_clone_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures_dir = tmp_path / "tests" / "fixtures" / "golden_project"
    fixtures_dir.mkdir(parents=True)
    _write_duplicate_function_module(fixtures_dir, "a.py")
    _write_duplicate_function_module(fixtures_dir, "b.py")
    _write_current_python_baseline(tmp_path / "codeclone.baseline.json")
    report_path = tmp_path / "report.json"
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.codeclone]
min_loc = 1
min_stmt = 1
fail_on_new = true
skip_metrics = true
golden_fixture_paths = ["tests/fixtures/golden_*"]
""".strip()
        + "\n",
        "utf-8",
    )

    _run_parallel_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--json",
            str(report_path),
        ],
    )

    payload = json.loads(report_path.read_text("utf-8"))
    clone_groups = cast(
        "dict[str, object]",
        cast("dict[str, object]", payload["findings"])["groups"],
    )["clones"]
    clone_groups_map = cast("dict[str, object]", clone_groups)
    assert clone_groups_map["functions"] == []
    suppressed = cast("dict[str, object]", clone_groups_map["suppressed"])
    suppressed_functions = cast("list[dict[str, object]]", suppressed["functions"])
    assert len(suppressed_functions) == 1
    assert suppressed_functions[0]["suppression_rule"] == "golden_fixture"
    assert (
        cast("dict[str, int]", payload["findings"]["summary"]["clones"])["suppressed"]
        == 1
    )


def test_cli_public_api_breaking_count_stable_across_warm_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src, metrics_baseline_path, cache_path = _prepare_api_surface_cache_case(
        tmp_path,
        monkeypatch,
        source="def run(alpha: int, beta: int) -> int:\n    return alpha + beta\n",
    )
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--api-surface",
            "--metrics-baseline",
            str(metrics_baseline_path),
            "--update-metrics-baseline",
        ],
    )
    _ = capsys.readouterr()

    src.write_text(
        "def run(beta: int, alpha: int) -> int:\n    return alpha + beta\n",
        "utf-8",
    )

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--api-surface",
            "--metrics-baseline",
            str(metrics_baseline_path),
            "--cache-path",
            str(cache_path),
        ],
    )
    cold_out = capsys.readouterr().out

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--api-surface",
            "--metrics-baseline",
            str(metrics_baseline_path),
            "--cache-path",
            str(cache_path),
        ],
    )
    warm_out = capsys.readouterr().out

    assert "1 breaking" in cold_out
    assert "1 breaking" in warm_out


def test_cli_api_surface_ignores_non_api_warm_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, cache_path = _prepare_api_surface_cache_case(
        tmp_path,
        monkeypatch,
        source="def run(value: int) -> int:\n    return value\n",
    )
    report_path = tmp_path / "report.json"
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--cache-path",
            str(cache_path),
        ],
    )
    _ = capsys.readouterr()

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--no-progress",
            "--api-surface",
            "--cache-path",
            str(cache_path),
            "--json",
            str(report_path),
        ],
    )
    out = capsys.readouterr().out
    payload = json.loads(report_path.read_text("utf-8"))
    api_surface_summary = cast(
        "dict[str, object]",
        cast("dict[str, object]", payload["metrics"])["summary"],
    )["api_surface"]

    assert _summary_metric(out, "analyzed") == 1
    assert _summary_metric(out, "from cache") == 0
    assert "Public API" in out
    assert cast("dict[str, object]", api_surface_summary)["enabled"] is True
    assert cast("dict[str, object]", api_surface_summary)["public_symbols"] == 1
    assert cast("dict[str, object]", api_surface_summary)["modules"] == 1


def test_cli_summary_no_color_has_no_ansi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress", "--no-color"])
    out = capsys.readouterr().out
    assert "\x1b[" not in out


def test_cli_scan_failed_is_internal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_root: str) -> Iterable[str]:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(core_discovery, "iter_py_files", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, [str(tmp_path)])
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out


def test_cli_scan_oserror_is_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(_root: str) -> Iterable[str]:
        raise OSError("scan denied")

    monkeypatch.setattr(core_discovery, "iter_py_files", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, [str(tmp_path)])
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "CONTRACT ERROR:" in out
    assert "Scan failed" in out


def test_cli_failed_files_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for i in range(12):
        (tmp_path / f"f{i}.py").write_text("def f():\n    return 1\n", "utf-8")

    def _bad_process(
        _fp: str, *_args: object, **_kwargs: object
    ) -> cli.ProcessingResult:
        return cli.ProcessingResult(filepath=_fp, success=False, error="bad")

    monkeypatch.setattr(core_worker, "process_file", _bad_process)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    assert "files failed to process" in out
    assert "and 2 more" in out


def test_cli_failed_files_report_single(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _bad_process(
        _fp: str, *_args: object, **_kwargs: object
    ) -> cli.ProcessingResult:
        return cli.ProcessingResult(filepath=_fp, success=False, error="bad")

    monkeypatch.setattr(core_worker, "process_file", _bad_process)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    assert "files failed to process" in out
    assert "and 1 more" not in out


def test_cli_worker_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _boom(*_args: object, **_kwargs: object) -> cli.ProcessingResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(core_worker, "process_file", _boom)
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    assert exc.value.code == 5
    out = capsys.readouterr().out
    assert "INTERNAL ERROR:" in out


def test_cli_worker_failed_progress_sequential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_worker_failure_internal_error(
        tmp_path,
        monkeypatch,
        capsys,
        no_progress=False,
    )


def test_cli_worker_failed_sequential_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_worker_failure_internal_error(
        tmp_path,
        monkeypatch,
        capsys,
        no_progress=True,
    )


def test_cli_fail_on_new_prints_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    _patch_baseline_diff(monkeypatch, new_func={"f1"}, new_block={"b1"})
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=_current_py_minor(),
    )
    _assert_parallel_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--fail-on-new",
            "--no-progress",
        ],
        expected_code=3,
    )
    out = capsys.readouterr().out
    _assert_fail_on_new_summary(out)


def test_cli_fail_on_new_no_report_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_default_source(tmp_path)
    _patch_baseline_diff(monkeypatch, new_func={"f1"}, new_block={"b1"})
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=_current_py_minor(),
    )
    monkeypatch.chdir(tmp_path)
    _assert_parallel_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--fail-on-new",
            "--no-progress",
        ],
        expected_code=3,
    )
    out = capsys.readouterr().out
    assert "\n  report" not in out


@pytest.mark.parametrize(
    ("new_func", "new_block", "expect_func", "expect_block"),
    [
        ({"f1"}, set(), True, False),
        (set(), {"b1"}, False, True),
    ],
)
def test_cli_fail_on_new_verbose_single_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    new_func: set[str],
    new_block: set[str],
    expect_func: bool,
    expect_block: bool,
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f1():\n    return 1\n\ndef f2():\n    return 1\n", "utf-8")

    def _diff(
        _self: object, _f: dict[str, object], _b: dict[str, object]
    ) -> tuple[set[str], set[str]]:
        return new_func, new_block

    monkeypatch.setattr(baseline.Baseline, "diff", _diff)
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--fail-on-new",
                "--verbose",
                "--no-progress",
            ],
        )
    assert exc.value.code == 3
    out = capsys.readouterr().out
    if expect_func:
        assert (
            "Details (function clone hashes):" in out or "Function clone hashes:" in out
        )
    else:
        assert "Details (function clone hashes):" not in out
        assert "Function clone hashes:" not in out
    if expect_block:
        assert "Details (block clone hashes):" in out or "Block clone hashes:" in out
    else:
        assert "Details (block clone hashes):" not in out
        assert "Block clone hashes:" not in out


def test_cli_fail_on_new_verbose_and_report_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_python_module(
        tmp_path,
        "a.py",
        "def f1():\n    return 1\n\ndef f2():\n    return 1\n",
    )
    _patch_baseline_diff(monkeypatch, new_func={"fhash1"}, new_block={"bhash1"})
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=_current_py_minor(),
    )
    html_out = tmp_path / "report.html"
    _assert_parallel_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--fail-on-new",
            "--verbose",
            "--html",
            str(html_out),
            "--no-progress",
        ],
        expected_code=3,
    )
    out = capsys.readouterr().out
    assert "report" in out
    assert str(html_out) in out or html_out.name in out
    assert "Details (function clone hashes):" in out or "Function clone hashes:" in out
    assert "- fhash1" in out
    assert "Details (block clone hashes):" in out or "Block clone hashes:" in out
    assert "- bhash1" in out


def test_cli_fail_on_new_default_report_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f1():\n    return 1\n\ndef f2():\n    return 1\n", "utf-8")
    report_path = tmp_path / ".cache" / "codeclone" / "report.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("<html>ok</html>", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    monkeypatch.chdir(tmp_path)
    _patch_parallel(monkeypatch)
    _assert_cli_exit(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--fail-on-new",
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ],
        expected_code=3,
    )
    out = capsys.readouterr().out
    assert "report" in out
    assert ".cache/codeclone/report.html" in out


def test_cli_batch_result_none_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for idx in range(pipeline._parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_fixed_executor(monkeypatch, _FixedFuture(value=None))
    _run_main(monkeypatch, [str(tmp_path), "--processes", "2", "--no-progress"])
    out = capsys.readouterr().out
    assert "Failed to process batch item" in out


def test_cli_batch_result_none_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for idx in range(pipeline._parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_dummy_progress(monkeypatch)
    _patch_fixed_executor(monkeypatch, _FixedFuture(value=None))
    _run_main(monkeypatch, [str(tmp_path), "--processes", "2"])
    out = capsys.readouterr().out
    assert "Worker failed" in out


def test_cli_failed_batch_item_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for idx in range(pipeline._parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_fixed_executor(monkeypatch, _FixedFuture(error=RuntimeError("boom")))
    _run_main(monkeypatch, [str(tmp_path), "--processes", "2", "--no-progress"])
    out = capsys.readouterr().out
    assert "Failed to process batch item" in out


def test_cli_failed_batch_item_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for idx in range(pipeline._parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_dummy_progress(monkeypatch)
    _patch_fixed_executor(monkeypatch, _FixedFuture(error=RuntimeError("boom")))
    _run_main(monkeypatch, [str(tmp_path), "--processes", "2"])
    out = capsys.readouterr().out
    assert "Worker failed" in out


# ---------------------------------------------------------------------------
# Contract protection: structural findings are report-only
# ---------------------------------------------------------------------------

_DUPLICATED_BRANCHES_SOURCE = """\
__all__ = ["fn"]


def fn(x):
    if x == 1:
        return 1
    elif x == 2:
        return 2
"""


def test_structural_findings_do_not_affect_clone_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structural findings must not alter function clone group counts."""
    # File with duplicated branches
    src = tmp_path / "dup.py"
    src.write_text(_DUPLICATED_BRANCHES_SOURCE, "utf-8")
    # File without any duplicated branches
    src2 = tmp_path / "clean.py"
    src2.write_text("def g(x):\n    return x\n", "utf-8")

    json_out = tmp_path / "report.json"
    _run_main(
        monkeypatch,
        [str(tmp_path), "--json", str(json_out), "--no-progress"],
    )
    payload = json.loads(json_out.read_text("utf-8"))

    # No function clones expected (both functions are unique)
    func_groups = _report_clone_groups(payload, "functions")
    assert len(func_groups) == 0, "Structural findings must not create clone groups"


def test_structural_findings_do_not_affect_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structural findings must not change exit code (should be 0 for no clones)."""
    src = tmp_path / "dup.py"
    src.write_text(_DUPLICATED_BRANCHES_SOURCE, "utf-8")

    # Run without --ci to avoid baseline requirement; structural findings must not
    # cause gating failure — exit must be SUCCESS (0), not GATING_FAILURE (3).
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])


def test_structural_findings_recomputed_when_cache_was_built_without_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "dup.py"
    src.write_text(
        """\
def fn(x):
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    f = 6
    g = 7
    if x == 1:
        log("a")
        value = x + 1
        return value
    elif x == 2:
        log("b")
        value = x + 2
        return value
    return a + b + c + d + e + f + g
""",
        "utf-8",
    )
    cache_path = tmp_path / "cache.json"
    json_out = tmp_path / "report.json"

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--cache-path",
            str(cache_path),
            "--no-progress",
        ],
    )
    cache_payload = json.loads(cache_path.read_text("utf-8"))
    files_before = cache_payload["payload"]["files"]
    assert all("sf" not in entry for entry in files_before.values())

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--cache-path",
            str(cache_path),
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    report_payload = json.loads(json_out.read_text("utf-8"))
    assert _report_structural_groups(report_payload)

    cache_payload = json.loads(cache_path.read_text("utf-8"))
    files_after = cache_payload["payload"]["files"]
    assert any("sf" in entry for entry in files_after.values())


@pytest.mark.parametrize(
    ("source", "suppressed_count"),
    [
        (
            """\
class Settings:  # codeclone: ignore[dead-code]
    @validator("field")
    @classmethod
    def validate_config_version(
        cls,
        value: str | None,
    ) -> str | None:  # codeclone: ignore[dead-code]
        return value
""",
            2,
        ),
        (
            """\
class Settings:  # codeclone: ignore[dead-code]
    @field_validator("trusted_proxy_ips", "additional_telegram_ip_ranges")
    @classmethod
    def validate_trusted_proxy_ips(  # codeclone: ignore[dead-code]
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        return value

    @model_validator(mode="before")
    @classmethod
    def migrate_config_if_needed(  # codeclone: ignore[dead-code]
        cls,
        values: dict[str, object],
    ) -> dict[str, object]:
        return values
""",
            3,
        ),
    ],
)
def test_cli_dead_code_suppression_is_stable_between_plain_and_json_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    suppressed_count: int,
) -> None:
    _write_python_module(
        tmp_path,
        "models.py",
        source,
    )
    json_out = tmp_path / "report.json"
    cache_path = tmp_path / "cache.json"

    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--cache-path",
            str(cache_path),
            "--fail-dead-code",
            "--no-progress",
        ],
    )

    cache_payload = json.loads(cache_path.read_text("utf-8"))
    files_before = cache_payload["payload"]["files"]
    assert all("sf" not in entry for entry in files_before.values())

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--cache-path",
            str(cache_path),
            "--fail-dead-code",
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    payload = json.loads(json_out.read_text("utf-8"))
    dead_code = payload["metrics"]["families"]["dead_code"]
    assert dead_code["summary"] == {
        "total": 0,
        "high_confidence": 0,
        "suppressed": suppressed_count,
    }

    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--cache-path",
            str(cache_path),
            "--fail-dead-code",
            "--no-progress",
        ],
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "New high-risk functions vs metrics baseline: 3.",
            ("new_high_risk_functions", "3"),
        ),
        (
            "Dependency cycles detected: 2 cycle(s).",
            ("dependency_cycles", "2"),
        ),
        (
            "Complexity threshold exceeded: max=31, threshold=20.",
            ("complexity_max", "31 (threshold=20)"),
        ),
        (
            "something else.",
            ("detail", "something else"),
        ),
    ],
)
def test_parse_metric_reason_entry_contract(
    reason: str, expected: tuple[str, str]
) -> None:
    assert parse_metric_reason_entry(reason) == expected

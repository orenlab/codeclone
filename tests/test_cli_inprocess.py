from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

import codeclone.baseline as baseline
from codeclone import __version__, cli
from codeclone.baseline import BASELINE_SCHEMA_VERSION
from codeclone.cache import Cache, file_stat_signature
from codeclone.errors import CacheError


@dataclass(slots=True)
class _DummyFuture:
    _result: object

    def result(self) -> object:
        return self._result


class _DummyExecutor:
    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers

    def __enter__(self) -> _DummyExecutor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> Literal[False]:
        return False

    def submit(
        self, fn: Callable[..., object], *args: object, **kwargs: object
    ) -> _DummyFuture:
        return _DummyFuture(fn(*args, **kwargs))


class _FailingExecutor:
    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers

    def __enter__(self) -> _FailingExecutor:
        raise PermissionError("nope")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> Literal[False]:
        return False


@dataclass(slots=True)
class _FixedFuture:
    value: object | None = None
    error: Exception | None = None

    def result(self) -> object | None:
        if self.error:
            raise self.error
        return self.value


class _FixedExecutor:
    def __init__(self, future: _FixedFuture, *args: object, **kwargs: object) -> None:
        self._future = future

    def __enter__(self) -> _FixedExecutor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> Literal[False]:
        return False

    def submit(
        self, fn: Callable[..., object], *args: object, **kwargs: object
    ) -> _FixedFuture:
        return self._future


class _DummyProgress:
    def __init__(self, *args: object, **kwargs: object) -> None:
        return None

    def __enter__(self) -> _DummyProgress:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> Literal[False]:
        return False

    def add_task(self, _desc: str, total: int) -> int:
        return total

    def advance(self, _task: int) -> None:
        return None


def _patch_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "ProcessPoolExecutor", _DummyExecutor)
    monkeypatch.setattr(cli, "as_completed", lambda futures: futures)


def _run_main(monkeypatch: pytest.MonkeyPatch, args: Iterable[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["codeclone", *args])
    cli.main()


def _patch_fixed_executor(
    monkeypatch: pytest.MonkeyPatch, future: _FixedFuture
) -> None:
    monkeypatch.setattr(
        cli, "ProcessPoolExecutor", lambda *args, **kwargs: _FixedExecutor(future)
    )
    monkeypatch.setattr(cli, "as_completed", lambda futures: futures)


def _baseline_payload(
    *,
    functions: list[str] | None = None,
    blocks: list[str] | None = None,
    python_version: str | None = None,
    baseline_version: str | None = None,
    schema_version: int | None = None,
    include_version_schema: bool = True,
    generator: str | None = "codeclone",
    payload_sha256: str | None = None,
) -> dict[str, object]:
    function_list = [] if functions is None else functions
    block_list = [] if blocks is None else blocks
    payload: dict[str, object] = {"functions": function_list, "blocks": block_list}
    if python_version is not None:
        payload["python_version"] = python_version
    if include_version_schema:
        payload["baseline_version"] = baseline_version or __version__
        payload["schema_version"] = (
            BASELINE_SCHEMA_VERSION if schema_version is None else schema_version
        )
    if generator is not None:
        payload["generator"] = generator
    canonical = json.dumps(
        {"functions": function_list, "blocks": block_list},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    payload["payload_sha256"] = (
        payload_sha256
        if payload_sha256 is not None
        else hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )
    return payload


def _write_baseline(
    path: Path,
    *,
    functions: list[str] | None = None,
    blocks: list[str] | None = None,
    python_version: str | None = None,
    baseline_version: str | None = None,
    schema_version: int | None = None,
    include_version_schema: bool = True,
    generator: str | None = "codeclone",
    payload_sha256: str | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            _baseline_payload(
                functions=functions,
                blocks=blocks,
                python_version=python_version,
                baseline_version=baseline_version,
                schema_version=schema_version,
                include_version_schema=include_version_schema,
                generator=generator,
                payload_sha256=payload_sha256,
            )
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
    out = capsys.readouterr().out
    assert expected_message in out
    if not strict_fail:
        assert "Baseline is not trusted for this run and will be ignored" in out
    payload_out = json.loads(json_out.read_text("utf-8"))
    meta = payload_out["meta"]
    assert meta["baseline_status"] == expected_status
    assert meta["baseline_loaded"] is False


def _assert_fail_on_new_summary(out: str, *, include_blocks: bool = True) -> None:
    assert "FAILED: New code clones detected." in out
    assert "New function clone groups" in out
    if include_blocks:
        assert "New block clone groups" in out
    assert "codeclone . --update-baseline" in out


def _summary_metric(out: str, label: str) -> int:
    match = re.search(rf"{re.escape(label)}:\s+(\d+)", out)
    if match:
        return int(match.group(1))
    match = re.search(rf"{re.escape(label)}\s+[│|]\s+(\d+)", out)
    assert match, f"summary label not found: {label}\n{out}"
    return int(match.group(1))


def _compact_summary_metric(out: str, key: str) -> int:
    match = re.search(rf"{re.escape(key)}=(\d+)", out)
    assert match, f"compact summary key not found: {key}\n{out}"
    return int(match.group(1))


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
    assert "Analysis Summary" in out
    assert "Function clone groups" in out


def test_cli_default_cache_dir_uses_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
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
        ) -> None:
            return None

        def save(self) -> None:
            return None

    monkeypatch.setattr(cli, "Cache", _CacheStub)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    assert captured["path"] == tmp_path / ".cache" / "codeclone" / "cache.json"


@pytest.mark.parametrize("flag", ["--cache-dir", "--cache-path"])
def test_cli_cache_dir_override_respected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
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
        ) -> None:
            return None

        def save(self) -> None:
            return None

    cache_path = tmp_path / "custom-cache.json"
    monkeypatch.setattr(cli, "Cache", _CacheStub)
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            flag,
            str(cache_path),
            "--no-progress",
        ],
    )
    assert captured["path"] == cache_path


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

    monkeypatch.setattr(cli, "iter_py_files", lambda _root: [])
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(root2), "--no-progress"])
    out = capsys.readouterr().out
    assert "Cache signature mismatch" not in out


def test_cli_warns_on_legacy_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def f():\n    return 1\n", "utf-8")
    legacy_path = tmp_path / "legacy" / "cache.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("{}", "utf-8")
    monkeypatch.setattr(cli, "LEGACY_CACHE_PATH", legacy_path)
    baseline = _write_baseline(
        root / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    _run_main(
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
    (root / "a.py").write_text("def f():\n    return 1\n", "utf-8")

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
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [str(root), "--baseline", str(baseline), "--no-progress"],
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" in out


def test_cli_no_legacy_warning_with_cache_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def f():\n    return 1\n", "utf-8")
    legacy_path = tmp_path / "legacy" / "cache.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("{}", "utf-8")
    monkeypatch.setattr(cli, "LEGACY_CACHE_PATH", legacy_path)
    cache_path = tmp_path / "custom-cache.json"
    _patch_parallel(monkeypatch)
    _run_main(
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


def test_cli_main_progress_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    monkeypatch.setattr(cli, "ProcessPoolExecutor", _FailingExecutor)
    _run_main(monkeypatch, [str(tmp_path)])
    out = capsys.readouterr().out
    assert "falling back to sequential" in out


def test_cli_main_no_progress_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    monkeypatch.setattr(cli, "ProcessPoolExecutor", _FailingExecutor)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
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
    monkeypatch.setattr(cli, "ProcessPoolExecutor", _FailingExecutor)
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
    monkeypatch.setattr(cli, "Progress", _DummyProgress)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path)])


def test_cli_invalid_root_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: Path) -> Path:
        raise OSError("bad")

    monkeypatch.setattr(Path, "resolve", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["bad"])
    assert exc.value.code == 1


def test_cli_main_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "out.json"
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
            "--text",
            str(text_out),
            "--no-progress",
        ],
    )
    assert html_out.exists()
    assert json_out.exists()
    assert text_out.exists()
    out = capsys.readouterr().out
    assert "HTML report saved:" in out
    assert "JSON report saved:" in out
    assert "Text report saved:" in out
    assert out.index("Analysis Summary") < out.index("HTML report saved:")


def test_cli_reports_include_audit_metadata_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
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
    meta = payload["meta"]
    assert meta["baseline_status"] == "ok"
    assert meta["baseline_loaded"] is True
    assert meta["baseline_version"] == __version__
    assert meta["baseline_schema_version"] == BASELINE_SCHEMA_VERSION
    assert meta["baseline_path"] == str(baseline_path.resolve())
    assert "function_clones" in payload
    assert "block_clones" in payload
    assert "segment_clones" in payload

    text = text_out.read_text("utf-8")
    assert "REPORT METADATA" in text
    assert "Baseline status: ok" in text
    assert f"Baseline schema version: {BASELINE_SCHEMA_VERSION}" in text

    html = html_out.read_text("utf-8")
    assert "Report Provenance" in html
    assert 'data-baseline-status="ok"' in html
    assert "Baseline schema" in html


def test_cli_reports_include_audit_metadata_missing_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(tmp_path / "missing-baseline.json"),
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "missing"
    assert meta["baseline_loaded"] is False
    assert meta["baseline_version"] is None
    assert meta["baseline_schema_version"] is None


def test_cli_reports_include_audit_metadata_version_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        baseline_version="0.0.0",
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
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
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline version mismatch" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "mismatch_version"
    assert meta["baseline_loaded"] is True
    assert meta["baseline_version"] == "0.0.0"


def test_cli_reports_include_audit_metadata_schema_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        schema_version=999,
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
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
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline schema version mismatch" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "mismatch_schema"
    assert meta["baseline_loaded"] is True
    assert meta["baseline_schema_version"] == 999


def test_cli_reports_include_audit_metadata_python_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version="0.0",
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--fail-on-new",
                "--json",
                str(json_out),
                "--no-progress",
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline Python version mismatch" in out
    assert "Baseline checks require the same Python version" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "mismatch_python"
    assert meta["baseline_loaded"] is True
    assert meta["baseline_python_version"] == "0.0"


def test_cli_reports_include_audit_metadata_invalid_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{broken json", "utf-8")
    json_out = tmp_path / "report.json"
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
    out = capsys.readouterr().out
    assert "Invalid baseline file" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "invalid"
    assert meta["baseline_loaded"] is False


def test_cli_reports_include_audit_metadata_legacy_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"functions": [], "blocks": [], "python_version": "3.13"}),
        "utf-8",
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
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
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "legacy baseline format" in out
    assert "payload_sha256" not in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "legacy"
    assert meta["baseline_loaded"] is True


def test_cli_reports_include_audit_metadata_integrity_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        functions=["f1"],
    )
    tampered = json.loads(baseline_path.read_text("utf-8"))
    tampered["functions"] = ["tampered"]
    baseline_path.write_text(json.dumps(tampered), "utf-8")

    json_out = tmp_path / "report.json"
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
    out = capsys.readouterr().out
    assert "integrity check failed" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "integrity_failed"
    assert meta["baseline_loaded"] is False


def test_cli_reports_include_audit_metadata_generator_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        generator="not-codeclone",
    )
    json_out = tmp_path / "report.json"
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
    out = capsys.readouterr().out
    assert "generator mismatch" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "generator_mismatch"
    assert meta["baseline_loaded"] is False


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_message", "expected_status"),
    [
        ("generator", 123, "generator mismatch", "generator_mismatch"),
        (
            "payload_sha256",
            1,
            "integrity payload hash is missing",
            "integrity_missing",
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
    _assert_baseline_failure_meta(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
        mutate_payload=lambda payload: payload.__setitem__(field, bad_value),
        expected_message=expected_message,
        expected_status=expected_status,
    )


def test_cli_reports_include_audit_metadata_integrity_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    payload = _baseline_payload(
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    del payload["payload_sha256"]
    baseline_path.write_text(json.dumps(payload), "utf-8")
    json_out = tmp_path / "report.json"
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
    out = capsys.readouterr().out
    assert "integrity payload hash is missing" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    payload_out = json.loads(json_out.read_text("utf-8"))
    meta = payload_out["meta"]
    assert meta["baseline_status"] == "integrity_missing"
    assert meta["baseline_loaded"] is False


def test_cli_reports_include_audit_metadata_baseline_too_large(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(tmp_path / "baseline.json")
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--max-baseline-size-mb",
            "0",
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "too large" in out
    assert "Baseline is not trusted for this run and will be ignored" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["baseline_status"] == "too_large"
    assert meta["baseline_loaded"] is False


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
    payload["generator"] = "not-codeclone"
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
    assert report["meta"]["baseline_status"] == "generator_mismatch"
    assert report["meta"]["baseline_loaded"] is False


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_message", "expected_status"),
    [
        ("generator", "not-codeclone", "generator mismatch", "generator_mismatch"),
        (
            "payload_sha256",
            "00",
            "integrity check failed",
            "integrity_failed",
        ),
        (
            "payload_sha256",
            None,
            "integrity payload hash is missing",
            "integrity_missing",
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
        if bad_value is None:
            payload.pop(field, None)
        else:
            payload[field] = bad_value

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
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{broken json", "utf-8")
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--json",
                str(json_out),
                "--ci",
                "--no-progress",
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Invalid baseline file" in out
    payload = json.loads(json_out.read_text("utf-8"))
    assert payload["meta"]["baseline_status"] == "invalid"
    assert payload["meta"]["baseline_loaded"] is False


def test_cli_too_large_baseline_fails_in_ci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(tmp_path / "baseline.json")
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--max-baseline-size-mb",
                "0",
                "--json",
                str(json_out),
                "--ci",
                "--no-progress",
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "too large" in out
    payload = json.loads(json_out.read_text("utf-8"))
    assert payload["meta"]["baseline_status"] == "too_large"
    assert payload["meta"]["baseline_loaded"] is False


def test_cli_reports_cache_used_false_on_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry(str(src), {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()
    data = json.loads(cache_path.read_text("utf-8"))
    data["_signature"] = "bad"
    cache_path.write_text(json.dumps(data), "utf-8")

    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--cache-dir",
            str(cache_path),
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "signature" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["cache_used"] is False


def test_cli_reports_cache_too_large_respects_max_size_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{}", "utf-8")

    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline_path),
            "--cache-path",
            str(cache_path),
            "--max-cache-size-mb",
            "0",
            "--json",
            str(json_out),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Cache file too large" in out
    payload = json.loads(json_out.read_text("utf-8"))
    meta = payload["meta"]
    assert meta["cache_used"] is False


@pytest.mark.parametrize(
    ("flag", "bad_name", "label", "expected"),
    [
        ("--html", "report.exe", "HTML", ".html"),
        ("--json", "report.txt", "JSON", ".json"),
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


def test_cli_outputs_quiet_no_print(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    html_out = tmp_path / "out.html"
    json_out = tmp_path / "out.json"
    text_out = tmp_path / "out.txt"
    baseline = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    _patch_parallel(monkeypatch)
    _run_main(
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
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        baseline_version="0.0.0",
    )
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


def test_cli_update_baseline(
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
    baseline = tmp_path / "codeclone.baseline.json"
    _patch_parallel(monkeypatch)
    _run_main(
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
    assert payload.get("baseline_version") == __version__
    assert payload.get("schema_version") == BASELINE_SCHEMA_VERSION


def test_cli_baseline_missing_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline = tmp_path / "missing.json"
    _patch_parallel(monkeypatch)
    _run_main(
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
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, python_version="0.0")
    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    assert "Baseline was generated with Python 0.0." in out
    assert "Current interpreter: Python" in out


def test_cli_baseline_version_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        baseline_version="0.0.0",
    )
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--no-progress",
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline version mismatch" in out


def test_cli_baseline_version_missing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
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
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--no-progress",
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline version missing" in out


def test_cli_baseline_schema_version_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        schema_version=999,
    )
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--no-progress",
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline schema version mismatch" in out


def test_cli_baseline_version_and_schema_mismatch_status_prefers_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
        baseline_version="0.0.0",
        schema_version=999,
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
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
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline version mismatch" in out
    assert "Baseline schema version mismatch" in out
    payload = json.loads(json_out.read_text("utf-8"))
    assert payload["meta"]["baseline_status"] == "mismatch_version"


def test_cli_baseline_version_and_python_mismatch_status_prefers_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version="0.0",
        baseline_version="0.0.0",
    )
    json_out = tmp_path / "report.json"
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
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
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline version mismatch" in out
    assert "Baseline Python version mismatch" in out
    payload = json.loads(json_out.read_text("utf-8"))
    assert payload["meta"]["baseline_status"] == "mismatch_version"


def test_cli_baseline_python_version_mismatch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, python_version="0.0")
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline),
                "--fail-on-new",
                "--no-progress",
            ],
        )
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Baseline checks require the same Python version" in out


def test_cli_negative_size_limits_fail_fast(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["--max-baseline-size-mb", "-1"])
    assert exc.value.code == 1
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
    assert exc.value.code == 2


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
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 1}, [], [], [])
    cache.save()
    data = json.loads(cache_path.read_text("utf-8"))
    data["_signature"] = "bad"
    cache_path.write_text(json.dumps(data), "utf-8")

    _patch_parallel(monkeypatch)
    _run_main(
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
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
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
    assert exc.value.code == 1


def test_cli_discovery_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    cache = Cache(tmp_path / "cache.json")
    cache.data["files"][str(src)] = {
        "stat": {"mtime_ns": src.stat().st_mtime_ns, "size": src.stat().st_size},
        "units": [
            {
                "qualname": "mod:f",
                "filepath": str(src),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "abc",
                "loc_bucket": "0-19",
            }
        ],
        "blocks": [],
        "segments": [],
    }
    cache.save()

    _patch_parallel(monkeypatch)
    _run_main(
        monkeypatch,
        [
            str(tmp_path),
            "--cache-dir",
            str(cache.path),
            "--no-progress",
        ],
    )
    out = capsys.readouterr().out
    files_found = _summary_metric(out, "Files found")
    files_analyzed = _summary_metric(out, "Files analyzed")
    cache_hits = _summary_metric(out, "Cache hits")
    files_skipped = _summary_metric(out, "Files skipped")
    assert files_found > 0
    assert cache_hits == files_found
    assert files_analyzed == 0
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

    monkeypatch.setattr(cli, "file_stat_signature", _bad_stat)
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
    assert "Skipping file" in out
    if "--ci" in extra_args:
        files_found = _compact_summary_metric(out, "found")
        files_analyzed = _compact_summary_metric(out, "analyzed")
        cache_hits = _compact_summary_metric(out, "cache_hits")
        files_skipped = _compact_summary_metric(out, "skipped")
    else:
        files_found = _summary_metric(out, "Files found")
        files_analyzed = _summary_metric(out, "Files analyzed")
        cache_hits = _summary_metric(out, "Cache hits")
        files_skipped = _summary_metric(out, "Files skipped")
    assert files_found == files_analyzed + cache_hits + files_skipped


def test_cli_ci_discovery_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
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
    assert "Analysis Summary" in out
    assert "Analyzing" not in out
    assert "\x1b[" not in out
    assert "new_vs_baseline=" in out
    assert _compact_summary_metric(out, "found") == 1
    assert _compact_summary_metric(out, "analyzed") == 0
    assert _compact_summary_metric(out, "cache_hits") == 1
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
    files_analyzed = _summary_metric(out, "Files analyzed")
    cache_hits = _summary_metric(out, "Cache hits")
    files_skipped = _summary_metric(out, "Files skipped")
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
    assert "Analysis Summary" in out
    assert out.count("Analysis Summary") == 1
    assert out.count("Metric") == 1
    assert out.count("Value") == 1
    assert "Files parsed" not in out
    assert "Input" not in out
    assert _summary_metric(out, "Files found") >= 0
    assert _summary_metric(out, "Files analyzed") >= 0
    assert _summary_metric(out, "Cache hits") >= 0
    assert _summary_metric(out, "Files skipped") >= 0
    assert _summary_metric(out, "Function clone groups") >= 0
    assert _summary_metric(out, "Block clone groups") >= 0
    assert _summary_metric(out, "Segment clone groups") >= 0
    assert _summary_metric(out, "Suppressed segment groups") >= 0
    assert _summary_metric(out, "New vs baseline") >= 0


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


def test_cli_scan_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_root: str) -> Iterable[str]:
        raise RuntimeError("scan failed")

    monkeypatch.setattr(cli, "iter_py_files", _boom)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, [str(tmp_path)])
    assert exc.value.code == 1


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

    monkeypatch.setattr(cli, "process_file", _bad_process)
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

    monkeypatch.setattr(cli, "process_file", _bad_process)
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

    monkeypatch.setattr(cli, "process_file", _boom)
    _patch_parallel(monkeypatch)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    assert "Worker failed" in out


def test_cli_worker_failed_progress_sequential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

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

    monkeypatch.setattr(cli, "Progress", _DummyProgress)
    monkeypatch.setattr(cli, "ProcessPoolExecutor", _FailExec)
    monkeypatch.setattr(cli, "process_file", _boom)
    _run_main(monkeypatch, [str(tmp_path)])
    out = capsys.readouterr().out
    assert "Worker failed" in out


def test_cli_worker_failed_sequential_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

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

    monkeypatch.setattr(cli, "ProcessPoolExecutor", _FailExec)
    monkeypatch.setattr(cli, "process_file", _boom)
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    assert "Worker failed" in out


def test_cli_fail_on_new_prints_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _diff(
        _self: object, _f: dict[str, object], _b: dict[str, object]
    ) -> tuple[set[str], set[str]]:
        return {"f1"}, {"b1"}

    monkeypatch.setattr(baseline.Baseline, "diff", _diff)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
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
                "--no-progress",
            ],
        )
    assert exc.value.code == 3
    out = capsys.readouterr().out
    _assert_fail_on_new_summary(out)


def test_cli_fail_on_new_no_report_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    def _diff(
        _self: object, _f: dict[str, object], _b: dict[str, object]
    ) -> tuple[set[str], set[str]]:
        return {"f1"}, {"b1"}

    monkeypatch.setattr(baseline.Baseline, "diff", _diff)
    baseline_path = _write_baseline(
        tmp_path / "baseline.json",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    monkeypatch.chdir(tmp_path)
    _patch_parallel(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        _run_main(
            monkeypatch,
            [
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--fail-on-new",
                "--no-progress",
            ],
        )
    assert exc.value.code == 3
    out = capsys.readouterr().out
    assert "See detailed report:" not in out


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
        assert "Details (function clone hashes):" in out
    else:
        assert "Details (function clone hashes):" not in out
    if expect_block:
        assert "Details (block clone hashes):" in out
    else:
        assert "Details (block clone hashes):" not in out


def test_cli_fail_on_new_verbose_and_report_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f1():\n    return 1\n\ndef f2():\n    return 1\n", "utf-8")

    def _diff(
        _self: object, _f: dict[str, object], _b: dict[str, object]
    ) -> tuple[set[str], set[str]]:
        return {"fhash1"}, {"bhash1"}

    monkeypatch.setattr(baseline.Baseline, "diff", _diff)
    baseline_path = tmp_path / "baseline.json"
    _write_baseline(
        baseline_path,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    html_out = tmp_path / "report.html"
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
                "--html",
                str(html_out),
                "--no-progress",
            ],
        )
    assert exc.value.code == 3
    out = capsys.readouterr().out
    assert "See detailed report:" in out
    assert str(html_out) in out
    assert "Details (function clone hashes):" in out
    assert "- fhash1" in out
    assert "Details (block clone hashes):" in out
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
    with pytest.raises(SystemExit) as exc:
        _run_main(
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
        )
    assert exc.value.code == 3
    out = capsys.readouterr().out
    assert "See detailed report:" in out
    assert ".cache/codeclone/report.html" in out


def test_cli_batch_result_none_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_fixed_executor(monkeypatch, _FixedFuture(value=None))
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    assert "Failed to process batch item" not in out


def test_cli_batch_result_none_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    monkeypatch.setattr(cli, "Progress", _DummyProgress)
    _patch_fixed_executor(monkeypatch, _FixedFuture(value=None))
    _run_main(monkeypatch, [str(tmp_path)])
    out = capsys.readouterr().out
    assert "Worker failed" not in out


def test_cli_failed_batch_item_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    _patch_fixed_executor(monkeypatch, _FixedFuture(error=RuntimeError("boom")))
    _run_main(monkeypatch, [str(tmp_path), "--no-progress"])
    out = capsys.readouterr().out
    assert "Failed to process batch item" in out


def test_cli_failed_batch_item_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    monkeypatch.setattr(cli, "Progress", _DummyProgress)
    _patch_fixed_executor(monkeypatch, _FixedFuture(error=RuntimeError("boom")))
    _run_main(monkeypatch, [str(tmp_path)])
    out = capsys.readouterr().out
    assert "Worker failed" in out

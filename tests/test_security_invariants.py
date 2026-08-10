# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Security invariant sentinels for CodeClone trust boundaries.

These tests lock documented security behavior without changing production
contracts. They complement integration tests in ``test_security.py`` and
surface-specific suites (MCP, scanner, baseline, cache).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codeclone.analysis.suppressions import (
    SUPPORTED_RULE_IDS,
    extract_suppression_directives,
)
from codeclone.audit.validation import AuditConfigError, resolve_audit_path
from codeclone.cache.integrity import (
    cache_payload_checksum,
    verify_cache_payload_checksum,
)
from codeclone.contracts.errors import ValidationError
from codeclone.report.html.primitives.escape import _escape_html
from codeclone.scanner import iter_py_files, resolved_path_under_root
from codeclone.surfaces.mcp._session_helpers import (
    _normalize_relative_path,
    _resolve_optional_path,
    _resolve_root,
)
from codeclone.surfaces.mcp.session import MCPServiceContractError
from codeclone.utils.git_diff import validate_git_diff_ref
from tests._tmp_tree import make_dir, write_file

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HTML_JS_PATH = _REPO_ROOT / "codeclone" / "report" / "html" / "assets" / "js.py"


def _symlink_or_skip(link: Path, target: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not supported on this platform")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this environment")


# ── git diff ref validation (pre-subprocess gate) ─────────────────────


@pytest.mark.parametrize(
    "ref",
    [
        "HEAD",
        "main",
        "origin/main",
        "v1.2.3",
        "abc1234",
        "HEAD~1",
        "main^",
        "release@{1}",
        "abc..def",
    ],
)
def test_validate_git_diff_ref_accepts_safe_revision_expressions(ref: str) -> None:
    assert validate_git_diff_ref(ref) == ref


@pytest.mark.parametrize(
    "ref",
    [
        "",
        " ",
        " HEAD",
        "HEAD ",
        "HEAD\n",
        "--cached",
        "-",
        "./main",
        "../main",
        "main;rm",
        "main$(whoami)",
        "main`id`",
        "main|cat",
    ],
)
def test_validate_git_diff_ref_rejects_unsafe_revision_expressions(ref: str) -> None:
    with pytest.raises(ValueError, match="Invalid git diff ref"):
        validate_git_diff_ref(ref)


# ── MCP path normalization and root resolution ───────────────────────


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/module.py", "src/module.py"),
        ("./src/module.py", "src/module.py"),
        ("src/nested/", "src/nested"),
        (".", ""),
    ],
)
def test_mcp_normalize_relative_path_accepts_in_repo_paths(
    path: str, expected: str
) -> None:
    assert _normalize_relative_path(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "src/../../outside.py",
        "foo/../bar/../../etc/passwd",
    ],
)
def test_mcp_normalize_relative_path_rejects_traversal(path: str) -> None:
    with pytest.raises(MCPServiceContractError, match="path traversal not allowed"):
        _normalize_relative_path(path)


def test_mcp_resolve_root_requires_absolute_existing_directory(tmp_path: Path) -> None:
    assert _resolve_root(str(tmp_path.resolve())) == tmp_path.resolve()

    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        _resolve_root("relative/path")

    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        _resolve_root("")

    missing = tmp_path / "missing"
    with pytest.raises(MCPServiceContractError, match="does not exist"):
        _resolve_root(str(missing))

    file_root = tmp_path / "file.py"
    file_root.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(MCPServiceContractError, match="not a directory"):
        _resolve_root(str(file_root.resolve()))


def test_mcp_resolve_optional_path_rejects_external_absolute_by_default(
    tmp_path: Path,
) -> None:
    workspace = make_dir(tmp_path, "workspace")
    outside = write_file(tmp_path, "outside-cache.json", "{}")

    with pytest.raises(MCPServiceContractError, match="Invalid path"):
        _resolve_optional_path(str(outside.resolve()), workspace)

    resolved = _resolve_optional_path(
        str(outside.resolve()),
        workspace,
        allow_external_artifacts=True,
    )
    assert resolved == outside.resolve()

    inside = workspace / "cache.json"
    assert _resolve_optional_path("cache.json", workspace) == inside.resolve()

    with pytest.raises(MCPServiceContractError, match="Invalid path"):
        _resolve_optional_path(str(inside.resolve()), workspace)


def test_mcp_resolve_optional_path_resolves_relative_under_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    target = nested / "coverage.xml"
    target.write_text("<coverage/>", encoding="utf-8")

    assert _resolve_optional_path("nested/coverage.xml", workspace) == target.resolve()


# ── audit path containment (contrast with optional MCP paths) ────────


def test_resolve_audit_path_rejects_absolute_and_traversal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    assert (
        resolve_audit_path(
            root_path=root,
            value=".codeclone/db/audit.sqlite3",
        )
        == root / ".codeclone" / "db" / "audit.sqlite3"
    )

    with pytest.raises(AuditConfigError, match="relative to the repository root"):
        resolve_audit_path(root_path=root, value="/tmp/audit.sqlite3")

    with pytest.raises(AuditConfigError, match="must not contain"):
        resolve_audit_path(root_path=root, value="../outside.db")

    with pytest.raises(AuditConfigError, match="must end with"):
        resolve_audit_path(root_path=root, value="audit.json")


# ── scanner / worker path helpers ────────────────────────────────────


def test_resolved_path_under_root_accepts_in_repo_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    module = workspace / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("x = 1\n", encoding="utf-8")

    resolved = resolved_path_under_root(str(module), str(workspace))
    assert resolved == module.resolve()


def test_resolved_path_under_root_rejects_outside_targets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    link = workspace / "linked.py"
    outside_file = outside / "secret.py"
    outside_file.write_text("x = 1\n", encoding="utf-8")
    _symlink_or_skip(link, outside_file)

    assert resolved_path_under_root(str(link), str(workspace)) is None


def test_resolved_path_under_root_returns_none_on_resolve_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        raise OSError("broken resolve")

    monkeypatch.setattr(Path, "resolve", _broken_resolve)
    assert resolved_path_under_root("/workspace/mod.py", "/workspace") is None


@pytest.mark.parametrize(
    "root",
    ["/etc", "/proc", "/var"],
)
def test_iter_py_files_rejects_sensitive_roots(root: str) -> None:
    if not Path(root).exists():
        pytest.skip(f"{root} is not available on this platform")
    with pytest.raises(ValidationError):
        list(iter_py_files(root))


def test_iter_py_files_rejects_non_directory_root(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-dir.py"
    file_path.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="Root must be a directory"):
        list(iter_py_files(str(file_path)))


# ── HTML escaping invariants ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected_fragment"),
    [
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ('" onclick="alert(1)', "&quot; onclick=&quot;alert(1)"),
        ("`backtick`", "&#96;backtick&#96;"),
        ("\u2028line sep", "&#8232;line sep"),
        ("\u2029para sep", "&#8233;para sep"),
        (None, ""),
    ],
)
def test_escape_html_neutralizes_html_metacharacters(
    raw: object, expected_fragment: str
) -> None:
    escaped = _escape_html(raw)
    assert expected_fragment in escaped
    if isinstance(raw, str) and "<" in raw:
        assert "<" not in escaped


def test_html_report_js_avoids_dataset_innerhtml_regression() -> None:
    """Regression guard for DOM XSS pattern in clone metrics modal."""
    source = _HTML_JS_PATH.read_text(encoding="utf-8")
    assert "dlg.querySelector('#modal-body').innerHTML=items" not in source
    assert "body.innerHTML=tpl.innerHTML" not in source
    assert "document.importNode(tpl.content" in source
    assert "list.className='info-dl'" in source


# ── cache integrity (checksum contract; not secret-keyed) ────────────


def test_cache_checksum_verification_uses_constant_time_compare() -> None:
    payload: dict[str, object] = {"version": "test", "files": {}}
    signature = cache_payload_checksum(payload)
    assert verify_cache_payload_checksum(payload, signature) is True
    assert verify_cache_payload_checksum(payload, "0" * len(signature)) is False


def test_cache_checksum_is_stable_for_canonical_payload() -> None:
    payload: dict[str, object] = {"b": 2, "a": 1, "files": {}}
    first = cache_payload_checksum(payload)
    second = cache_payload_checksum({"a": 1, "b": 2, "files": {}})
    assert first == second


# ── suppressions: malformed input must not crash extraction ─────────


@pytest.mark.parametrize(
    "source",
    [
        "# codeclone: ignore[dead-code, unknown-rule]\n",
        "# codeclone: ignore[not a rule!]\n",
        "# codeclone ignore[dead-code]\n",
        '"""\n# codeclone: ignore[dead-code]\n',
    ],
)
def test_extract_suppression_directives_ignores_malformed_or_unknown_rules(
    source: str,
) -> None:
    directives = extract_suppression_directives(source)
    rule_ids = {rule for directive in directives for rule in directive.rules}
    assert rule_ids.issubset(SUPPORTED_RULE_IDS)


def test_extract_suppression_directives_accepts_supported_rule_ids() -> None:
    source = "# codeclone: ignore[dead-code]\ndef keep():\n    return 1\n"
    directives = extract_suppression_directives(source)
    assert len(directives) == 1
    assert directives[0].rules == ("dead-code",)


# ── scanner file-count cap (DoS guard) ───────────────────────────────


def test_iter_py_files_rejects_excessive_file_count(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"mod_{index}.py").write_text("x = 1\n", encoding="utf-8")

    assert len(list(iter_py_files(str(tmp_path), max_files=10))) == 5

    with pytest.raises(ValidationError, match="File count exceeds limit"):
        list(iter_py_files(str(tmp_path), max_files=3))


# ── baseline integrity tamper detection ──────────────────────────────


def test_baseline_load_rejects_tampered_clone_payload(
    tmp_path: Path,
) -> None:
    """Trusted baseline comparison must fail closed on payload tampering."""
    import json

    from codeclone.baseline import Baseline, build_container, canonical_container_bytes
    from codeclone.contracts.errors import BaselineValidationError
    from tests.test_baseline import _SCOPE_ID, _bundle

    func_id = f"{'a' * 64}|0-19"
    block_id = "|".join(("b" * 64,) * 4)
    baseline_path = tmp_path / "codeclone.baseline.json"
    baseline_path.write_bytes(
        canonical_container_bytes(build_container(_bundle(), _SCOPE_ID))
    )

    baseline = Baseline(baseline_path)
    baseline.load()
    assert baseline.functions == {func_id}
    assert baseline.blocks == {block_id}

    payload = json.loads(baseline_path.read_text("utf-8"))
    match payload["lanes"]:
        case dict() as lanes:
            pass
        case _:
            pytest.fail("baseline lanes must be an object")
    match lanes["clones.functions"]:
        case dict() as functions_lane:
            pass
        case _:
            pytest.fail("function clone lane must be an object")
    match functions_lane["payload"]:
        case dict() as clone_payload:
            pass
        case _:
            pytest.fail("function clone payload must be an object")
    clone_payload["items"] = [func_id, f"{'b' * 64}|20-39"]
    baseline_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tampered = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="lane digest mismatch") as exc:
        tampered.load()
    assert exc.value.status == "integrity_failed"


# ── workspace intent registry path safety ────────────────────────────


def test_workspace_intent_path_helper_rejects_escape_attempts(
    tmp_path: Path,
) -> None:
    from codeclone.surfaces.mcp._workspace_intents import (
        _is_safe_intent_path,
        intent_path,
        registry_dir,
    )

    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    valid = intent_path(
        root=tmp_path,
        pid=123,
        start_epoch=456,
        intent_id="intent-aaa-001",
    )
    assert _is_safe_intent_path(valid, registry) is True

    assert (
        _is_safe_intent_path(
            Path("../outside/123-456-intent-aaa-001.json"),
            registry,
        )
        is False
    )

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    symlink = registry / "123-456-intent-aaa-001.json"
    _symlink_or_skip(symlink, outside)
    assert _is_safe_intent_path(symlink, registry) is False


# ── git diff ref: control characters and injection payloads ──────────


@pytest.mark.parametrize(
    "ref",
    [
        "HEAD\x00",
        "main\r\n",
        "refs/heads/main;id",
        "$(curl attacker)",
        "HEAD && git status",
    ],
)
def test_validate_git_diff_ref_rejects_control_and_shell_metacharacters(
    ref: str,
) -> None:
    with pytest.raises(ValueError, match="Invalid git diff ref"):
        validate_git_diff_ref(ref)

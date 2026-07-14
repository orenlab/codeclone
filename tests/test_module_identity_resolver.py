# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Protocol

import pytest

from codeclone.contracts import MODULE_IDENTITY_VERSION
from codeclone.models import (
    ImportMount,
    ObservabilityConfig,
    PythonModuleIdentity,
    ResolvedSourceIdentity,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.paths.module_identity import (
    LEGACY_MODULE_IDENTITY_KILL_INVENTORY,
    ModuleIdentityCollisionError,
    build_module_identity_manifest,
    resolve_source_identity,
    validate_portable_paths,
)
from codeclone.paths.module_identity import (
    manifest as manifest_module,
)

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).parent / "fixtures" / "module_identity"


@pytest.fixture(autouse=True)
def _reset_observer() -> Iterator[None]:
    yield
    shutdown()


def _root_mount() -> tuple[ImportMount, ...]:
    return (ImportMount(path=".", module_prefix="", origin="root"),)


def _resolve(
    root: Path,
    relative: str,
    mounts: tuple[ImportMount, ...],
) -> ResolvedSourceIdentity:
    return resolve_source_identity(
        root=root,
        path=root / relative,
        import_mounts=mounts,
    )


def test_flat_root_mount_derives_package_context() -> None:
    root = _FIXTURES / "flat"

    package = _resolve(root, "pkg/__init__.py", _root_mount())
    module = _resolve(root, "pkg/mod.py", _root_mount())
    top_level = _resolve(root, "tool.py", _root_mount())

    assert package.python_module == PythonModuleIdentity(
        module="pkg",
        package="pkg",
        is_package=True,
        mount_path=".",
        origin="import_mount",
        node_kind="regular_package",
    )
    assert module.python_module == PythonModuleIdentity(
        module="pkg.mod",
        package="pkg",
        is_package=False,
        mount_path=".",
        origin="import_mount",
        node_kind="module_file",
    )
    assert top_level.python_module is not None
    assert top_level.python_module.module == "tool"
    assert top_level.python_module.package == ""


def test_src_mount_does_not_invent_analysis_mount_modules() -> None:
    root = _FIXTURES / "src_layout"
    mounts = (ImportMount(path="src", module_prefix="", origin="conventional_src"),)

    package = _resolve(root, "src/acme/__init__.py", mounts)
    service = _resolve(root, "src/acme/service.py", mounts)
    script = _resolve(root, "scripts/check.py", mounts)

    assert package.python_module is not None
    assert package.python_module.module == "acme"
    assert service.python_module is not None
    assert service.python_module.module == "acme.service"
    assert script.file.path == "scripts/check.py"
    assert script.python_module is None


def test_longest_mount_wins_then_namespace_prefix_is_applied() -> None:
    root = _FIXTURES / "mixed"
    mounts = (
        ImportMount(path="src", module_prefix="", origin="explicit"),
        ImportMount(path="src/pkg/nested", module_prefix="special", origin="explicit"),
        ImportMount(path="vendor", module_prefix="company", origin="explicit"),
    )

    primary = _resolve(root, "src/pkg/mod.py", mounts)
    nested = _resolve(root, "src/pkg/nested/tool.py", mounts)
    vendor = _resolve(root, "vendor/tools/check.py", mounts)
    plugin = _resolve(root, "plugins/my-plugin/check.py", mounts)

    assert primary.python_module is not None
    assert primary.python_module.module == "pkg.mod"
    assert nested.python_module is not None
    assert nested.python_module.module == "special.tool"
    assert vendor.python_module is not None
    assert vendor.python_module.module == "company.tools.check"
    assert plugin.python_module is None


@pytest.mark.parametrize(
    "relative",
    ["bad-name.py", "bad.name.py", "class.py", "snow☃.py"],
)
def test_invalid_dotted_segments_remain_file_only(relative: str) -> None:
    root = _FIXTURES / "flat"
    identity = _resolve(root, relative, _root_mount())
    assert identity.file.path == relative
    assert identity.python_module is None


def test_unicode_identifier_is_nfc_normalized() -> None:
    root = _FIXTURES / "flat"
    nfd_name = unicodedata.normalize("NFD", "café.py")
    identity = _resolve(root, nfd_name, _root_mount())

    assert identity.file.path == "café.py"
    assert identity.python_module is not None
    assert identity.python_module.module == "café"


def test_python_module_identity_rejects_mixed_discriminant_state() -> None:
    with pytest.raises(ValueError, match="package flag and node kind"):
        PythonModuleIdentity(
            module="pkg.mod",
            package="pkg",
            is_package=False,
            mount_path=".",
            origin="import_mount",
            node_kind="regular_package",
        )


def test_portable_profile_reports_sorted_collisions_and_failures() -> None:
    nfd = unicodedata.normalize("NFD", "café.py")
    verdict = validate_portable_paths(
        (
            "pkg/Name.py",
            "pkg/name.py",
            nfd,
            "café.py",
            "CON.txt",
            "pkg/trailing. ",
            "pkg/bad:name.py",
            "pkg/control\x01.py",
        )
    )

    assert verdict.eligible is False
    assert tuple((issue.kind, issue.paths) for issue in verdict.issues) == tuple(
        sorted(
            ((issue.kind, issue.paths) for issue in verdict.issues),
            key=lambda item: item,
        )
    )
    assert {issue.kind for issue in verdict.issues} == {
        "ascii_control",
        "case_collision",
        "nfc_collision",
        "trailing_dot_or_space",
        "windows_device",
        "windows_forbidden_byte",
    }
    assert "café.py" in verdict.normalized_paths


def test_separator_normalization_is_host_independent() -> None:
    posix = validate_portable_paths(("pkg/module.py",))
    windows = validate_portable_paths((r"pkg\module.py",))
    assert posix == windows

    root = _FIXTURES / "flat"
    posix_identity = _resolve(root, "pkg/module.py", _root_mount())
    windows_identity = _resolve(root, r"pkg\module.py", _root_mount())
    assert posix_identity == windows_identity


def test_manifest_bytes_and_digest_ignore_input_order() -> None:
    root = _FIXTURES / "flat"
    paths = (root / "tool.py", root / "pkg/mod.py", root / "pkg/__init__.py")

    forward = build_module_identity_manifest(
        root=root,
        paths=paths,
        import_mounts=_root_mount(),
        strategy="root",
    )
    reverse = build_module_identity_manifest(
        root=root,
        paths=reversed(paths),
        import_mounts=_root_mount(),
        strategy="root",
    )

    assert forward == reverse
    assert forward.manifest.module_identity_version == MODULE_IDENTITY_VERSION
    assert "/Users/" not in forward.manifest_json
    assert str(root) not in forward.manifest_json
    assert (
        forward.manifest_digest
        == hashlib.sha256(
            b"ccmi2:manifest\x00" + forward.manifest_json.encode("utf-8")
        ).hexdigest()
    )


def test_manifest_digest_is_hash_seed_independent() -> None:
    script = """
from pathlib import Path
from codeclone.models import ImportMount
from codeclone.paths.module_identity import build_module_identity_manifest
root = Path('tests/fixtures/module_identity/flat').resolve()
paths = {root / 'pkg/mod.py', root / 'tool.py', root / 'pkg/__init__.py'}
result = build_module_identity_manifest(
    root=root,
    paths=paths,
    import_mounts=(ImportMount(path='.', module_prefix='', origin='root'),),
    strategy='root',
)
print(result.manifest_digest)
"""

    digests: list[str] = []
    for seed in ("1", "999"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            (sys.executable, "-c", script),
            cwd=_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        digests.append(completed.stdout.strip())
    assert len(set(digests)) == 1


def test_manifest_collision_is_typed_and_carries_policy_digest() -> None:
    root = _FIXTURES / "flat"
    with pytest.raises(ModuleIdentityCollisionError) as raised:
        build_module_identity_manifest(
            root=root,
            paths=(root / "Pkg.py", root / "pkg.py"),
            import_mounts=_root_mount(),
            strategy="root",
        )
    assert len(raised.value.manifest_digest) == 64
    assert tuple(issue.kind for issue in raised.value.issues) == ("case_collision",)


class _RecordedSpan:
    def __init__(self, *, name: str) -> None:
        self.name = name
        self.status = "ok"
        self.counters: dict[str, int] = {}

    def set_counter(self, key: str, value: int) -> None:
        self.counters[key] = value


class _SpanFactory(Protocol):
    def __call__(self, *, name: str) -> AbstractContextManager[_RecordedSpan]: ...


def _recording_span_factory(
    recorded: list[_RecordedSpan],
) -> _SpanFactory:
    @contextmanager
    def recording_span(*, name: str) -> Iterator[_RecordedSpan]:
        observed = _RecordedSpan(name=name)
        recorded.append(observed)
        try:
            yield observed
        except Exception:
            observed.status = "error"
            raise

    return recording_span


def test_manifest_build_observer_on_off_byte_equality(tmp_path: Path) -> None:
    paths = (tmp_path / "pkg/mod.py", tmp_path / "tool.py")
    bootstrap(ObservabilityConfig(enabled=False))
    try:
        with operation(name="test.manifest", surface="test"):
            disabled = build_module_identity_manifest(
                root=tmp_path,
                paths=paths,
                import_mounts=_root_mount(),
                strategy="root",
            )
    finally:
        shutdown()

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="test.manifest", surface="test"):
            enabled = build_module_identity_manifest(
                root=tmp_path,
                paths=paths,
                import_mounts=_root_mount(),
                strategy="root",
            )
    finally:
        shutdown()

    assert disabled == enabled


@pytest.mark.parametrize(
    ("relative_paths", "expected_status", "expected_counters"),
    [
        (
            ("pkg/mod.py", "tool.py"),
            "ok",
            {
                "manifest_collisions": 0,
                "manifest_input_files": 2,
                "manifest_mounts": 1,
                "manifest_null_modules": 0,
                "manifest_portability_failures": 0,
                "manifest_resolved_modules": 2,
            },
        ),
        (
            ("CON.py",),
            "ok",
            {
                "manifest_collisions": 0,
                "manifest_input_files": 1,
                "manifest_mounts": 1,
                "manifest_null_modules": 0,
                "manifest_portability_failures": 1,
                "manifest_resolved_modules": 1,
            },
        ),
        (
            ("Pkg.py", "pkg.py"),
            "error",
            {
                "manifest_collisions": 1,
                "manifest_input_files": 2,
                "manifest_mounts": 1,
                "manifest_null_modules": 0,
                "manifest_portability_failures": 0,
                "manifest_resolved_modules": 2,
            },
        ),
    ],
)
def test_manifest_build_has_one_bounded_span_for_each_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_paths: tuple[str, ...],
    expected_status: str,
    expected_counters: dict[str, int],
) -> None:
    recorded: list[_RecordedSpan] = []
    monkeypatch.setattr(manifest_module, "span", _recording_span_factory(recorded))
    paths = tuple(tmp_path / relative for relative in relative_paths)

    if expected_status == "error":
        with pytest.raises(ModuleIdentityCollisionError):
            build_module_identity_manifest(
                root=tmp_path,
                paths=paths,
                import_mounts=_root_mount(),
                strategy="root",
            )
    else:
        result = build_module_identity_manifest(
            root=tmp_path,
            paths=paths,
            import_mounts=_root_mount(),
            strategy="root",
        )
        assert result.portability.eligible is (relative_paths != ("CON.py",))

    assert len(recorded) == 1
    assert recorded[0].name == "manifest.build"
    assert recorded[0].status == expected_status
    assert recorded[0].counters == expected_counters


def test_package_imports_only_contract_model_observer_dependencies() -> None:
    package_root = _ROOT / "codeclone" / "paths" / "module_identity"
    forbidden_imports: list[str] = []
    for path in sorted(package_root.glob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level:
                continue
            module = node.module or ""
            if module.startswith("codeclone.") and module not in {
                "codeclone.contracts",
                "codeclone.models",
                "codeclone.observability",
            }:
                forbidden_imports.append(f"{path.name}:{module}")
        assert "from codeclone.scanner" not in path.read_text("utf-8")
        assert "module_name_from_path" not in path.read_text("utf-8")
        assert "@dataclass" not in path.read_text("utf-8")
    assert forbidden_imports == []


def test_legacy_derivation_owners_are_finite_and_phase_bound() -> None:
    inventory = dict(LEGACY_MODULE_IDENTITY_KILL_INVENTORY)
    assert set(inventory.values()) == {"39H", "39O", "39P", "39Q", "39R"}
    assert len(inventory) == len(LEGACY_MODULE_IDENTITY_KILL_INVENTORY)

    needles = (
        'with_suffix("")',
        'removesuffix(".py").replace("/", ".")',
        'replace("/", ".").strip(".")',
        'replace(".", "/") + ".py"',
    )
    ungoverned: list[str] = []
    for path in sorted((_ROOT / "codeclone").rglob("*.py")):
        relative = path.relative_to(_ROOT).as_posix()
        if relative.startswith("codeclone/paths/module_identity/"):
            continue
        source = path.read_text("utf-8")
        if any(needle in source for needle in needles) and relative not in inventory:
            ungoverned.append(relative)
    assert ungoverned == []

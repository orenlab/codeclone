# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import dataclass

from ..models import (
    SecuritySurface,
    SecuritySurfaceCategory,
    SecuritySurfaceClassificationMode,
    SecuritySurfaceEvidenceKind,
    SecuritySurfaceLocationScope,
)


@dataclass(frozen=True, slots=True)
class _ImportRule:
    module_prefix: str
    category: SecuritySurfaceCategory
    capability: str


@dataclass(frozen=True, slots=True)
class _CallRule:
    symbol: str
    category: SecuritySurfaceCategory
    capability: str
    prefix_match: bool = False


_BUILTIN_RULES: dict[str, tuple[SecuritySurfaceCategory, str]] = {
    "__import__": ("dynamic_loading", "builtin_import"),
    "compile": ("dynamic_execution", "dynamic_compile"),
    "eval": ("dynamic_execution", "dynamic_eval"),
    "exec": ("dynamic_execution", "dynamic_exec"),
}

_IMPORT_RULES: tuple[_ImportRule, ...] = (
    _ImportRule("aiohttp", "network_boundary", "aiohttp_import"),
    _ImportRule("asyncpg", "database_boundary", "asyncpg_import"),
    _ImportRule("authlib", "identity_token", "authlib_import"),
    _ImportRule("bcrypt", "identity_token", "bcrypt_import"),
    _ImportRule("cloudpickle", "deserialization", "cloudpickle_import"),
    _ImportRule("cryptography", "crypto_transport", "cryptography_import"),
    _ImportRule("dill", "deserialization", "dill_import"),
    _ImportRule("django.http", "network_boundary", "django_http_import"),
    _ImportRule("fastapi", "network_boundary", "fastapi_import"),
    _ImportRule("flask", "network_boundary", "flask_import"),
    _ImportRule("grpc", "network_boundary", "grpc_import"),
    _ImportRule("hmac", "crypto_transport", "hmac_import"),
    _ImportRule("http.server", "network_boundary", "http_server_import"),
    _ImportRule("httpx", "network_boundary", "httpx_import"),
    _ImportRule("importlib", "dynamic_loading", "importlib_import"),
    _ImportRule("itsdangerous", "identity_token", "itsdangerous_import"),
    _ImportRule("jsonpickle", "deserialization", "jsonpickle_import"),
    _ImportRule("jwt", "identity_token", "jwt_import"),
    _ImportRule("marshal", "deserialization", "marshal_import"),
    _ImportRule("OpenSSL", "crypto_transport", "openssl_import"),
    _ImportRule("passlib", "identity_token", "passlib_import"),
    _ImportRule("pickle", "deserialization", "pickle_import"),
    _ImportRule("psycopg", "database_boundary", "psycopg_import"),
    _ImportRule("psycopg2", "database_boundary", "psycopg2_import"),
    _ImportRule("pymysql", "database_boundary", "pymysql_import"),
    _ImportRule("redis", "database_boundary", "redis_import"),
    _ImportRule("requests", "network_boundary", "requests_import"),
    _ImportRule("ruamel.yaml", "deserialization", "ruamel_yaml_import"),
    _ImportRule("runpy", "dynamic_loading", "runpy_import"),
    _ImportRule("secrets", "crypto_transport", "secrets_import"),
    _ImportRule("shelve", "deserialization", "shelve_import"),
    _ImportRule("socket", "network_boundary", "socket_import"),
    _ImportRule("sqlalchemy", "database_boundary", "sqlalchemy_import"),
    _ImportRule("sqlite3", "database_boundary", "sqlite3_import"),
    _ImportRule("ssl", "crypto_transport", "ssl_import"),
    _ImportRule("subprocess", "process_boundary", "subprocess_import"),
    _ImportRule("tarfile", "archive_extraction", "tarfile_import"),
    _ImportRule("websockets", "network_boundary", "websockets_import"),
    _ImportRule("urllib", "network_boundary", "urllib_import"),
    _ImportRule("yaml", "deserialization", "yaml_import"),
    _ImportRule("zipfile", "archive_extraction", "zipfile_import"),
)

_CALL_RULES: tuple[_CallRule, ...] = (
    _CallRule(
        "asyncio.create_subprocess_exec", "process_boundary", "asyncio_subprocess_exec"
    ),
    _CallRule(
        "asyncio.create_subprocess_shell",
        "process_boundary",
        "asyncio_subprocess_shell",
    ),
    _CallRule("cloudpickle.load", "deserialization", "cloudpickle_load"),
    _CallRule("cloudpickle.loads", "deserialization", "cloudpickle_loads"),
    _CallRule("dill.load", "deserialization", "dill_load"),
    _CallRule("dill.loads", "deserialization", "dill_loads"),
    _CallRule("importlib.import_module", "dynamic_loading", "import_module"),
    _CallRule(
        "importlib.util.spec_from_file_location",
        "dynamic_loading",
        "import_spec_from_file",
    ),
    _CallRule("jsonpickle.decode", "deserialization", "jsonpickle_decode"),
    _CallRule("marshal.load", "deserialization", "marshal_load"),
    _CallRule("marshal.loads", "deserialization", "marshal_loads"),
    _CallRule("os.chmod", "filesystem_mutation", "os_chmod"),
    _CallRule("os.chown", "filesystem_mutation", "os_chown"),
    _CallRule("os.makedirs", "filesystem_mutation", "os_makedirs"),
    _CallRule("os.remove", "filesystem_mutation", "os_remove"),
    _CallRule("os.rename", "filesystem_mutation", "os_rename"),
    _CallRule("os.replace", "filesystem_mutation", "os_replace"),
    _CallRule("os.rmdir", "filesystem_mutation", "os_rmdir"),
    _CallRule("os.spawn", "process_boundary", "os_spawn", prefix_match=True),
    _CallRule("os.system", "process_boundary", "os_system"),
    _CallRule("os.unlink", "filesystem_mutation", "os_unlink"),
    _CallRule("pathlib.Path.chmod", "filesystem_mutation", "pathlib_chmod"),
    _CallRule("pathlib.Path.mkdir", "filesystem_mutation", "pathlib_mkdir"),
    _CallRule("pathlib.Path.open", "filesystem_mutation", "pathlib_open_write"),
    _CallRule("pathlib.Path.rename", "filesystem_mutation", "pathlib_rename"),
    _CallRule("pathlib.Path.replace", "filesystem_mutation", "pathlib_replace"),
    _CallRule("pathlib.Path.rmdir", "filesystem_mutation", "pathlib_rmdir"),
    _CallRule("pathlib.Path.touch", "filesystem_mutation", "pathlib_touch"),
    _CallRule("pathlib.Path.unlink", "filesystem_mutation", "pathlib_unlink"),
    _CallRule("pathlib.Path.write_bytes", "filesystem_mutation", "pathlib_write_bytes"),
    _CallRule("pathlib.Path.write_text", "filesystem_mutation", "pathlib_write_text"),
    _CallRule("pickle.load", "deserialization", "pickle_load"),
    _CallRule("pickle.loads", "deserialization", "pickle_loads"),
    _CallRule("pty.spawn", "process_boundary", "pty_spawn"),
    _CallRule("runpy.run_module", "dynamic_loading", "run_module"),
    _CallRule("runpy.run_path", "dynamic_loading", "run_path"),
    _CallRule("shutil.move", "filesystem_mutation", "shutil_move"),
    _CallRule("shutil.rmtree", "filesystem_mutation", "shutil_rmtree"),
    _CallRule("shutil.unpack_archive", "archive_extraction", "unpack_archive"),
    _CallRule("subprocess.call", "process_boundary", "subprocess_call"),
    _CallRule("subprocess.check_call", "process_boundary", "subprocess_check_call"),
    _CallRule("subprocess.check_output", "process_boundary", "subprocess_check_output"),
    _CallRule("subprocess.Popen", "process_boundary", "subprocess_popen"),
    _CallRule("subprocess.run", "process_boundary", "subprocess_run"),
    _CallRule(
        "tarfile.open.extract", "archive_extraction", "tar_extract", prefix_match=True
    ),
    _CallRule("tempfile.mkdtemp", "filesystem_mutation", "tempfile_mkdtemp"),
    _CallRule(
        "tempfile.NamedTemporaryFile",
        "filesystem_mutation",
        "tempfile_named_temporary_file",
    ),
    _CallRule("yaml.load", "deserialization", "yaml_load"),
    _CallRule("yaml.unsafe_load", "deserialization", "yaml_unsafe_load"),
    _CallRule(
        "zipfile.ZipFile.extract",
        "archive_extraction",
        "zip_extract",
        prefix_match=True,
    ),
)


def _node_start_line(node: ast.AST) -> int | None:
    line = getattr(node, "lineno", None)
    if isinstance(line, int) and line > 0:
        return line
    return None


def _node_end_line(node: ast.AST) -> int:
    start_line = _node_start_line(node)
    if start_line is None:
        return 0
    end_line = getattr(node, "end_lineno", None)
    return (
        end_line if isinstance(end_line, int) and end_line >= start_line else start_line
    )


def _is_type_checking_guard(test: ast.AST) -> bool:
    match test:
        case ast.Name(id="TYPE_CHECKING"):
            return True
        case ast.Attribute(value=ast.Name(id="typing"), attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _matches_import_prefix(imported_name: str, module_prefix: str) -> bool:
    return imported_name == module_prefix or imported_name.startswith(
        module_prefix + "."
    )


def _matches_call_rule(symbol: str, rule: _CallRule) -> bool:
    return symbol == rule.symbol or (
        rule.prefix_match and symbol.startswith(rule.symbol)
    )


class _SecuritySurfaceVisitor(ast.NodeVisitor):
    __slots__ = (
        "_aliases",
        "_callable_depth",
        "_class_depth",
        "_filepath",
        "_module_name",
        "_scope_stack",
        "_seen",
        "items",
    )

    def __init__(self, *, module_name: str, filepath: str) -> None:
        self._aliases: dict[str, str] = {}
        self._module_name = module_name
        self._filepath = filepath
        self._scope_stack: list[str] = []
        self._callable_depth = 0
        self._class_depth = 0
        self._seen: set[
            tuple[
                str,
                str,
                str,
                int,
                int,
                str,
                str,
                str,
            ]
        ] = set()
        self.items: list[SecuritySurface] = []

    def _current_scope(self) -> tuple[str, SecuritySurfaceLocationScope]:
        if not self._scope_stack:
            return self._module_name, "module"
        return (
            f"{self._module_name}:{'.'.join(self._scope_stack)}",
            "callable" if self._callable_depth > 0 else "class",
        )

    def _emit(
        self,
        *,
        category: SecuritySurfaceCategory,
        capability: str,
        node: ast.AST,
        classification_mode: SecuritySurfaceClassificationMode,
        evidence_kind: SecuritySurfaceEvidenceKind,
        evidence_symbol: str,
    ) -> None:
        start_line = _node_start_line(node)
        if start_line is None:
            return
        qualname, location_scope = self._current_scope()
        key = (
            category,
            capability,
            qualname,
            start_line,
            _node_end_line(node),
            classification_mode,
            evidence_kind,
            evidence_symbol,
        )
        if key in self._seen:
            return
        self._seen.add(key)
        self.items.append(
            SecuritySurface(
                category=category,
                capability=capability,
                module=self._module_name,
                filepath=self._filepath,
                qualname=qualname,
                start_line=start_line,
                end_line=_node_end_line(node),
                location_scope=location_scope,
                classification_mode=classification_mode,
                evidence_kind=evidence_kind,
                evidence_symbol=evidence_symbol,
            )
        )

    def _register_import_alias(self, *, bound_name: str, imported_name: str) -> None:
        clean_bound = bound_name.strip()
        clean_imported = imported_name.strip()
        if clean_bound and clean_imported:
            self._aliases[clean_bound] = clean_imported

    def _emit_import_matches(self, *, imported_name: str, node: ast.AST) -> None:
        for rule in _IMPORT_RULES:
            if _matches_import_prefix(imported_name, rule.module_prefix):
                self._emit(
                    category=rule.category,
                    capability=rule.capability,
                    node=node,
                    classification_mode="exact_import",
                    evidence_kind="import",
                    evidence_symbol=imported_name,
                )

    def _resolve_expr_symbol(self, node: ast.AST) -> str | None:
        match node:
            case ast.Name(id=name):
                resolved = self._aliases.get(name)
                if resolved is not None:
                    return resolved
                if name in _BUILTIN_RULES or name == "open":
                    return name
                return None
            case ast.Attribute(value=value, attr=attr):
                parent = self._resolve_expr_symbol(value)
                if parent is None:
                    return None
                return f"{parent}.{attr}"
            case ast.Call(func=func):
                return self._resolve_expr_symbol(func)
            case _:
                return None

    def _mode_from_open_call(self, node: ast.Call) -> str | None:
        mode_arg: ast.AST | None = None
        if len(node.args) >= 2:
            mode_arg = node.args[1]
        else:
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode_arg = keyword.value
                    break
        if not isinstance(mode_arg, ast.Constant) or not isinstance(
            mode_arg.value, str
        ):
            return None
        mode = mode_arg.value
        if any(marker in mode for marker in ("w", "a", "x", "+")):
            return mode
        return None

    def _emit_call_matches(self, node: ast.Call) -> None:
        symbol = self._resolve_expr_symbol(node.func)
        if symbol is None:
            return
        if symbol in _BUILTIN_RULES:
            category, capability = _BUILTIN_RULES[symbol]
            self._emit(
                category=category,
                capability=capability,
                node=node,
                classification_mode="exact_builtin",
                evidence_kind="builtin",
                evidence_symbol=symbol,
            )
        if symbol in {"open", "pathlib.Path.open"}:
            mode = self._mode_from_open_call(node)
            if mode is not None:
                capability = (
                    "pathlib_open_write"
                    if symbol == "pathlib.Path.open"
                    else "builtin_open_write"
                )
                self._emit(
                    category="filesystem_mutation",
                    capability=capability,
                    node=node,
                    classification_mode="exact_call",
                    evidence_kind="call",
                    evidence_symbol=f"{symbol}[mode={mode}]",
                )
        for rule in _CALL_RULES:
            if _matches_call_rule(symbol, rule):
                self._emit(
                    category=rule.category,
                    capability=rule.capability,
                    node=node,
                    classification_mode="exact_call",
                    evidence_kind="call",
                    evidence_symbol=symbol,
                )

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            full_name = alias.name.strip()
            if not full_name:
                continue
            bound_name = alias.asname or full_name.split(".", maxsplit=1)[0]
            self._register_import_alias(
                bound_name=bound_name,
                imported_name=full_name if alias.asname else bound_name,
            )
            self._emit_import_matches(imported_name=full_name, node=node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (
            node.level != 0
            or not isinstance(node.module, str)
            or not node.module.strip()
        ):
            return
        module_name = node.module.strip()
        for alias in node.names:
            if alias.name == "*":
                continue
            full_name = f"{module_name}.{alias.name}"
            self._register_import_alias(
                bound_name=alias.asname or alias.name,
                imported_name=full_name,
            )
            self._emit_import_matches(imported_name=full_name, node=node)

    def _visit_scoped_node(
        self,
        node: ast.AST,
        *,
        scope_name: str,
        is_callable: bool,
    ) -> None:
        self._scope_stack.append(scope_name)
        if is_callable:
            self._callable_depth += 1
        else:
            self._class_depth += 1
        self.generic_visit(node)
        if is_callable:
            self._callable_depth -= 1
        else:
            self._class_depth -= 1
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped_node(node, scope_name=node.name, is_callable=False)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped_node(node, scope_name=node.name, is_callable=True)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped_node(node, scope_name=node.name, is_callable=True)

    def visit_Call(self, node: ast.Call) -> None:
        self._emit_call_matches(node)
        self.generic_visit(node)


def collect_security_surfaces(
    *,
    tree: ast.Module,
    module_name: str,
    filepath: str,
) -> tuple[SecuritySurface, ...]:
    visitor = _SecuritySurfaceVisitor(module_name=module_name, filepath=filepath)
    visitor.visit(tree)
    return tuple(
        sorted(
            visitor.items,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.category,
                item.capability,
                item.evidence_symbol,
                item.classification_mode,
            ),
        )
    )


__all__ = ["collect_security_surfaces"]

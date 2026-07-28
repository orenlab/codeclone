# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import TypeAlias

from ..analysis.ast_helpers import ast_node_end_line, ast_node_start_line
from ..models import (
    DynamicLoadArgument,
    EventKind,
    FactRef,
    SecuritySurfaceCategory,
    SemanticEvent,
)

_ImportRule: TypeAlias = tuple[str, SecuritySurfaceCategory, str]
_CallRule: TypeAlias = tuple[str, SecuritySurfaceCategory, str, bool]

# The mechanisms this phase projects into dependency evidence. runpy stays a
# named follow-up: category alone is too broad a gate.
_DYNAMIC_LOAD_CAPABILITIES: frozenset[str] = frozenset(
    {"builtin_import", "import_module", "import_spec_from_file"}
)

_BUILTIN_RULES: dict[str, tuple[SecuritySurfaceCategory, str]] = {
    "__import__": ("dynamic_loading", "builtin_import"),
    "compile": ("dynamic_execution", "dynamic_compile"),
    "eval": ("dynamic_execution", "dynamic_eval"),
    "exec": ("dynamic_execution", "dynamic_exec"),
}

_IMPORT_RULES: tuple[_ImportRule, ...] = (
    ("aiohttp", "network_boundary", "aiohttp_import"),
    ("asyncpg", "database_boundary", "asyncpg_import"),
    ("authlib", "identity_token", "authlib_import"),
    ("bcrypt", "identity_token", "bcrypt_import"),
    ("cloudpickle", "deserialization", "cloudpickle_import"),
    ("cryptography", "crypto_transport", "cryptography_import"),
    ("dill", "deserialization", "dill_import"),
    ("django.http", "network_boundary", "django_http_import"),
    ("fastapi", "network_boundary", "fastapi_import"),
    ("flask", "network_boundary", "flask_import"),
    ("grpc", "network_boundary", "grpc_import"),
    ("hmac", "crypto_transport", "hmac_import"),
    ("http.server", "network_boundary", "http_server_import"),
    ("httpx", "network_boundary", "httpx_import"),
    ("importlib", "dynamic_loading", "importlib_import"),
    ("itsdangerous", "identity_token", "itsdangerous_import"),
    ("jsonpickle", "deserialization", "jsonpickle_import"),
    ("jwt", "identity_token", "jwt_import"),
    ("marshal", "deserialization", "marshal_import"),
    ("OpenSSL", "crypto_transport", "openssl_import"),
    ("passlib", "identity_token", "passlib_import"),
    ("pickle", "deserialization", "pickle_import"),
    ("psycopg", "database_boundary", "psycopg_import"),
    ("psycopg2", "database_boundary", "psycopg2_import"),
    ("pymysql", "database_boundary", "pymysql_import"),
    ("redis", "database_boundary", "redis_import"),
    ("requests", "network_boundary", "requests_import"),
    ("ruamel.yaml", "deserialization", "ruamel_yaml_import"),
    ("runpy", "dynamic_loading", "runpy_import"),
    ("secrets", "crypto_transport", "secrets_import"),
    ("shelve", "deserialization", "shelve_import"),
    ("socket", "network_boundary", "socket_import"),
    ("sqlalchemy", "database_boundary", "sqlalchemy_import"),
    ("sqlite3", "database_boundary", "sqlite3_import"),
    ("ssl", "crypto_transport", "ssl_import"),
    ("subprocess", "process_boundary", "subprocess_import"),
    ("tarfile", "archive_extraction", "tarfile_import"),
    ("websockets", "network_boundary", "websockets_import"),
    ("urllib", "network_boundary", "urllib_import"),
    ("yaml", "deserialization", "yaml_import"),
    ("zipfile", "archive_extraction", "zipfile_import"),
)

_CALL_RULES: tuple[_CallRule, ...] = (
    (
        "asyncio.create_subprocess_exec",
        "process_boundary",
        "asyncio_subprocess_exec",
        False,
    ),
    (
        "asyncio.create_subprocess_shell",
        "process_boundary",
        "asyncio_subprocess_shell",
        False,
    ),
    ("cloudpickle.load", "deserialization", "cloudpickle_load", False),
    ("cloudpickle.loads", "deserialization", "cloudpickle_loads", False),
    ("dill.load", "deserialization", "dill_load", False),
    ("dill.loads", "deserialization", "dill_loads", False),
    ("importlib.import_module", "dynamic_loading", "import_module", False),
    (
        "importlib.util.spec_from_file_location",
        "dynamic_loading",
        "import_spec_from_file",
        False,
    ),
    ("jsonpickle.decode", "deserialization", "jsonpickle_decode", False),
    ("marshal.load", "deserialization", "marshal_load", False),
    ("marshal.loads", "deserialization", "marshal_loads", False),
    ("os.chmod", "filesystem_mutation", "os_chmod", False),
    ("os.chown", "filesystem_mutation", "os_chown", False),
    ("os.makedirs", "filesystem_mutation", "os_makedirs", False),
    ("os.remove", "filesystem_mutation", "os_remove", False),
    ("os.rename", "filesystem_mutation", "os_rename", False),
    ("os.replace", "filesystem_mutation", "os_replace", False),
    ("os.rmdir", "filesystem_mutation", "os_rmdir", False),
    ("os.spawn", "process_boundary", "os_spawn", True),
    ("os.system", "process_boundary", "os_system", False),
    ("os.unlink", "filesystem_mutation", "os_unlink", False),
    ("pathlib.Path.chmod", "filesystem_mutation", "pathlib_chmod", False),
    ("pathlib.Path.mkdir", "filesystem_mutation", "pathlib_mkdir", False),
    ("pathlib.Path.open", "filesystem_mutation", "pathlib_open_write", False),
    ("pathlib.Path.rename", "filesystem_mutation", "pathlib_rename", False),
    ("pathlib.Path.replace", "filesystem_mutation", "pathlib_replace", False),
    ("pathlib.Path.rmdir", "filesystem_mutation", "pathlib_rmdir", False),
    ("pathlib.Path.touch", "filesystem_mutation", "pathlib_touch", False),
    ("pathlib.Path.unlink", "filesystem_mutation", "pathlib_unlink", False),
    ("pathlib.Path.write_bytes", "filesystem_mutation", "pathlib_write_bytes", False),
    ("pathlib.Path.write_text", "filesystem_mutation", "pathlib_write_text", False),
    ("pickle.load", "deserialization", "pickle_load", False),
    ("pickle.loads", "deserialization", "pickle_loads", False),
    ("pty.spawn", "process_boundary", "pty_spawn", False),
    ("runpy.run_module", "dynamic_loading", "run_module", False),
    ("runpy.run_path", "dynamic_loading", "run_path", False),
    ("shutil.move", "filesystem_mutation", "shutil_move", False),
    ("shutil.rmtree", "filesystem_mutation", "shutil_rmtree", False),
    ("shutil.unpack_archive", "archive_extraction", "unpack_archive", False),
    ("subprocess.call", "process_boundary", "subprocess_call", False),
    ("subprocess.check_call", "process_boundary", "subprocess_check_call", False),
    ("subprocess.check_output", "process_boundary", "subprocess_check_output", False),
    ("subprocess.Popen", "process_boundary", "subprocess_popen", False),
    ("subprocess.run", "process_boundary", "subprocess_run", False),
    ("tarfile.open.extract", "archive_extraction", "tar_extract", True),
    ("tempfile.mkdtemp", "filesystem_mutation", "tempfile_mkdtemp", False),
    (
        "tempfile.NamedTemporaryFile",
        "filesystem_mutation",
        "tempfile_named_temporary_file",
        False,
    ),
    ("yaml.load", "deserialization", "yaml_load", False),
    ("yaml.unsafe_load", "deserialization", "yaml_unsafe_load", False),
    ("zipfile.ZipFile.extract", "archive_extraction", "zip_extract", True),
)

_EVENT_COUNTER_KEYS: dict[EventKind, str] = {
    "artifact_write": "events_by_kind.artifact_write",
    "assign": "events_by_kind.assign",
    "compatibility_check": "events_by_kind.compatibility_check",
    "compute_digest": "events_by_kind.compute_digest",
    "construct": "events_by_kind.construct",
    "field_write": "events_by_kind.field_write",
    "publish_event": "events_by_kind.publish_event",
    "resolve_identity": "events_by_kind.resolve_identity",
    "return_value": "events_by_kind.return_value",
    "serialize_field": "events_by_kind.serialize_field",
    "security_observation": "events_by_kind.security_observation",
}


def event_counter_key(kind: EventKind) -> str:
    return _EVENT_COUNTER_KEYS[kind]


def _matches_import_prefix(imported_name: str, module_prefix: str) -> bool:
    return imported_name == module_prefix or imported_name.startswith(
        module_prefix + "."
    )


def _matches_call_rule(symbol: str, rule: _CallRule) -> bool:
    expected, _category, _capability, prefix_match = rule
    return symbol == expected or (prefix_match and symbol.startswith(expected))


def _target_name(target: ast.expr) -> str:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        prefix = _target_name(target.value)
        return f"{prefix}.{target.attr}" if prefix else target.attr
    if isinstance(target, ast.Subscript):
        return _target_name(target.value)
    return type(target).__name__


def _input_ref(node: ast.AST | None) -> FactRef:
    if node is None:
        return FactRef(kind="const", ref="none")
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None or isinstance(value, bool | int | float):
            return FactRef(kind="const", ref=f"{type(value).__name__}:{value}")
        if isinstance(value, str):
            return FactRef(kind="const", ref=f"str_length:{len(value)}")
        if isinstance(value, bytes):
            return FactRef(kind="const", ref=f"bytes_length:{len(value)}")
        return FactRef(kind="const", ref=type(value).__name__)
    name = _target_name(node) if isinstance(node, ast.expr) else type(node).__name__
    return FactRef(kind="unresolved", ref=name)


class SemanticEventCollector:
    __slots__ = (
        "_aliases",
        "_events",
        "_filepath",
        "_module_name",
        "_ordinals",
        "_seen_security",
        "_top_level_class_names",
    )

    def __init__(
        self,
        *,
        module_name: str,
        filepath: str,
        top_level_class_names: frozenset[str],
    ) -> None:
        self._aliases: dict[str, str] = {}
        self._events: list[SemanticEvent] = []
        self._module_name = module_name
        self._filepath = filepath
        self._top_level_class_names = top_level_class_names
        self._ordinals: dict[str, int] = {}
        self._seen_security: set[tuple[str, str, str, int, int, str, str, str]] = set()

    @property
    def events(self) -> tuple[SemanticEvent, ...]:
        return tuple(self._events)

    def _next_event_id(self, qualname: str) -> str:
        ordinal = self._ordinals.get(qualname, 0) + 1
        self._ordinals[qualname] = ordinal
        return f"{qualname}#{ordinal:06d}"

    @staticmethod
    def _dynamic_load_argument(
        node: ast.AST,
        capability: str,
    ) -> DynamicLoadArgument | None:
        """Read the module argument of a dynamic-load call, or record opacity."""

        if capability not in _DYNAMIC_LOAD_CAPABILITIES or not isinstance(
            node, ast.Call
        ):
            return None
        argument = (
            node.args[0]
            if node.args
            else next(
                (keyword.value for keyword in node.keywords if keyword.arg == "name"),
                None,
            )
        )
        if (
            isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
            and argument.value
        ):
            return DynamicLoadArgument(module=argument.value)
        return DynamicLoadArgument(module=None)

    def _emit(
        self,
        *,
        kind: EventKind,
        subject: str,
        inputs: tuple[FactRef, ...],
        node: ast.AST,
        qualname: str,
        guards: tuple[str, ...],
        resolution: str = "resolved",
        output: bool = False,
        dynamic_load: DynamicLoadArgument | None = None,
    ) -> None:
        start_line = ast_node_start_line(node)
        if start_line is None:
            return
        event_id = self._next_event_id(qualname)
        self._events.append(
            SemanticEvent(
                event_id=event_id,
                kind=kind,
                subject=subject,
                inputs=inputs,
                output=FactRef(kind="event", ref=event_id) if output else None,
                guards=guards,
                location=(self._filepath, start_line),
                resolution="resolved" if resolution == "resolved" else "unavailable",
                dynamic_load=dynamic_load,
            )
        )

    def _register_import_alias(self, *, bound_name: str, imported_name: str) -> None:
        clean_bound = bound_name.strip()
        clean_imported = imported_name.strip()
        if clean_bound and clean_imported:
            self._aliases[clean_bound] = clean_imported

    def _resolve_symbol(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            resolved = self._aliases.get(node.id)
            if resolved is not None:
                return resolved
            if node.id in _BUILTIN_RULES or node.id == "open":
                return node.id
            if node.id in self._top_level_class_names:
                return f"{self._module_name}:{node.id}"
            return None
        if isinstance(node, ast.Attribute):
            parent = self._resolve_symbol(node.value)
            return f"{parent}.{node.attr}" if parent is not None else None
        if isinstance(node, ast.Call):
            return self._resolve_symbol(node.func)
        return None

    @staticmethod
    def _mode_from_open_call(node: ast.Call) -> str | None:
        mode_arg: ast.AST | None = node.args[1] if len(node.args) >= 2 else None
        if mode_arg is None:
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode_arg = keyword.value
                    break
        if not isinstance(mode_arg, ast.Constant) or not isinstance(
            mode_arg.value, str
        ):
            return None
        return (
            mode_arg.value
            if any(marker in mode_arg.value for marker in ("w", "a", "x", "+"))
            else None
        )

    def _emit_security(
        self,
        *,
        category: SecuritySurfaceCategory,
        capability: str,
        node: ast.AST,
        qualname: str,
        location_scope: str,
        classification_mode: str,
        evidence_kind: str,
        evidence_symbol: str,
        guards: tuple[str, ...],
    ) -> None:
        start_line = ast_node_start_line(node)
        if start_line is None:
            return
        end_line = ast_node_end_line(node)
        key = (
            category,
            capability,
            qualname,
            start_line,
            end_line,
            classification_mode,
            evidence_kind,
            evidence_symbol,
        )
        if key in self._seen_security:
            return
        self._seen_security.add(key)
        inputs = tuple(
            FactRef(kind="const", ref=value)
            for value in (
                f"security.category={category}",
                f"security.capability={capability}",
                f"security.module={self._module_name}",
                f"security.qualname={qualname}",
                f"security.end_line={end_line}",
                f"security.location_scope={location_scope}",
                f"security.classification_mode={classification_mode}",
                f"security.evidence_kind={evidence_kind}",
            )
        )
        self._emit(
            kind="security_observation",
            subject=evidence_symbol,
            inputs=inputs,
            node=node,
            qualname=qualname,
            guards=guards,
            dynamic_load=self._dynamic_load_argument(node, capability),
        )

    def _observe_import(
        self,
        node: ast.Import,
        *,
        qualname: str,
        location_scope: str,
        guards: tuple[str, ...],
    ) -> None:
        for alias in node.names:
            full_name = alias.name.strip()
            if not full_name:
                continue
            bound_name = alias.asname or full_name.split(".", maxsplit=1)[0]
            self._register_import_alias(
                bound_name=bound_name,
                imported_name=full_name if alias.asname else bound_name,
            )
            for module_prefix, category, capability in _IMPORT_RULES:
                if _matches_import_prefix(full_name, module_prefix):
                    self._emit_security(
                        category=category,
                        capability=capability,
                        node=node,
                        qualname=qualname,
                        location_scope=location_scope,
                        classification_mode="exact_import",
                        evidence_kind="import",
                        evidence_symbol=full_name,
                        guards=guards,
                    )

    def _observe_import_from(
        self,
        node: ast.ImportFrom,
        *,
        qualname: str,
        location_scope: str,
        guards: tuple[str, ...],
    ) -> None:
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
            for module_prefix, category, capability in _IMPORT_RULES:
                if _matches_import_prefix(full_name, module_prefix):
                    self._emit_security(
                        category=category,
                        capability=capability,
                        node=node,
                        qualname=qualname,
                        location_scope=location_scope,
                        classification_mode="exact_import",
                        evidence_kind="import",
                        evidence_symbol=full_name,
                        guards=guards,
                    )

    def _observe_security_call(
        self,
        node: ast.Call,
        *,
        symbol: str,
        qualname: str,
        location_scope: str,
        guards: tuple[str, ...],
    ) -> None:
        if symbol in _BUILTIN_RULES:
            category, capability = _BUILTIN_RULES[symbol]
            self._emit_security(
                category=category,
                capability=capability,
                node=node,
                qualname=qualname,
                location_scope=location_scope,
                classification_mode="exact_builtin",
                evidence_kind="builtin",
                evidence_symbol=symbol,
                guards=guards,
            )
        if symbol in {"open", "pathlib.Path.open"}:
            mode = self._mode_from_open_call(node)
            if mode is not None:
                capability = (
                    "pathlib_open_write"
                    if symbol == "pathlib.Path.open"
                    else "builtin_open_write"
                )
                self._emit_security(
                    category="filesystem_mutation",
                    capability=capability,
                    node=node,
                    qualname=qualname,
                    location_scope=location_scope,
                    classification_mode="exact_call",
                    evidence_kind="call",
                    evidence_symbol=f"{symbol}[mode={mode}]",
                    guards=guards,
                )
        for rule in _CALL_RULES:
            if _matches_call_rule(symbol, rule):
                _expected, category, capability, _prefix_match = rule
                self._emit_security(
                    category=category,
                    capability=capability,
                    node=node,
                    qualname=qualname,
                    location_scope=location_scope,
                    classification_mode="exact_call",
                    evidence_kind="call",
                    evidence_symbol=symbol,
                    guards=guards,
                )

    @staticmethod
    def _semantic_call_kind(symbol: str) -> EventKind | None:
        lowered = symbol.lower()
        if "compatib" in lowered:
            return "compatibility_check"
        if any(token in lowered for token in ("sha256", "digest", "hashlib")):
            return "compute_digest"
        if any(
            token in lowered
            for token in ("module_identity", "resolve_identity", "resolve_module")
        ):
            return "resolve_identity"
        if any(token in lowered for token in ("publish", "emit_event", "record_event")):
            return "publish_event"
        if any(
            token in lowered
            for token in ("write_", ".write", "os.replace", "os.rename")
        ):
            return "artifact_write"
        return None

    def observe(
        self,
        node: ast.AST,
        *,
        scope: tuple[str, ...],
        callable_depth: int,
        class_depth: int,
        guards: tuple[str, ...],
    ) -> None:
        qualname = (
            self._module_name if not scope else f"{self._module_name}:{'.'.join(scope)}"
        )
        location_scope = (
            "callable" if callable_depth else "class" if class_depth else "module"
        )
        if isinstance(node, ast.Import):
            self._observe_import(
                node,
                qualname=qualname,
                location_scope=location_scope,
                guards=guards,
            )
        if isinstance(node, ast.ImportFrom):
            self._observe_import_from(
                node,
                qualname=qualname,
                location_scope=location_scope,
                guards=guards,
            )
        if isinstance(node, ast.Return):
            self._emit(
                kind="return_value",
                subject=qualname,
                inputs=(_input_ref(node.value),),
                node=node,
                qualname=qualname,
                guards=guards,
            )
            return
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.NamedExpr):
            targets: tuple[ast.expr, ...]
            value: ast.AST | None
            if isinstance(node, ast.Assign):
                targets = tuple(node.targets)
                value = node.value
            else:
                targets = (node.target,)
                value = node.value
            for target in targets:
                kind: EventKind = (
                    "field_write"
                    if isinstance(target, ast.Attribute)
                    else "serialize_field"
                    if isinstance(target, ast.Subscript)
                    else "assign"
                )
                self._emit(
                    kind=kind,
                    subject=_target_name(target),
                    inputs=(_input_ref(value),),
                    node=node,
                    qualname=qualname,
                    guards=guards,
                    resolution="unavailable"
                    if _input_ref(value).kind == "unresolved"
                    else "resolved",
                    output=True,
                )
            return
        if not isinstance(node, ast.Call):
            return
        symbol = self._resolve_symbol(node.func)
        if symbol is None:
            return
        self._observe_security_call(
            node,
            symbol=symbol,
            qualname=qualname,
            location_scope=location_scope,
            guards=guards,
        )
        local_class_prefix = f"{self._module_name}:"
        call_kind = (
            "construct"
            if symbol.startswith(local_class_prefix)
            else self._semantic_call_kind(symbol)
        )
        if call_kind is not None:
            self._emit(
                kind=call_kind,
                subject=symbol,
                inputs=tuple(_input_ref(argument) for argument in node.args),
                node=node,
                qualname=qualname,
                guards=guards,
                output=True,
            )


__all__ = ["SemanticEventCollector", "event_counter_key"]

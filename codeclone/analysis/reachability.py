# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import dataclass

from .. import qualnames as _qualnames
from ..models import (
    RuntimeReachabilityConfidence,
    RuntimeReachabilityEdgeKind,
    RuntimeReachabilityFact,
    RuntimeReachabilityFramework,
    RuntimeReachabilityTargetKind,
)
from .ast_helpers import ast_node_end_line, ast_node_start_line

_RuntimeObjectKind = str

_FASTAPI_ROUTE_METHODS = {
    "api_route",
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "route",
    "trace",
    "websocket",
    "websocket_route",
}
_AIOGRAM_OBSERVER_METHODS = {
    "business_connection",
    "business_message",
    "callback_query",
    "channel_post",
    "chat_boost",
    "chat_join_request",
    "chat_member",
    "chosen_inline_result",
    "deleted_business_messages",
    "edited_business_message",
    "edited_channel_post",
    "edited_message",
    "error",
    "inline_query",
    "message",
    "message_reaction",
    "message_reaction_count",
    "my_chat_member",
    "poll",
    "poll_answer",
    "pre_checkout_query",
    "purchased_paid_media",
    "shipping_query",
}
_AIOHTTP_ROUTE_METHODS = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "route",
    "view",
}
_FLASK_ROUTE_METHODS = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "route",
}
_FASTAPI_DEPENDENCY_SYMBOLS = {
    "fastapi.Depends",
    "fastapi.Security",
    "fastapi.params.Depends",
    "fastapi.params.Security",
}
_ANNOTATED_SYMBOLS = {
    "typing.Annotated",
    "typing_extensions.Annotated",
}
_DJANGO_URL_SYMBOLS = {
    "django.urls.path",
    "django.urls.re_path",
}
_DI_PROVIDER_PREFIX = "dependency_injector.providers."
_DI_PROVIDER_NAMES = {
    "Callable",
    "Coroutine",
    "DelegatedCallable",
    "DelegatedCoroutine",
    "DelegatedFactory",
    "DelegatedSingleton",
    "Factory",
    "Resource",
    "Selector",
    "Singleton",
    "ThreadLocalSingleton",
}
_DI_PROVIDER_SYMBOLS = {f"{_DI_PROVIDER_PREFIX}{name}" for name in _DI_PROVIDER_NAMES}
_STARLETTE_BASE_HTTP_MIDDLEWARE = "starlette.middleware.base.BaseHTTPMiddleware"
_SQLALCHEMY_TYPE_DECORATOR_SYMBOLS = {
    "sqlalchemy.TypeDecorator",
    "sqlalchemy.sql.type_api.TypeDecorator",
    "sqlalchemy.types.TypeDecorator",
}
_SQLALCHEMY_TYPE_DECORATOR_HOOKS = {
    "bind_expression",
    "coerce_compared_value",
    "column_expression",
    "compare_values",
    "load_dialect_impl",
    "process_bind_param",
    "process_literal_param",
    "process_result_value",
}
_TYPING_CAST_SYMBOLS = {
    "typing.cast",
    "typing_extensions.cast",
}
_RUNTIME_REGISTRATION_METHODS = {
    "add_routes": ("aiohttp_app", "first_arg"),
    "include_router": ("fastapi_app", "include_router"),
    "register_blueprint": ("flask_app", "first_arg"),
}


@dataclass(frozen=True, slots=True)
class _Target:
    qualname: str
    start_line: int
    end_line: int
    kind: RuntimeReachabilityTargetKind


@dataclass(frozen=True, slots=True)
class _RouteRegistration:
    framework: RuntimeReachabilityFramework
    confidence: RuntimeReachabilityConfidence
    evidence: str
    evidence_symbol: str
    source_qualname: str


@dataclass(frozen=True, slots=True)
class _RouteDecoratorFactory:
    obj_name: str
    obj_kind: _RuntimeObjectKind
    method: str


@dataclass(frozen=True, slots=True)
class _ProviderRegistration:
    target: _Target
    provider_name: str
    evidence_symbol: str


def _registration_confidence(
    obj_name: str,
    *,
    included_routers: set[str],
    high_when: bool = False,
) -> RuntimeReachabilityConfidence:
    if high_when or obj_name in included_routers:
        return "high"
    return "medium"


def _route_registration_for_runtime_object(
    *,
    obj_name: str,
    obj_kind: _RuntimeObjectKind | None,
    method: str,
    included_routers: set[str],
) -> tuple[RuntimeReachabilityFramework, RuntimeReachabilityConfidence] | None:
    match obj_kind:
        case "aiogram_dispatcher":
            framework: RuntimeReachabilityFramework = "aiogram"
            route_methods = _AIOGRAM_OBSERVER_METHODS
            high_when = True
        case "aiogram_router":
            framework = "aiogram"
            route_methods = _AIOGRAM_OBSERVER_METHODS
            high_when = False
        case "aiohttp_routes":
            framework = "aiohttp"
            route_methods = _AIOHTTP_ROUTE_METHODS
            high_when = False
        case "flask_app":
            framework = "flask"
            route_methods = _FLASK_ROUTE_METHODS
            high_when = True
        case "flask_blueprint":
            framework = "flask"
            route_methods = _FLASK_ROUTE_METHODS
            high_when = False
        case "fastapi_app" | "fastapi_router":
            framework = "fastapi"
            route_methods = _FASTAPI_ROUTE_METHODS
            high_when = obj_kind == "fastapi_app"
        case "starlette_app" | "starlette_router":
            framework = "starlette"
            route_methods = _FASTAPI_ROUTE_METHODS
            high_when = obj_kind == "starlette_app"
        case _:
            return None
    if method not in route_methods:
        return None
    return framework, _registration_confidence(
        obj_name,
        included_routers=included_routers,
        high_when=high_when,
    )


def _is_type_checking_guard(test: ast.AST) -> bool:
    match test:
        case ast.Name(id="TYPE_CHECKING"):
            return True
        case ast.Attribute(value=ast.Name(id="typing"), attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _dotted_name(node: ast.AST) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            prefix = _dotted_name(value)
            return f"{prefix}.{attr}" if prefix else None
        case ast.Call(func=func):
            return _dotted_name(func)
        case ast.Subscript(value=value):
            return _dotted_name(value)
        case _:
            return None


def _resolve_symbol(node: ast.AST, aliases: dict[str, str]) -> str | None:
    dotted = _dotted_name(node)
    if dotted is None:
        return None
    head, separator, tail = dotted.partition(".")
    resolved_head = aliases.get(head)
    if resolved_head is None:
        return dotted
    return f"{resolved_head}.{tail}" if separator else resolved_head


def _is_call_to_symbol(
    call: ast.Call, symbols: set[str], aliases: dict[str, str]
) -> bool:
    symbol = _resolve_symbol(call.func, aliases)
    return symbol in symbols


def _call_symbol_name(call: ast.Call, aliases: dict[str, str]) -> str:
    return _resolve_symbol(call.func, aliases) or _dotted_name(call.func) or "<call>"


def _provider_symbol_name(symbol: str) -> str:
    return symbol.rsplit(".", 1)[-1]


class _ImportAliasVisitor(ast.NodeVisitor):
    __slots__ = ("aliases",)

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node.test):
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self.aliases[local_name] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            self.aliases[local_name] = f"{node.module}.{alias.name}"


class _RuntimeBindingVisitor(ast.NodeVisitor):
    __slots__ = (
        "_aliases",
        "_scope_depth",
        "included_routers",
        "objects",
        "route_decorator_factories",
    )

    def __init__(self, aliases: dict[str, str]) -> None:
        self._aliases = aliases
        self._scope_depth = 0
        self.objects: dict[str, _RuntimeObjectKind] = {}
        self.included_routers: set[str] = set()
        self.route_decorator_factories: dict[str, _RouteDecoratorFactory] = {}

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node.test):
            return
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        kind = self._runtime_object_kind(node.value)
        if kind is None:
            self.generic_visit(node)
            return
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.objects[target.id] = kind
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            self.generic_visit(node)
            return
        kind = self._runtime_object_kind(node.value)
        if kind is not None and isinstance(node.target, ast.Name):
            self.objects[node.target.id] = kind
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        symbol = _resolve_symbol(node.func, self._aliases)
        self._collect_runtime_registration(node)
        if symbol == "fastapi.FastAPI.include_router":
            self._collect_include_router_arg(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._scope_depth == 0:
            self._collect_click_group_binding(node)
            self._collect_route_decorator_factory(node)
        self._visit_nested_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._scope_depth == 0:
            self._collect_click_group_binding(node)
            self._collect_route_decorator_factory(node)
        self._visit_nested_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_nested_scope(node)

    def _visit_nested_scope(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._scope_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._scope_depth -= 1

    def _collect_click_group_binding(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            func = call.func if call is not None else decorator
            symbol = _resolve_symbol(func, self._aliases)
            if symbol in {"click.group", "click.Group"}:
                self.objects[node.name] = "click_group"

    def _collect_route_decorator_factory(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        local_route_aliases: dict[str, _RouteDecoratorFactory] = {}
        for statement in node.body:
            alias = self._route_method_assignment(statement)
            if alias is not None:
                name, factory = alias
                local_route_aliases[name] = factory
                continue
            returned_factory = self._returned_route_factory(
                statement, local_route_aliases
            )
            if returned_factory is not None:
                self.route_decorator_factories[node.name] = returned_factory
                return

    def _route_method_assignment(
        self,
        statement: ast.stmt,
    ) -> tuple[str, _RouteDecoratorFactory] | None:
        match statement:
            case ast.Assign(targets=[ast.Name(id=name), *_], value=value):
                factory = self._route_method_reference(value)
            case ast.AnnAssign(target=ast.Name(id=name), value=value):
                factory = (
                    self._route_method_reference(value) if value is not None else None
                )
            case _:
                return None
        if factory is None:
            return None
        return name, factory

    def _returned_route_factory(
        self,
        statement: ast.stmt,
        local_route_aliases: dict[str, _RouteDecoratorFactory],
    ) -> _RouteDecoratorFactory | None:
        match statement:
            case ast.Return(value=ast.Call(func=ast.Name(id=name))):
                return local_route_aliases.get(name)
            case ast.Return(value=ast.Call(func=func)):
                return self._route_method_reference(func)
            case _:
                return None

    def _route_method_reference(self, value: ast.AST) -> _RouteDecoratorFactory | None:
        if (
            isinstance(value, ast.Call)
            and _resolve_symbol(value.func, self._aliases) in _TYPING_CAST_SYMBOLS
        ):
            if len(value.args) < 2:
                return None
            return self._route_method_reference(value.args[1])
        match value:
            case ast.Attribute(value=ast.Name(id=obj_name), attr=method):
                obj_kind = self.objects.get(obj_name)
                if obj_kind is None:
                    return None
                if (
                    _route_registration_for_runtime_object(
                        obj_name=obj_name,
                        obj_kind=obj_kind,
                        method=method,
                        included_routers=self.included_routers,
                    )
                    is None
                ):
                    return None
                return _RouteDecoratorFactory(
                    obj_name=obj_name,
                    obj_kind=obj_kind,
                    method=method,
                )
            case _:
                return None

    def _collect_include_router_arg(self, node: ast.Call) -> None:
        if node.args:
            router = _dotted_name(node.args[0])
            if router is not None:
                self.included_routers.add(router)
        for keyword in node.keywords:
            if keyword.arg == "router":
                router = _dotted_name(keyword.value)
                if router is not None:
                    self.included_routers.add(router)

    def _collect_runtime_registration(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(value=ast.Name(id=owner), attr=method):
                expected = _RUNTIME_REGISTRATION_METHODS.get(method)
            case _:
                return
        if expected is None:
            return
        expected_kind, collector = expected
        if self.objects.get(owner) != expected_kind:
            return
        if collector == "include_router":
            self._collect_include_router_arg(node)
        else:
            self._collect_first_arg_object(node)

    def _collect_first_arg_object(self, node: ast.Call) -> None:
        if not node.args:
            return
        target = _dotted_name(node.args[0])
        if target is not None:
            self.included_routers.add(target)

    def _runtime_object_kind(self, value: ast.AST) -> _RuntimeObjectKind | None:
        if not isinstance(value, ast.Call):
            return None
        symbol = _resolve_symbol(value.func, self._aliases)
        match symbol:
            case "aiogram.Dispatcher":
                return "aiogram_dispatcher"
            case "aiogram.Router":
                return "aiogram_router"
            case "aiohttp.web.Application":
                return "aiohttp_app"
            case "aiohttp.web.RouteTableDef":
                return "aiohttp_routes"
            case "fastapi.FastAPI":
                return "fastapi_app"
            case "fastapi.APIRouter":
                return "fastapi_router"
            case "flask.Blueprint":
                return "flask_blueprint"
            case "flask.Flask":
                return "flask_app"
            case "starlette.applications.Starlette":
                return "starlette_app"
            case "starlette.routing.Router":
                return "starlette_router"
            case "typer.Typer":
                return "typer_app"
            case "click.Group":
                return "click_group"
            case "celery.Celery":
                return "celery_app"
            case _:
                return None


class _RuntimeReachabilityVisitor(ast.NodeVisitor):
    __slots__ = (
        "_aliases",
        "_class_targets",
        "_filepath",
        "_function_targets",
        "_included_routers",
        "_methods_by_class",
        "_module_name",
        "_route_decorator_factories",
        "_runtime_objects",
        "_seen",
        "_targets_by_name",
        "facts",
    )

    def __init__(
        self,
        *,
        module_name: str,
        filepath: str,
        collector: _qualnames.QualnameCollector,
        aliases: dict[str, str],
        runtime_objects: dict[str, _RuntimeObjectKind],
        included_routers: set[str],
        route_decorator_factories: dict[str, _RouteDecoratorFactory],
    ) -> None:
        self._module_name = module_name
        self._filepath = filepath
        self._aliases = aliases
        self._runtime_objects = runtime_objects
        self._included_routers = included_routers
        self._route_decorator_factories = route_decorator_factories
        self._function_targets: dict[int, _Target] = {}
        self._class_targets: dict[int, _Target] = {}
        self._methods_by_class: dict[str, list[_Target]] = {}
        self._targets_by_name: dict[str, _Target] = {}
        self._seen: set[
            tuple[
                str,
                str,
                str,
                str,
                str,
                int,
                int,
            ]
        ] = set()
        self.facts: list[RuntimeReachabilityFact] = []
        self._index_targets(collector)

    def _index_targets(self, collector: _qualnames.QualnameCollector) -> None:
        for local_name, function_node in collector.units:
            target = _Target(
                qualname=f"{self._module_name}:{local_name}",
                start_line=ast_node_start_line(function_node) or 0,
                end_line=ast_node_end_line(function_node),
                kind="method" if "." in local_name else "function",
            )
            self._function_targets[id(function_node)] = target
            self._targets_by_name.setdefault(function_node.name, target)
            self._targets_by_name.setdefault(local_name, target)
            if "." in local_name:
                class_name = local_name.rsplit(".", 1)[0]
                self._methods_by_class.setdefault(class_name, []).append(target)
        for local_name, class_node in collector.class_nodes:
            target = _Target(
                qualname=f"{self._module_name}:{local_name}",
                start_line=ast_node_start_line(class_node) or 0,
                end_line=ast_node_end_line(class_node),
                kind="class",
            )
            self._class_targets[id(class_node)] = target
            self._targets_by_name.setdefault(class_node.name, target)
            self._targets_by_name.setdefault(local_name, target)

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node.test):
            return
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_callable(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_callable(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._handle_dependency_injector_container(node)
        self._handle_starlette_base_http_middleware(node)
        self._handle_sqlalchemy_type_decorator(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(
            isinstance(target, ast.Name) and target.id == "urlpatterns"
            for target in node.targets
        ):
            self._handle_django_urlpatterns(node.value)
        self.generic_visit(node)

    def _handle_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        target = self._function_targets.get(id(node))
        if target is None:
            return
        for decorator in node.decorator_list:
            route = self._route_registration(decorator)
            if route is not None:
                self._emit(
                    target=target,
                    framework=route.framework,
                    edge_kind="registers_handler",
                    confidence=route.confidence,
                    evidence=route.evidence,
                    evidence_symbol=route.evidence_symbol,
                    source_qualname=route.source_qualname,
                )
                self._collect_fastapi_dependencies(
                    node,
                    route=route,
                    decorator=decorator,
                )
                continue
            self._handle_cli_or_task_decorator(target, decorator)

    def _route_registration(self, decorator: ast.AST) -> _RouteRegistration | None:
        call = decorator if isinstance(decorator, ast.Call) else None
        func = call.func if call is not None else decorator
        match func:
            case ast.Attribute(value=ast.Name(id=obj_name), attr=method):
                obj_kind = self._runtime_objects.get(obj_name)
                route = _route_registration_for_runtime_object(
                    obj_name=obj_name,
                    obj_kind=obj_kind,
                    method=method,
                    included_routers=self._included_routers,
                )
                if route is None:
                    return None
                framework, confidence = route
                return _RouteRegistration(
                    framework=framework,
                    confidence=confidence,
                    evidence="route decorator",
                    evidence_symbol=f"{obj_name}.{method}",
                    source_qualname=f"{self._module_name}:{obj_name}",
                )
            case ast.Name(id=factory_name):
                factory = self._route_decorator_factories.get(factory_name)
                if factory is None:
                    return None
                route = _route_registration_for_runtime_object(
                    obj_name=factory.obj_name,
                    obj_kind=factory.obj_kind,
                    method=factory.method,
                    included_routers=self._included_routers,
                )
                if route is None:
                    return None
                framework, confidence = route
                return _RouteRegistration(
                    framework=framework,
                    confidence=confidence,
                    evidence="route decorator factory",
                    evidence_symbol=factory_name,
                    source_qualname=f"{self._module_name}:{factory_name}",
                )
            case _:
                return None

    def _handle_cli_or_task_decorator(
        self,
        target: _Target,
        decorator: ast.AST,
    ) -> None:
        call = decorator if isinstance(decorator, ast.Call) else None
        func = call.func if call is not None else decorator
        symbol = _resolve_symbol(func, self._aliases)
        match func:
            case ast.Attribute(
                value=ast.Name(id=obj_name), attr=("command" | "callback")
            ):
                if self._runtime_objects.get(obj_name) == "typer_app":
                    self._emit(
                        target=target,
                        framework="typer",
                        edge_kind="registers_command",
                        confidence="high",
                        evidence="Typer command decorator",
                        evidence_symbol=f"{obj_name}.{func.attr}",
                        source_qualname=f"{self._module_name}:{obj_name}",
                    )
                if self._runtime_objects.get(obj_name) == "click_group":
                    self._emit(
                        target=target,
                        framework="click",
                        edge_kind="registers_command",
                        confidence="high",
                        evidence="Click group command decorator",
                        evidence_symbol=f"{obj_name}.{func.attr}",
                        source_qualname=f"{self._module_name}:{obj_name}",
                    )
            case ast.Attribute(value=ast.Name(id=obj_name), attr="task"):
                if self._runtime_objects.get(obj_name) == "celery_app":
                    self._emit(
                        target=target,
                        framework="celery",
                        edge_kind="registers_task",
                        confidence="high",
                        evidence="Celery task decorator",
                        evidence_symbol=f"{obj_name}.task",
                        source_qualname=f"{self._module_name}:{obj_name}",
                    )
            case _:
                pass
        if symbol in {"click.command", "click.group"}:
            self._emit(
                target=target,
                framework="click",
                edge_kind="registers_command",
                confidence="high",
                evidence="Click decorator",
                evidence_symbol=symbol,
                source_qualname=self._module_name,
            )
        elif symbol == "celery.shared_task":
            self._emit(
                target=target,
                framework="celery",
                edge_kind="registers_task",
                confidence="high",
                evidence="Celery shared task decorator",
                evidence_symbol=symbol,
                source_qualname=self._module_name,
            )

    def _collect_fastapi_dependencies(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        route: _RouteRegistration,
        decorator: ast.AST,
    ) -> None:
        dependency_nodes: list[ast.Call] = []
        if isinstance(decorator, ast.Call):
            dependency_nodes.extend(
                self._dependency_calls_from_route_decorator(decorator)
            )
        dependency_nodes.extend(
            self._dependency_calls_from_defaults(node.args.defaults)
        )
        dependency_nodes.extend(
            self._dependency_calls_from_defaults(
                [default for default in node.args.kw_defaults if default is not None]
            )
        )
        dependency_nodes.extend(self._dependency_calls_from_annotations(node.args))
        for call in dependency_nodes:
            target = self._target_from_dependency_call(call)
            if target is None:
                continue
            self._emit(
                target=target,
                framework=route.framework,
                edge_kind="declares_dependency",
                confidence=route.confidence,
                evidence="dependency registration",
                evidence_symbol=_call_symbol_name(call, self._aliases),
                source_qualname=route.source_qualname,
            )

    def _dependency_calls_from_route_decorator(self, call: ast.Call) -> list[ast.Call]:
        calls: list[ast.Call] = []
        for keyword in call.keywords:
            if keyword.arg != "dependencies":
                continue
            match keyword.value:
                case ast.List(elts=elts) | ast.Tuple(elts=elts):
                    calls.extend(item for item in elts if isinstance(item, ast.Call))
                case ast.Call() as dep_call:
                    calls.append(dep_call)
                case _:
                    pass
        return calls

    def _dependency_calls_from_defaults(
        self, defaults: list[ast.expr]
    ) -> list[ast.Call]:
        return [item for item in defaults if isinstance(item, ast.Call)]

    def _dependency_calls_from_annotations(
        self, arguments: ast.arguments
    ) -> list[ast.Call]:
        calls: list[ast.Call] = []
        args: list[ast.arg] = [*arguments.posonlyargs, *arguments.args]
        if arguments.vararg is not None:
            args.append(arguments.vararg)
        args.extend(arguments.kwonlyargs)
        if arguments.kwarg is not None:
            args.append(arguments.kwarg)
        for arg in args:
            if arg.annotation is not None:
                calls.extend(self._dependency_calls_from_annotation(arg.annotation))
        return calls

    def _dependency_calls_from_annotation(self, annotation: ast.expr) -> list[ast.Call]:
        calls: list[ast.Call] = []
        for node in ast.walk(annotation):
            if not isinstance(node, ast.Subscript):
                continue
            if _resolve_symbol(node.value, self._aliases) not in _ANNOTATED_SYMBOLS:
                continue
            calls.extend(
                item
                for item in self._annotated_metadata_elements(node.slice)
                if isinstance(item, ast.Call)
            )
        return calls

    def _annotated_metadata_elements(self, node: ast.AST) -> tuple[ast.AST, ...]:
        if not isinstance(node, ast.Tuple) or len(node.elts) < 2:
            return ()
        return tuple(node.elts[1:])

    def _target_from_dependency_call(self, call: ast.Call) -> _Target | None:
        if not _is_call_to_symbol(call, _FASTAPI_DEPENDENCY_SYMBOLS, self._aliases):
            return None
        dependency_expr = call.args[0] if call.args else None
        for keyword in call.keywords:
            if keyword.arg == "dependency":
                dependency_expr = keyword.value
                break
        if dependency_expr is None:
            return None
        return self._target_from_expr(dependency_expr)

    def _handle_django_urlpatterns(self, value: ast.AST) -> None:
        match value:
            case ast.List(elts=elts) | ast.Tuple(elts=elts):
                for item in elts:
                    self._handle_django_url_entry(item)
            case ast.BinOp(left=left, op=ast.Add(), right=right):
                self._handle_django_urlpatterns(left)
                self._handle_django_urlpatterns(right)
            case _:
                pass

    def _handle_django_url_entry(self, node: ast.AST) -> None:
        if not isinstance(node, ast.Call):
            return
        if not _is_call_to_symbol(node, _DJANGO_URL_SYMBOLS, self._aliases):
            return
        if len(node.args) < 2:
            return
        view_expr = node.args[1]
        target = self._django_view_target(view_expr)
        if target is None:
            return
        self._emit(
            target=target,
            framework="django",
            edge_kind="registers_handler",
            confidence="medium" if target.kind == "class" else "high",
            evidence="Django URL pattern",
            evidence_symbol=_call_symbol_name(node, self._aliases),
            source_qualname=f"{self._module_name}:urlpatterns",
        )
        if target.kind == "class":
            self._emit_django_class_view_methods(target)

    def _emit_django_class_view_methods(self, target: _Target) -> None:
        local_class = target.qualname.split(":", 1)[-1]
        for method in self._methods_by_class.get(local_class, []):
            if method.qualname.rsplit(".", 1)[-1] not in {
                "delete",
                "dispatch",
                "get",
                "head",
                "options",
                "patch",
                "post",
                "put",
            }:
                continue
            self._emit(
                target=method,
                framework="django",
                edge_kind="registers_handler",
                confidence="medium",
                evidence="Django class-based view dispatch",
                evidence_symbol="as_view",
                source_qualname=target.qualname,
            )

    def _django_view_target(self, node: ast.AST) -> _Target | None:
        match node:
            case ast.Call(func=ast.Attribute(value=value, attr="as_view")):
                return self._target_from_expr(value)
            case _:
                return self._target_from_expr(node)

    def _handle_starlette_base_http_middleware(self, node: ast.ClassDef) -> None:
        if not any(
            _resolve_symbol(base, self._aliases) == _STARLETTE_BASE_HTTP_MIDDLEWARE
            for base in node.bases
        ):
            return
        class_target = self._class_targets.get(id(node))
        class_qualname = (
            class_target.qualname.split(":", 1)[-1]
            if class_target is not None
            else node.name
        )
        for method in self._methods_by_class.get(class_qualname, []):
            if method.qualname.rsplit(".", 1)[-1] != "dispatch":
                continue
            self._emit(
                target=method,
                framework="starlette",
                edge_kind="registers_handler",
                confidence="medium",
                evidence="Starlette BaseHTTPMiddleware dispatch hook",
                evidence_symbol="BaseHTTPMiddleware.dispatch",
                source_qualname=class_target.qualname
                if class_target is not None
                else f"{self._module_name}:{node.name}",
            )

    def _handle_sqlalchemy_type_decorator(self, node: ast.ClassDef) -> None:
        if not any(
            _resolve_symbol(base, self._aliases) in _SQLALCHEMY_TYPE_DECORATOR_SYMBOLS
            for base in node.bases
        ):
            return
        class_target = self._class_targets.get(id(node))
        class_qualname = (
            class_target.qualname.split(":", 1)[-1]
            if class_target is not None
            else node.name
        )
        source_qualname = (
            class_target.qualname
            if class_target is not None
            else f"{self._module_name}:{node.name}"
        )
        for method in self._methods_by_class.get(class_qualname, []):
            method_name = method.qualname.rsplit(".", 1)[-1]
            if method_name not in _SQLALCHEMY_TYPE_DECORATOR_HOOKS:
                continue
            self._emit(
                target=method,
                framework="sqlalchemy",
                edge_kind="runtime_hook",
                confidence="medium",
                evidence="SQLAlchemy TypeDecorator hook",
                evidence_symbol=f"TypeDecorator.{method_name}",
                source_qualname=source_qualname,
            )

    def _handle_dependency_injector_container(self, node: ast.ClassDef) -> None:
        if not any(
            self._is_dependency_injector_container_base(base) for base in node.bases
        ):
            return
        container_name = self._class_targets.get(id(node))
        source_prefix = container_name.qualname if container_name else self._module_name
        if container_name is not None:
            self._emit(
                target=container_name,
                framework="dependency_injector",
                edge_kind="provides",
                confidence="medium",
                evidence="Dependency Injector declarative container",
                evidence_symbol="DeclarativeContainer",
                source_qualname=self._module_name,
            )
        for statement in node.body:
            registration = self._dependency_injector_provider(statement)
            if registration is None:
                continue
            source_qualname = (
                f"{source_prefix}.{registration.provider_name}"
                if registration.provider_name
                else source_prefix
            )
            self._emit(
                target=registration.target,
                framework="dependency_injector",
                edge_kind="provides",
                confidence="medium",
                evidence="Dependency Injector provider",
                evidence_symbol=registration.evidence_symbol,
                source_qualname=source_qualname,
            )

    def _is_dependency_injector_container_base(self, node: ast.AST) -> bool:
        return (
            _resolve_symbol(node, self._aliases)
            == "dependency_injector.containers.DeclarativeContainer"
        )

    def _provider_target(self, call: ast.Call) -> _Target | None:
        if not call.args:
            return None
        return self._target_from_expr(call.args[0])

    def _dependency_injector_provider(
        self,
        statement: ast.stmt,
    ) -> _ProviderRegistration | None:
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            return None
        value = statement.value
        if value is None or not isinstance(value, ast.Call):
            return None
        symbol = _resolve_symbol(value.func, self._aliases)
        if symbol not in _DI_PROVIDER_SYMBOLS:
            return None
        target = self._provider_target(value)
        if target is None:
            return None
        return _ProviderRegistration(
            target=target,
            provider_name=self._provider_assignment_name(statement),
            evidence_symbol=_provider_symbol_name(symbol),
        )

    def _provider_assignment_name(self, node: ast.Assign | ast.AnnAssign) -> str:
        match node:
            case ast.Assign(targets=[ast.Name(id=name), *_]):
                return name
            case ast.AnnAssign(target=ast.Name(id=name)):
                return name
            case _:
                return ""

    def _target_from_expr(self, node: ast.AST) -> _Target | None:
        name = _dotted_name(node)
        if name is None:
            return None
        return self._targets_by_name.get(name)

    def _emit(
        self,
        *,
        target: _Target,
        framework: RuntimeReachabilityFramework,
        edge_kind: RuntimeReachabilityEdgeKind,
        confidence: RuntimeReachabilityConfidence,
        evidence: str,
        evidence_symbol: str,
        source_qualname: str,
    ) -> None:
        if target.start_line <= 0:
            return
        key = (
            target.qualname,
            framework,
            edge_kind,
            confidence,
            evidence_symbol,
            target.start_line,
            target.end_line,
        )
        if key in self._seen:
            return
        self._seen.add(key)
        self.facts.append(
            RuntimeReachabilityFact(
                target_qualname=target.qualname,
                filepath=self._filepath,
                start_line=target.start_line,
                end_line=target.end_line,
                target_kind=target.kind,
                framework=framework,
                edge_kind=edge_kind,
                confidence=confidence,
                evidence=evidence,
                evidence_symbol=evidence_symbol,
                source_qualname=source_qualname,
            )
        )


def collect_runtime_reachability(
    *,
    tree: ast.Module,
    module_name: str,
    filepath: str,
    collector: _qualnames.QualnameCollector,
) -> tuple[RuntimeReachabilityFact, ...]:
    alias_visitor = _ImportAliasVisitor()
    alias_visitor.visit(tree)
    binding_visitor = _RuntimeBindingVisitor(alias_visitor.aliases)
    binding_visitor.visit(tree)
    visitor = _RuntimeReachabilityVisitor(
        module_name=module_name,
        filepath=filepath,
        collector=collector,
        aliases=alias_visitor.aliases,
        runtime_objects=binding_visitor.objects,
        included_routers=binding_visitor.included_routers,
        route_decorator_factories=binding_visitor.route_decorator_factories,
    )
    visitor.visit(tree)
    return tuple(
        sorted(
            visitor.facts,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.target_qualname,
                item.framework,
                item.edge_kind,
                item.evidence_symbol,
            ),
        )
    )


__all__ = ["collect_runtime_reachability"]

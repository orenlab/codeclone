# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from json import JSONDecodeError
from pathlib import Path
from typing import Any, Literal, cast

from ..cache.projection import runtime_filepath_from_wire
from ..contracts import BASELINE_SCHEMA_VERSION
from ..contracts.errors import BaselineValidationError
from ..models import (
    ApiParamSpec,
    ApiSurfaceSnapshot,
    MetricsSnapshot,
    ModuleApiSurface,
    PublicSymbol,
)
from ..utils.json_io import read_json_object as _read_json_object
from ..utils.json_io import (
    write_json_document_atomically as _write_json_document_atomically,
)
from ..utils.schema_validation import validate_top_level_structure
from ._metrics_baseline_contract import (
    _METRICS_PAYLOAD_SHA256_KEY,
    _TOP_LEVEL_ALLOWED_KEYS,
    _TOP_LEVEL_REQUIRED_KEYS,
    MetricsBaselineStatus,
)
from ._metrics_baseline_payload import _compose_api_surface_qualname


def _is_compatible_metrics_schema(
    *,
    baseline_version: str | None,
    expected_version: str,
) -> bool:
    if baseline_version is None:
        return False
    baseline_major_minor = _parse_major_minor(baseline_version)
    expected_major_minor = _parse_major_minor(expected_version)
    if baseline_major_minor is None or expected_major_minor is None:
        return baseline_version == expected_version
    baseline_major, baseline_minor = baseline_major_minor
    expected_major, expected_minor = expected_major_minor
    return baseline_major == expected_major and baseline_minor <= expected_minor


def _parse_major_minor(version: str) -> tuple[int, int] | None:
    parts = version.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    _write_json_document_atomically(
        path,
        payload,
        indent=True,
        trailing_newline=True,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        return _read_json_object(path)
    except OSError as e:
        raise BaselineValidationError(
            f"Cannot read metrics baseline file at {path}: {e}",
            status=MetricsBaselineStatus.INVALID_JSON,
        ) from e
    except JSONDecodeError as e:
        raise BaselineValidationError(
            f"Corrupted metrics baseline file at {path}: {e}",
            status=MetricsBaselineStatus.INVALID_JSON,
        ) from e
    except TypeError:
        raise BaselineValidationError(
            f"Metrics baseline payload must be an object at {path}",
            status=MetricsBaselineStatus.INVALID_TYPE,
        ) from None


def _validate_top_level_structure(payload: dict[str, Any], *, path: Path) -> None:
    validate_top_level_structure(
        payload,
        path=path,
        required_keys=_TOP_LEVEL_REQUIRED_KEYS,
        allowed_keys=_TOP_LEVEL_ALLOWED_KEYS,
        schema_label="metrics baseline",
        missing_status=MetricsBaselineStatus.MISSING_FIELDS,
        extra_status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _validate_required_keys(
    payload: dict[str, Any],
    required: frozenset[str],
    *,
    path: Path,
) -> None:
    missing = required - set(payload.keys())
    if missing:
        raise BaselineValidationError(
            "Invalid metrics baseline schema at "
            f"{path}: missing required fields: {', '.join(sorted(missing))}",
            status=MetricsBaselineStatus.MISSING_FIELDS,
        )


def _validate_exact_keys(
    payload: dict[str, Any],
    required: frozenset[str],
    *,
    path: Path,
) -> None:
    extra = set(payload.keys()) - set(required)
    if extra:
        raise BaselineValidationError(
            "Invalid metrics baseline schema at "
            f"{path}: unexpected fields: {', '.join(sorted(extra))}",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )


def _require_str(payload: dict[str, Any], key: str, *, path: Path) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: {key!r} must be str",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _extract_metrics_payload_sha256(
    payload: dict[str, Any],
    *,
    path: Path,
) -> str:
    direct = payload.get(_METRICS_PAYLOAD_SHA256_KEY)
    if isinstance(direct, str):
        return direct
    return _require_str(payload, "payload_sha256", path=path)


def _extract_optional_payload_sha256(
    payload: dict[str, Any],
    *,
    key: str,
) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _require_int(payload: dict[str, Any], key: str, *, path: Path) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be int",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if isinstance(value, int):
        return value
    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: {key!r} must be int",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _optional_require_str(
    payload: dict[str, Any],
    key: str,
    *,
    path: Path,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: {key!r} must be str",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _require_str_list(payload: dict[str, Any], key: str, *, path: Path) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if not all(isinstance(item, str) for item in value):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    return value


def _parse_cycles(
    payload: dict[str, Any],
    *,
    key: str,
    path: Path,
) -> tuple[tuple[str, ...], ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: {key!r} must be list",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )

    cycles: list[tuple[str, ...]] = []
    for cycle in value:
        if not isinstance(cycle, list):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: {key!r} cycle item must be list[str]",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        if not all(isinstance(item, str) for item in cycle):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: {key!r} cycle item must be list[str]",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        cycles.append(tuple(cycle))
    return tuple(sorted(set(cycles)))


def _parse_generator(
    meta: dict[str, Any],
    *,
    path: Path,
) -> tuple[str, str | None]:
    generator = meta.get("generator")
    if isinstance(generator, str):
        version_value = meta.get("generator_version")
        if version_value is None:
            version_value = meta.get("codeclone_version")
        if version_value is None:
            return generator, None
        if not isinstance(version_value, str):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: generator_version must be str",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        return generator, version_value

    if isinstance(generator, dict):
        allowed_keys = {"name", "version"}
        extra = set(generator.keys()) - allowed_keys
        if extra:
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {path}: "
                f"unexpected generator keys: {', '.join(sorted(extra))}",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        name = generator.get("name")
        version = generator.get("version")
        if not isinstance(name, str):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: generator.name must be str",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        if version is not None and not isinstance(version, str):
            raise BaselineValidationError(
                "Invalid metrics baseline schema at "
                f"{path}: generator.version must be str",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        return name, version if isinstance(version, str) else None

    raise BaselineValidationError(
        f"Invalid metrics baseline schema at {path}: generator must be object or str",
        status=MetricsBaselineStatus.INVALID_TYPE,
    )


def _require_embedded_clone_baseline_payload(
    payload: dict[str, Any],
    *,
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_obj = payload.get("meta")
    clones_obj = payload.get("clones")
    if not isinstance(meta_obj, dict):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'meta' must be object",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if not isinstance(clones_obj, dict):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'clones' must be object",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    _require_str(meta_obj, "payload_sha256", path=path)
    _require_str(meta_obj, "python_tag", path=path)
    _require_str(meta_obj, "created_at", path=path)
    functions = clones_obj.get("functions")
    blocks = clones_obj.get("blocks")
    if not isinstance(functions, list) or not all(
        isinstance(item, str) for item in functions
    ):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'clones.functions' must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    if not isinstance(blocks, list) or not all(
        isinstance(item, str) for item in blocks
    ):
        raise BaselineValidationError(
            f"Invalid baseline schema at {path}: 'clones.blocks' must be list[str]",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    return meta_obj, clones_obj


def _resolve_embedded_schema_version(meta: dict[str, Any], *, path: Path) -> str:
    raw_version = _require_str(meta, "schema_version", path=path)
    parts = raw_version.split(".")
    if len(parts) not in {2, 3} or not all(part.isdigit() for part in parts):
        raise BaselineValidationError(
            "Invalid baseline schema at "
            f"{path}: 'schema_version' must be semver string",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    major = int(parts[0])
    if major >= 2:
        return raw_version
    return BASELINE_SCHEMA_VERSION


def _parse_snapshot(
    payload: dict[str, Any],
    *,
    path: Path,
) -> MetricsSnapshot:
    grade = _require_str(payload, "health_grade", path=path)
    if grade not in {"A", "B", "C", "D", "F"}:
        raise BaselineValidationError(
            "Invalid metrics baseline schema at "
            f"{path}: 'health_grade' must be one of A/B/C/D/F",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )

    return MetricsSnapshot(
        max_complexity=_require_int(payload, "max_complexity", path=path),
        high_risk_functions=tuple(
            sorted(set(_require_str_list(payload, "high_risk_functions", path=path)))
        ),
        max_coupling=_require_int(payload, "max_coupling", path=path),
        high_coupling_classes=tuple(
            sorted(set(_require_str_list(payload, "high_coupling_classes", path=path)))
        ),
        max_cohesion=_require_int(payload, "max_cohesion", path=path),
        low_cohesion_classes=tuple(
            sorted(set(_require_str_list(payload, "low_cohesion_classes", path=path)))
        ),
        dependency_cycles=_parse_cycles(payload, key="dependency_cycles", path=path),
        dependency_max_depth=_require_int(payload, "dependency_max_depth", path=path),
        dead_code_items=tuple(
            sorted(set(_require_str_list(payload, "dead_code_items", path=path)))
        ),
        health_score=_require_int(payload, "health_score", path=path),
        health_grade=cast("Literal['A', 'B', 'C', 'D', 'F']", grade),
        typing_param_permille=_optional_int(
            payload,
            "typing_param_permille",
            path=path,
        ),
        typing_return_permille=_optional_int(
            payload,
            "typing_return_permille",
            path=path,
        ),
        docstring_permille=_optional_int(payload, "docstring_permille", path=path),
        typing_any_count=_optional_int(payload, "typing_any_count", path=path),
    )


def _optional_int(payload: dict[str, Any], key: str, *, path: Path) -> int:
    value = payload.get(key)
    if value is None:
        return 0
    return _require_int(payload, key, path=path)


def _parse_api_surface_snapshot(
    payload: object,
    *,
    path: Path,
    root: Path | None = None,
) -> ApiSurfaceSnapshot | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: 'api_surface' must be object",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    raw_modules = payload.get("modules", [])
    if not isinstance(raw_modules, list):
        raise BaselineValidationError(
            f"Invalid metrics baseline schema at {path}: "
            "'api_surface.modules' must be list",
            status=MetricsBaselineStatus.INVALID_TYPE,
        )
    modules: list[ModuleApiSurface] = []
    for raw_module in raw_modules:
        if not isinstance(raw_module, dict):
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {path}: "
                "api surface module must be object",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        module = _require_str(raw_module, "module", path=path)
        wire_filepath = _require_str(raw_module, "filepath", path=path)
        filepath = runtime_filepath_from_wire(wire_filepath, root=root)
        all_declared = _require_str_list_or_none(raw_module, "all_declared", path=path)
        raw_symbols = raw_module.get("symbols", [])
        if not isinstance(raw_symbols, list):
            raise BaselineValidationError(
                f"Invalid metrics baseline schema at {path}: "
                "api surface symbols must be list",
                status=MetricsBaselineStatus.INVALID_TYPE,
            )
        symbols: list[PublicSymbol] = []
        for raw_symbol in raw_symbols:
            if not isinstance(raw_symbol, dict):
                raise BaselineValidationError(
                    f"Invalid metrics baseline schema at {path}: "
                    "api surface symbol must be object",
                    status=MetricsBaselineStatus.INVALID_TYPE,
                )
            local_name = _optional_require_str(raw_symbol, "local_name", path=path)
            legacy_qualname = _optional_require_str(raw_symbol, "qualname", path=path)
            if local_name is None and legacy_qualname is None:
                raise BaselineValidationError(
                    f"Invalid metrics baseline schema at {path}: "
                    "api surface symbol requires 'local_name' or 'qualname'",
                    status=MetricsBaselineStatus.MISSING_FIELDS,
                )
            qualname = (
                legacy_qualname
                if local_name is None
                else _compose_api_surface_qualname(
                    module=module,
                    local_name=local_name,
                )
            )
            kind = _require_str(raw_symbol, "kind", path=path)
            exported_via = _require_str(raw_symbol, "exported_via", path=path)
            params_raw = raw_symbol.get("params", [])
            if not isinstance(params_raw, list):
                raise BaselineValidationError(
                    f"Invalid metrics baseline schema at {path}: "
                    "api surface params must be list",
                    status=MetricsBaselineStatus.INVALID_TYPE,
                )
            params: list[ApiParamSpec] = []
            for raw_param in params_raw:
                if not isinstance(raw_param, dict):
                    raise BaselineValidationError(
                        f"Invalid metrics baseline schema at {path}: "
                        "api param must be object",
                        status=MetricsBaselineStatus.INVALID_TYPE,
                    )
                name = _require_str(raw_param, "name", path=path)
                param_kind = _require_str(raw_param, "kind", path=path)
                has_default = raw_param.get("has_default")
                annotation_hash = _optional_require_str(
                    raw_param,
                    "annotation_hash",
                    path=path,
                )
                if not isinstance(has_default, bool):
                    raise BaselineValidationError(
                        f"Invalid metrics baseline schema at {path}: "
                        "api param 'has_default' must be bool",
                        status=MetricsBaselineStatus.INVALID_TYPE,
                    )
                params.append(
                    ApiParamSpec(
                        name=name,
                        kind=cast(
                            (
                                "Literal['pos_only', 'pos_or_kw', "
                                "'vararg', 'kw_only', 'kwarg']"
                            ),
                            param_kind,
                        ),
                        has_default=has_default,
                        annotation_hash=annotation_hash or "",
                    )
                )
            symbols.append(
                PublicSymbol(
                    qualname=qualname or "",
                    kind=cast(
                        "Literal['function', 'class', 'method', 'constant']",
                        kind,
                    ),
                    start_line=_require_int(raw_symbol, "start_line", path=path),
                    end_line=_require_int(raw_symbol, "end_line", path=path),
                    params=tuple(params),
                    returns_hash=_optional_require_str(
                        raw_symbol,
                        "returns_hash",
                        path=path,
                    )
                    or "",
                    exported_via=cast("Literal['all', 'name']", exported_via),
                )
            )
        modules.append(
            ModuleApiSurface(
                module=module,
                filepath=filepath,
                symbols=tuple(sorted(symbols, key=lambda item: item.qualname)),
                all_declared=tuple(all_declared) if all_declared is not None else None,
            )
        )
    return ApiSurfaceSnapshot(
        modules=tuple(sorted(modules, key=lambda item: (item.filepath, item.module)))
    )


def _require_str_list_or_none(
    payload: dict[str, Any],
    key: str,
    *,
    path: Path,
) -> list[str] | None:
    value = payload.get(key)
    if value is None:
        return None
    return _require_str_list(payload, key, path=path)


__all__ = [
    "_atomic_write_json",
    "_extract_metrics_payload_sha256",
    "_is_compatible_metrics_schema",
    "_load_json_object",
    "_optional_require_str",
    "_parse_api_surface_snapshot",
    "_parse_cycles",
    "_parse_generator",
    "_parse_snapshot",
    "_require_embedded_clone_baseline_payload",
    "_require_int",
    "_require_str",
    "_require_str_list",
    "_resolve_embedded_schema_version",
    "_validate_exact_keys",
    "_validate_required_keys",
    "_validate_top_level_structure",
]

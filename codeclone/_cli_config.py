"""
CodeClone CLI configuration loading from pyproject.toml.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final


class ConfigValidationError(ValueError):
    """Raised when pyproject.toml contains invalid CodeClone configuration."""


@dataclass(frozen=True, slots=True)
class _ConfigKeySpec:
    expected_type: type[object]
    allow_none: bool = False


_CONFIG_KEY_SPECS: Final[dict[str, _ConfigKeySpec]] = {
    "min_loc": _ConfigKeySpec(int),
    "min_stmt": _ConfigKeySpec(int),
    "processes": _ConfigKeySpec(int),
    "cache_path": _ConfigKeySpec(str, allow_none=True),
    "max_cache_size_mb": _ConfigKeySpec(int),
    "baseline": _ConfigKeySpec(str),
    "max_baseline_size_mb": _ConfigKeySpec(int),
    "update_baseline": _ConfigKeySpec(bool),
    "fail_on_new": _ConfigKeySpec(bool),
    "fail_threshold": _ConfigKeySpec(int),
    "ci": _ConfigKeySpec(bool),
    "fail_complexity": _ConfigKeySpec(int),
    "fail_coupling": _ConfigKeySpec(int),
    "fail_cohesion": _ConfigKeySpec(int),
    "fail_cycles": _ConfigKeySpec(bool),
    "fail_dead_code": _ConfigKeySpec(bool),
    "fail_health": _ConfigKeySpec(int),
    "fail_on_new_metrics": _ConfigKeySpec(bool),
    "update_metrics_baseline": _ConfigKeySpec(bool),
    "metrics_baseline": _ConfigKeySpec(str),
    "skip_metrics": _ConfigKeySpec(bool),
    "skip_dead_code": _ConfigKeySpec(bool),
    "skip_dependencies": _ConfigKeySpec(bool),
    "html_out": _ConfigKeySpec(str, allow_none=True),
    "json_out": _ConfigKeySpec(str, allow_none=True),
    "text_out": _ConfigKeySpec(str, allow_none=True),
    "no_progress": _ConfigKeySpec(bool),
    "no_color": _ConfigKeySpec(bool),
    "quiet": _ConfigKeySpec(bool),
    "verbose": _ConfigKeySpec(bool),
    "debug": _ConfigKeySpec(bool),
}
_PATH_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "cache_path",
        "baseline",
        "metrics_baseline",
        "html_out",
        "json_out",
        "text_out",
    }
)


def collect_explicit_cli_dests(
    parser: argparse.ArgumentParser,
    *,
    argv: Sequence[str],
) -> set[str]:
    option_to_dest: dict[str, str] = {}
    for action in parser._actions:
        for option in action.option_strings:
            option_to_dest[option] = action.dest

    explicit: set[str] = set()
    for token in argv:
        if token == "--":
            break
        if not token.startswith("-"):
            continue
        option = token.split("=", maxsplit=1)[0]
        dest = option_to_dest.get(option)
        if dest is not None:
            explicit.add(dest)
    return explicit


def load_pyproject_config(root_path: Path) -> dict[str, object]:
    config_path = root_path / "pyproject.toml"
    if not config_path.exists():
        return {}

    payload: object
    try:
        payload = _load_toml(config_path)
    except OSError as exc:
        raise ConfigValidationError(
            f"Cannot read pyproject.toml at {config_path}: {exc}"
        ) from exc
    except ValueError as exc:
        raise ConfigValidationError(f"Invalid TOML in {config_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigValidationError(
            f"Invalid pyproject payload at {config_path}: root must be object"
        )

    tool_obj = payload.get("tool")
    if tool_obj is None:
        return {}
    if not isinstance(tool_obj, dict):
        raise ConfigValidationError(
            f"Invalid pyproject payload at {config_path}: 'tool' must be object"
        )

    codeclone_obj = tool_obj.get("codeclone")
    if codeclone_obj is None:
        return {}
    if not isinstance(codeclone_obj, dict):
        raise ConfigValidationError(
            "Invalid pyproject payload at "
            f"{config_path}: 'tool.codeclone' must be object"
        )

    unknown = sorted(set(codeclone_obj.keys()) - set(_CONFIG_KEY_SPECS))
    if unknown:
        raise ConfigValidationError(
            "Unknown key(s) in tool.codeclone: " + ", ".join(unknown)
        )

    validated: dict[str, object] = {}
    for key in sorted(codeclone_obj.keys()):
        value = _validate_config_value(
            key=key,
            value=codeclone_obj[key],
        )
        validated[key] = _normalize_path_config_value(
            key=key,
            value=value,
            root_path=root_path,
        )
    return validated


def apply_pyproject_config_overrides(
    *,
    args: argparse.Namespace,
    config_values: Mapping[str, object],
    explicit_cli_dests: set[str],
) -> None:
    for key, value in config_values.items():
        if key in explicit_cli_dests:
            continue
        setattr(args, key, value)


def _validate_config_value(*, key: str, value: object) -> object:
    spec = _CONFIG_KEY_SPECS[key]
    if value is None:
        if spec.allow_none:
            return None
        raise ConfigValidationError(
            "Invalid value type for tool.codeclone."
            f"{key}: expected {spec.expected_type.__name__}"
        )

    if spec.expected_type is bool:
        if isinstance(value, bool):
            return value
        raise ConfigValidationError(
            f"Invalid value type for tool.codeclone.{key}: expected bool"
        )

    if spec.expected_type is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ConfigValidationError(
            f"Invalid value type for tool.codeclone.{key}: expected int"
        )

    if spec.expected_type is str:
        if isinstance(value, str):
            return value
        raise ConfigValidationError(
            f"Invalid value type for tool.codeclone.{key}: expected str"
        )

    raise ConfigValidationError(f"Unsupported config key spec for tool.codeclone.{key}")


def _load_toml(path: Path) -> object:
    if sys.version_info >= (3, 11):
        import tomllib

        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    else:
        try:
            tomli_module = importlib.import_module("tomli")
        except ModuleNotFoundError as exc:
            raise ConfigValidationError(
                "Python 3.10 requires dependency 'tomli' to read pyproject.toml."
            ) from exc

        load_fn = getattr(tomli_module, "load", None)
        if not callable(load_fn):
            raise ConfigValidationError(
                "Invalid 'tomli' module: missing callable 'load'."
            )

        with path.open("rb") as config_file:
            return load_fn(config_file)


def _normalize_path_config_value(
    *,
    key: str,
    value: object,
    root_path: Path,
) -> object:
    if key not in _PATH_CONFIG_KEYS:
        return value
    if not isinstance(value, str):
        return value

    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    return str(root_path / path)

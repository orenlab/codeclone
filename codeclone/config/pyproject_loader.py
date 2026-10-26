from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ..findings.clones.golden_fixtures import (
    GoldenFixturePatternError,
    normalize_golden_fixture_patterns,
)
from .spec import CONFIG_KEY_SPECS, OPTIONS, PATH_CONFIG_KEYS, ConfigKeySpec

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Set


class ConfigValidationError(ValueError):
    """Raised when pyproject.toml contains invalid CodeClone configuration."""


def validate_config_value(
    *,
    key: str,
    value: object,
    config_key_specs: Mapping[str, ConfigKeySpec] = CONFIG_KEY_SPECS,
) -> object:
    spec = config_key_specs[key]
    if value is None:
        if spec.allow_none:
            return None
        raise ConfigValidationError(
            "Invalid value type for tool.codeclone."
            f"{key}: expected {spec.expected_name or spec.expected_type.__name__}"
        )

    expected_type = spec.expected_type
    if expected_type is bool:
        return _validated_config_instance(
            key=key,
            value=value,
            expected_type=bool,
            expected_name="bool",
        )

    if expected_type is int:
        return _validated_config_instance(
            key=key,
            value=value,
            expected_type=int,
            expected_name="int",
            reject_bool=True,
        )

    if expected_type is str:
        return _validated_config_instance(
            key=key,
            value=value,
            expected_type=str,
            expected_name="str",
        )

    if expected_type is list:
        return _validated_string_list(key=key, value=value)

    raise ConfigValidationError(f"Unsupported config key spec for tool.codeclone.{key}")


def load_pyproject_config(
    root_path: Path,
    *,
    load_toml: Callable[[Path], object] | None = None,
    config_key_specs: Mapping[str, ConfigKeySpec] = CONFIG_KEY_SPECS,
    path_config_keys: Set[str] | frozenset[str] = PATH_CONFIG_KEYS,
) -> dict[str, object]:
    config_path = root_path / "pyproject.toml"
    if not config_path.exists():
        return {}

    load_toml_fn = _load_toml if load_toml is None else load_toml

    payload: object
    try:
        payload = load_toml_fn(config_path)
    except OSError as exc:
        raise ConfigValidationError(
            f"Cannot read pyproject.toml at {config_path}: {exc}"
        ) from exc
    except ValueError as exc:
        raise ConfigValidationError(f"Invalid TOML in {config_path}: {exc}") from exc
    except RecursionError as exc:
        raise ConfigValidationError(
            f"Invalid TOML in {config_path}: values are nested too deeply to read."
        ) from exc

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

    unknown = sorted(set(codeclone_obj.keys()) - set(config_key_specs))
    if unknown:
        raise ConfigValidationError(
            "Unknown key(s) in tool.codeclone: " + ", ".join(unknown)
        )

    validated: dict[str, object] = {}
    for key in sorted(codeclone_obj.keys()):
        value = validate_config_value(
            key=key,
            value=codeclone_obj[key],
            config_key_specs=config_key_specs,
        )
        validated[key] = normalize_path_config_value(
            key=key,
            value=value,
            root_path=root_path,
            path_config_keys=path_config_keys,
        )
    return validated


#: Why a path the repository's own ``pyproject.toml`` names may not leave it,
#: and what the user can do instead.
_ERR_PATH_OUTSIDE_REPOSITORY = (
    "tool.codeclone.{key} = {value!r} must stay under the repository root, "
    "because a path in the repository's own pyproject.toml may only point "
    "inside the repository; choose a path inside the repository{remedy}."
)
_REMEDY_COMMAND_LINE_FLAG = ", or pass the outside path on the command line with {flag}"

#: The command-line flag that carries each path key: the user's own word, the
#: only way a path outside the repository is accepted. Read from the option
#: table so the remedy names the spelling ``--help`` documents.
_PATH_KEY_FLAGS: Final[Mapping[str, str]] = {
    spec.pyproject_key: spec.flags[0]
    for spec in OPTIONS
    if spec.path_value and spec.pyproject_key is not None and spec.flags
}


def normalize_path_config_value(
    *,
    key: str,
    value: object,
    root_path: Path,
    path_config_keys: Set[str] | frozenset[str] = PATH_CONFIG_KEYS,
) -> object:
    """Anchor a path from ``pyproject.toml`` at the repository and keep it there.

    The value is the repository author's word, not the user's: a repository
    that named ``../victim/notes.md`` or ``~/.bashrc`` here made a plain
    ``codeclone .`` overwrite that file. So the path is resolved first -- every
    existing component, symbolic links included -- and refused unless the
    result lies under the repository root. The refusal happens while the
    configuration is read, before anything is written or created. A path
    outside the repository is still accepted from the command line, which
    never passes through here.

    The returned spelling is unchanged (the root joined to the value, not the
    resolved path), so a consumer that refuses a symbolic link at the final
    component still sees it.
    """

    if key not in path_config_keys:
        return value
    if not isinstance(value, str):
        return value

    path = Path(value).expanduser()
    _refuse_path_outside_repository(path, root_path=root_path, key=key, value=value)
    if path.is_absolute():
        return str(path)
    return str(root_path / path)


def _refuse_path_outside_repository(
    path: Path, *, root_path: Path, key: str, value: str
) -> None:
    """Resolve *path* under the repository root, or refuse the key by name."""

    candidate = path if path.is_absolute() else root_path / path
    try:
        resolved_root = root_path.resolve(strict=True)
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise ConfigValidationError(
            f"Invalid value for tool.codeclone.{key}: cannot resolve {value!r}: {exc}"
        ) from exc
    if resolved.is_relative_to(resolved_root):
        return
    flag = _PATH_KEY_FLAGS.get(key)
    raise ConfigValidationError(
        _ERR_PATH_OUTSIDE_REPOSITORY.format(
            key=key,
            value=value,
            remedy=_REMEDY_COMMAND_LINE_FLAG.format(flag=flag) if flag else "",
        )
    )


def _validated_config_instance(
    *,
    key: str,
    value: object,
    expected_type: type[object],
    expected_name: str,
    reject_bool: bool = False,
) -> object:
    if isinstance(value, expected_type) and (
        not reject_bool or not isinstance(value, bool)
    ):
        return value
    raise ConfigValidationError(
        f"Invalid value type for tool.codeclone.{key}: expected {expected_name}"
    )


def _validated_string_list(*, key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigValidationError(
            f"Invalid value type for tool.codeclone.{key}: expected list[str]"
        )
    if not all(isinstance(item, str) for item in value):
        raise ConfigValidationError(
            f"Invalid value type for tool.codeclone.{key}: expected list[str]"
        )
    try:
        return normalize_golden_fixture_patterns(value)
    except GoldenFixturePatternError as exc:
        raise ConfigValidationError(str(exc)) from exc


def _load_toml(path: Path) -> object:
    if sys.version_info >= (3, 11):
        import tomllib

        with path.open("rb") as config_file:
            return tomllib.load(config_file)

    try:
        tomli_module = importlib.import_module("tomli")
    except ModuleNotFoundError as exc:
        raise ConfigValidationError(
            "Python 3.10 requires dependency 'tomli' to read pyproject.toml."
        ) from exc

    load_fn = getattr(tomli_module, "load", None)
    if not callable(load_fn):
        raise ConfigValidationError("Invalid 'tomli' module: missing callable 'load'.")

    with path.open("rb") as config_file:
        return load_fn(config_file)


__all__ = [
    "CONFIG_KEY_SPECS",
    "PATH_CONFIG_KEYS",
    "ConfigValidationError",
    "_load_toml",
    "load_pyproject_config",
    "normalize_path_config_value",
    "validate_config_value",
]

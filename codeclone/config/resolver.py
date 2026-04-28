from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    values: dict[str, object]
    explicit_cli_dests: frozenset[str]
    pyproject_values: dict[str, object]


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


def resolve_config(
    *,
    args: argparse.Namespace,
    config_values: Mapping[str, object],
    explicit_cli_dests: set[str],
) -> ResolvedConfig:
    resolved_values = vars(args).copy()
    for key, value in config_values.items():
        if key in explicit_cli_dests:
            continue
        resolved_values[key] = value

    return ResolvedConfig(
        values=resolved_values,
        explicit_cli_dests=frozenset(explicit_cli_dests),
        pyproject_values=dict(config_values),
    )


def apply_resolved_config(
    *,
    args: argparse.Namespace,
    resolved: ResolvedConfig,
) -> None:
    for key, value in resolved.values.items():
        setattr(args, key, value)


def apply_pyproject_config_overrides(
    *,
    args: argparse.Namespace,
    config_values: Mapping[str, object],
    explicit_cli_dests: set[str],
) -> None:
    apply_resolved_config(
        args=args,
        resolved=resolve_config(
            args=args,
            config_values=config_values,
            explicit_cli_dests=explicit_cli_dests,
        ),
    )


__all__ = [
    "ResolvedConfig",
    "apply_pyproject_config_overrides",
    "apply_resolved_config",
    "collect_explicit_cli_dests",
    "resolve_config",
]

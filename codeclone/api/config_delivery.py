# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal R3 configuration-delivery door over the canonical R2 config owners.

Every surface that analyses a repository resolves its configuration through
``config.resolver``. Historically the MCP surface did not: it hand-set attributes
on an ``argparse.Namespace`` from a closed allowlist, so autodetected
``source_roots``, the authority registry, and the opt-in clone tiers never
reached the pipeline. A key was therefore *absent* from a surface for two
indistinguishable reasons -- a deliberate policy, or nobody having added its
name.

This door removes that ambiguity. A surface declares **how** it consumes the
resolved configuration, and every deviation from "deliver everything" is an
explicit :class:`Withholding` carrying the rule it protects. Silence is no longer
a policy.

Two declaration shapes exist, because the two real cases are genuinely different:

``DELIVER_ALL_EXCEPT``
    The surface honours the repository's configuration, minus keys it has no
    authority to act on. Used by every surface that respects ``pyproject.toml``.

``DELIVER_ONLY``
    The caller explicitly asked the surface *not* to honour repository
    configuration, yet a few keys remain required for identity to stay
    comparable. Used by the MCP governance path (``respect_pyproject=false``).

One rule, one owner. ``DELIVER_ONLY`` is enforced as a **whitelist** inside
:func:`delivered_config_values`, never as "everything configurable minus the
required keys": a key the declared universe does not know about is not in that
universe, so a subtraction would deliver it. :func:`withheld_keys` still reports
the complement for ``DELIVER_ONLY``, but that projection is for explaining a
decision, not for making it.

It lives here, and not under ``config/``, because a door is what keeps an R4
surface out of R2: the declaration is consumed by surfaces, while the loader,
the specs and the resolver it reads stay canonical owners behind it.

A declaration also states **where** it happens and **by which route**. Naming
the module is what makes the contract checkable without asking a human: the
ratchet reads :data:`DELIVERIES`, computes which production modules actually
reach the resolver, and reds when the two disagree in either direction. A
surface declared here that no longer delivers is as much a lie about coverage
as a delivery nobody declared, so both are the same failure.

:class:`DeliveryRoute` exists because one surface legitimately does not use this
door. A surface with real command-line flags MUST pass its own
``explicit_cli_dests``, and this door has none to pass; routing it through here
would hand the resolver an empty set and let ``pyproject.toml`` overwrite a
value the user typed. That is a rule, so it is declared as one rather than left
as an absence -- an undeclared absence is exactly the silence this door removes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final

from ..config.analytics_specs import ANALYTICS_NESTED_TABLE_KEY
from ..config.memory_specs import MEMORY_NESTED_TABLE_KEY
from ..config.pyproject_loader import load_pyproject_config
from ..config.pyproject_writer import (
    ToolCodecloneTableState,
    probe_tool_codeclone_table,
)
from ..config.resolver import apply_pyproject_config_overrides
from ..config.spec import CONFIG_KEY_SPECS

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping
    from pathlib import Path

#: Nested pyproject table validated outside ``CONFIG_KEY_SPECS``
#: (``config.pyproject_loader`` parses it through ``parse_authority_registry``).
#: It is a configurable key for delivery purposes and MUST be declared here, or
#: a surface can silently lose the whole authority lane.
AUTHORITY_KEY: Final = "authority"

#: Every nested table ``load_pyproject_config`` publishes as one top-level key.
#: These are the keys the flat specs cannot describe, and the reason the declared
#: universe has to be derived from the loader rather than from the flat specs
#: alone.
NESTED_TABLE_KEYS: Final = frozenset(
    {
        MEMORY_NESTED_TABLE_KEY,
        ANALYTICS_NESTED_TABLE_KEY,
        AUTHORITY_KEY,
    }
)


class DeliverySurface(str, Enum):
    """Every plumbing that delivers repository configuration into an analysis run."""

    CLI = "cli"
    CLI_MEMORY = "cli_memory"
    MCP = "mcp"
    MCP_PYPROJECT_DECLINED = "mcp_pyproject_declined"


class DeliveryMode(str, Enum):
    """How a surface's declaration is to be read."""

    DELIVER_ALL_EXCEPT = "deliver_all_except"
    DELIVER_ONLY = "deliver_only"


class DeliveryRoute(str, Enum):
    """How a surface reaches the canonical resolver behind this door."""

    THROUGH_THE_DOOR = "through_the_door"
    RESOLVER_DIRECT = "resolver_direct"


@dataclass(frozen=True)
class Withholding:
    """One key a surface does not deliver, and the rule that requires that."""

    key: str
    reason: str


@dataclass(frozen=True)
class SurfaceDelivery:
    """A surface's declared relationship to repository configuration.

    ``module`` is the production module that performs this surface's delivery.
    It is what turns the declaration from prose into something a guard can
    check: without it "which surfaces exist" is answerable only by a human
    reading the code, and a declaration nobody can check is decoration.
    """

    surface: DeliverySurface
    mode: DeliveryMode
    module: str
    route: DeliveryRoute = DeliveryRoute.THROUGH_THE_DOOR
    route_reason: str = ""
    withheld: tuple[Withholding, ...] = ()
    required: tuple[Withholding, ...] = ()

    def __post_init__(self) -> None:
        # A table, not a branch ladder: these are five declaration rules, and
        # adding the sixth should cost a row rather than another decision.
        rules: tuple[tuple[bool, str], ...] = (
            (
                self.mode is DeliveryMode.DELIVER_ALL_EXCEPT and bool(self.required),
                "deliver_all_except declares no required keys",
            ),
            (
                self.mode is DeliveryMode.DELIVER_ONLY and bool(self.withheld),
                "deliver_only declares no withheld keys",
            ),
            (
                not self.module.strip(),
                "a delivery declares the module performing it",
            ),
            (
                self.route is DeliveryRoute.RESOLVER_DIRECT
                and not self.route_reason.strip(),
                "resolver_direct declares why it is not a hole",
            ),
            (
                self.route is DeliveryRoute.THROUGH_THE_DOOR
                and bool(self.route_reason.strip()),
                "through_the_door declares no route reason",
            ),
        )
        for broken, rule in rules:
            if broken:
                raise ValueError(f"{self.surface.value}: {rule}")


_REPORT_WRITE_RULE: Final = (
    "MCP is read-only with respect to generated reports; a repository MUST NOT "
    "be able to make the server write report files"
)
_NOT_A_TERMINAL_RULE: Final = (
    "the surface is not a terminal; presentation and verbosity are fixed by the "
    "surface, not by the analysed repository"
)
_NO_BASELINE_WRITE_RULE: Final = (
    "MCP MUST NOT mutate baselines; delivering this would create a write path "
    "that does not exist today"
)
_IDENTITY_STILL_REQUIRED_RULE: Final = (
    "the caller declined repository configuration, but this key participates in "
    "baseline identity and comparability, so dropping it would silently change "
    "what is compared"
)
_CLI_HAS_ITS_OWN_EXPLICIT_DESTS_RULE: Final = (
    "the terminal surface has real command-line flags, so it must pass its own "
    "explicit_cli_dests to the resolver; this door has none to pass, and routing "
    "the CLI through it would let pyproject.toml overwrite a value the user typed "
    "on the command line"
)

_MCP_WITHHELD: Final = (
    Withholding("html_out", _REPORT_WRITE_RULE),
    Withholding("json_out", _REPORT_WRITE_RULE),
    Withholding("md_out", _REPORT_WRITE_RULE),
    Withholding("sarif_out", _REPORT_WRITE_RULE),
    Withholding("text_out", _REPORT_WRITE_RULE),
    Withholding("no_color", _NOT_A_TERMINAL_RULE),
    Withholding("no_progress", _NOT_A_TERMINAL_RULE),
    Withholding("quiet", _NOT_A_TERMINAL_RULE),
    Withholding("verbose", _NOT_A_TERMINAL_RULE),
    Withholding("debug", _NOT_A_TERMINAL_RULE),
    Withholding("update_baseline", _NO_BASELINE_WRITE_RULE),
)

_DELIVERIES: Final[tuple[SurfaceDelivery, ...]] = (
    SurfaceDelivery(
        DeliverySurface.CLI,
        DeliveryMode.DELIVER_ALL_EXCEPT,
        module="codeclone.surfaces.cli.workflow",
        route=DeliveryRoute.RESOLVER_DIRECT,
        route_reason=_CLI_HAS_ITS_OWN_EXPLICIT_DESTS_RULE,
    ),
    SurfaceDelivery(
        DeliverySurface.CLI_MEMORY,
        DeliveryMode.DELIVER_ALL_EXCEPT,
        module="codeclone.surfaces.cli.memory_analysis",
    ),
    SurfaceDelivery(
        DeliverySurface.MCP,
        DeliveryMode.DELIVER_ALL_EXCEPT,
        module="codeclone.surfaces.mcp._session_state_mixin",
        withheld=_MCP_WITHHELD,
    ),
    # Autodetection is deliberately NOT a withholding here. ``source_roots`` is
    # withheld from this surface as *configuration*, but the resolver still runs
    # with the repository root, so an unset value is autodetected on both MCP
    # surfaces. Declining a repository's configuration must not silently change
    # the import mount the run analyses, or the two surfaces stop being
    # comparable.
    SurfaceDelivery(
        DeliverySurface.MCP_PYPROJECT_DECLINED,
        DeliveryMode.DELIVER_ONLY,
        module="codeclone.surfaces.mcp._session_state_mixin",
        required=(
            Withholding("baseline_scope_id", _IDENTITY_STILL_REQUIRED_RULE),
            Withholding("golden_fixture_paths", _IDENTITY_STILL_REQUIRED_RULE),
        ),
    ),
)

DELIVERIES: Final[Mapping[DeliverySurface, SurfaceDelivery]] = {
    delivery.surface: delivery for delivery in _DELIVERIES
}


def configurable_keys() -> frozenset[str]:
    """Every top-level key a repository can set in ``pyproject.toml``.

    Derived from the producer, not restated: ``load_pyproject_config`` publishes
    the flat ``CONFIG_KEY_SPECS`` keys plus one key per validated nested table.
    The keys *inside* a nested table are that table's own contract and never
    appear at this level, so listing them here would declare keys no repository
    can set at top level -- the dead-contract-content defect this door exists
    to make impossible.
    """
    return frozenset(CONFIG_KEY_SPECS) | NESTED_TABLE_KEYS


def delivery_modules(route: DeliveryRoute) -> frozenset[str]:
    """Production modules declared to deliver configuration by ``route``.

    Two surfaces may share one module -- ``respect_pyproject`` picks between the
    MCP declarations inside a single call site -- so this is a set of modules,
    not a per-surface listing.
    """
    return frozenset(
        delivery.module for delivery in _DELIVERIES if delivery.route is route
    )


def required_keys(surface: DeliverySurface) -> frozenset[str]:
    """Keys a ``DELIVER_ONLY`` surface still requires; empty for the other mode."""
    delivery = DELIVERIES[surface]
    if delivery.mode is DeliveryMode.DELIVER_ONLY:
        return frozenset(item.key for item in delivery.required)
    return frozenset()


def withheld_keys(surface: DeliverySurface) -> frozenset[str]:
    """Keys ``surface`` declares it does not deliver.

    For ``DELIVER_ONLY`` this is a *reporting* projection over the declared
    universe. It explains a decision and MUST NOT be used to make one --
    :func:`delivered_config_values` enforces that mode as a whitelist.
    """
    delivery = DELIVERIES[surface]
    if delivery.mode is DeliveryMode.DELIVER_ONLY:
        return configurable_keys() - required_keys(surface)
    return frozenset(item.key for item in delivery.withheld)


def withholding_reason(surface: DeliverySurface, key: str) -> str | None:
    """The declared rule that stops ``surface`` delivering ``key``, if it does."""
    delivery = DELIVERIES[surface]
    if delivery.mode is DeliveryMode.DELIVER_ONLY:
        if key in required_keys(surface):
            return None
        return (
            f"not required under {surface.value}: "
            f"{_IDENTITY_STILL_REQUIRED_RULE.split(',', 1)[0]}"
        )
    for item in delivery.withheld:
        if item.key == key:
            return item.reason
    return None


def delivered_config_values(
    *,
    surface: DeliverySurface,
    config_values: Mapping[str, object],
) -> dict[str, object]:
    """Project ``config_values`` through the declared contract for ``surface``.

    The result is what the surface hands to the resolver; the resolver, not this
    door, remains the single place that applies precedence and autodetection.
    """
    delivery = DELIVERIES[surface]
    if delivery.mode is DeliveryMode.DELIVER_ONLY:
        keep = required_keys(surface)
        return {
            key: value for key, value in sorted(config_values.items()) if key in keep
        }
    withheld = withheld_keys(surface)
    return {
        key: value
        for key, value in sorted(config_values.items())
        if key not in withheld
    }


def load_repository_config(root_path: Path) -> dict[str, object]:
    """Read the repository's own configuration through the canonical loader.

    Raises ``config.pyproject_loader.ConfigValidationError`` unchanged: a surface
    decides how to present an invalid repository configuration, and the door does
    not soften the diagnosis on its way out.
    """
    return load_pyproject_config(root_path)


def apply_repository_config(
    *,
    args: argparse.Namespace,
    config_values: Mapping[str, object],
    root_path: Path | None = None,
) -> None:
    """Resolve delivered configuration and apply it to a surface's namespace.

    For surfaces that have **no command line**. MCP and the memory-init path have
    no ``argv``, so nothing was explicitly supplied that repository configuration
    must not override, and ``explicit_cli_dests`` is empty by construction
    (mem-bd3480c0). A surface with real CLI flags MUST keep using
    ``config.resolver`` directly and pass its own explicit dests.

    ``root_path`` is what lets the resolver autodetect ``source_roots``. Omit it
    and the import mount silently differs from every other surface.
    """
    apply_pyproject_config_overrides(
        args=args,
        config_values=config_values,
        explicit_cli_dests=set(),
        root_path=root_path,
    )


def tool_codeclone_table_state(root_path: Path) -> ToolCodecloneTableState:
    """Report the shape of ``[tool.codeclone]`` to a surface, through the door.

    A surface that has to tell an operator what to paste into
    ``pyproject.toml`` needs to know whether the table is already there, and
    the answer belongs to ``config.pyproject_writer`` -- the module that knows
    how the table is created. R4 may not read R2, so the question comes through
    here, exactly as configuration delivery does: the loader and the writer
    stay canonical owners behind this door, and no surface grows its own idea
    of the file's shape.
    """

    return probe_tool_codeclone_table(root_path)


__all__ = [
    "AUTHORITY_KEY",
    "DELIVERIES",
    "NESTED_TABLE_KEYS",
    "DeliveryMode",
    "DeliveryRoute",
    "DeliverySurface",
    "SurfaceDelivery",
    "ToolCodecloneTableState",
    "Withholding",
    "apply_repository_config",
    "configurable_keys",
    "delivered_config_values",
    "delivery_modules",
    "load_repository_config",
    "required_keys",
    "tool_codeclone_table_state",
    "withheld_keys",
    "withholding_reason",
]

"""Ratchet for the declared configuration-delivery contract.

The contract exists because a key could be absent from a surface for two
indistinguishable reasons: a deliberate policy, or nobody having added its name.
These tests red in both directions — a withholding that no longer corresponds to
a configurable key, and a delivery boundary that silently stops carrying one.

Three layers are pinned separately, and the names say which layer a test holds:

``declares``
    the declaration against the code it describes (no delivery happens).
``projection``
    ``delivered_config_values`` as a pure function over a config mapping.
``surface``
    a real surface: ``_build_args`` for MCP, ``run_memory_analysis_report`` for
    the CLI memory path. Only these tests can see whether a declared key
    actually arrives — a projection test is green with no wiring at all.

Each test pins one edge and reports a witness of its own, so a failure names
which edge broke rather than only that something did.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

import codeclone.surfaces.cli.workflow as cli_workflow
from codeclone.api import config_delivery as delivery
from codeclone.api.config_delivery import DeliveryMode, DeliverySurface
from codeclone.surfaces.cli.memory_analysis import run_memory_analysis_report
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService

# The exact set MCP withholds. Pinned as a literal set, not as a relation: a
# relative invariant ("MCP withholds some keys") stays green for any content, so
# removing update_baseline would silently open a baseline write path.
MCP_WITHHELD_EXACT = frozenset(
    {
        "html_out",
        "json_out",
        "md_out",
        "sarif_out",
        "text_out",
        "no_color",
        "no_progress",
        "quiet",
        "verbose",
        "debug",
        "update_baseline",
    }
)

# The two keys MCP still honours when the caller declined repository config.
DECLINED_DELIVERED_EXACT = frozenset({"baseline_scope_id", "golden_fixture_paths"})

# baseline_scope_id is validated as a canonical UUID by FoundationConfigInput, so
# the fixture cannot use a readable label here.
DECLARED_SCOPE_ID = "2f1c9b74-5d3a-4f19-8c62-7a0e5b4d3c21"


def _declared_keys(surface: DeliverySurface) -> frozenset[str]:
    """Keys the surface's declaration names explicitly, whichever shape it uses."""
    declaration = delivery.DELIVERIES[surface]
    if declaration.mode is DeliveryMode.DELIVER_ONLY:
        return frozenset(item.key for item in declaration.required)
    return frozenset(item.key for item in declaration.withheld)


def _field(payload: object, key: str) -> object:
    """One typed step down a report document, without a per-step assert ladder."""
    assert isinstance(payload, dict), f"expected a table to read {key!r} from"
    return payload[key]


def _rows(payload: object) -> tuple[object, ...]:
    """One typed step into a report document's sequence lane."""
    assert isinstance(payload, (list, tuple)), "expected a sequence"
    return tuple(payload)


# --------------------------------------------------------------------------------------
# Layer 1: the declaration against the code it describes
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("surface", list(DeliverySurface))
def test_every_declared_key_is_actually_configurable(surface: DeliverySurface) -> None:
    """A declaration naming a key no repository can set is dead contract content.

    This is the defect class the retired MCP allowlist carried: it listed a key
    that could never match the loaded configuration, so the entry looked like
    policy and was noise.
    """
    configurable = delivery.configurable_keys()
    declared = _declared_keys(surface)

    unknown = sorted(declared - configurable)

    assert unknown == [], f"{surface.value} declares non-configurable keys: {unknown}"


@pytest.mark.parametrize("surface", list(DeliverySurface))
def test_every_declaration_carries_a_non_empty_reason(surface: DeliverySurface) -> None:
    """A deviation without a stated rule is the silence the contract removes."""
    declaration = delivery.DELIVERIES[surface]
    items = declaration.withheld or declaration.required

    reasonless = sorted(item.key for item in items if not item.reason.strip())

    assert reasonless == [], (
        f"{surface.value} deviations without a reason: {reasonless}"
    )


@pytest.mark.parametrize(
    ("mode", "kwargs", "expected"),
    [
        (
            DeliveryMode.DELIVER_ALL_EXCEPT,
            {"required": (delivery.Withholding("min_loc", "irrelevant"),)},
            "deliver_all_except declares no required keys",
        ),
        (
            DeliveryMode.DELIVER_ONLY,
            {"withheld": (delivery.Withholding("min_loc", "irrelevant"),)},
            "deliver_only declares no withheld keys",
        ),
        (
            DeliveryMode.DELIVER_ALL_EXCEPT,
            {"module": "   "},
            "a delivery declares the module performing it",
        ),
        (
            DeliveryMode.DELIVER_ALL_EXCEPT,
            {"route": delivery.DeliveryRoute.RESOLVER_DIRECT},
            "resolver_direct declares why it is not a hole",
        ),
        (
            DeliveryMode.DELIVER_ALL_EXCEPT,
            {"route_reason": "no route needs this"},
            "through_the_door declares no route reason",
        ),
    ],
)
def test_a_declaration_the_ratchet_cannot_read_is_rejected(
    mode: DeliveryMode,
    kwargs: dict[str, object],
    expected: str,
) -> None:
    """Reachability: every declaration guard has an input that trips it.

    The two shapes answer different questions, so a declaration carrying both
    lists has no single reading. A guard nothing can be shown to reach is
    theatre, so exhibit the input rather than trusting the branch.

    The route guards are here for the same reason. An unnamed module is a
    declaration the ratchet cannot resolve to code; a resolver-direct route
    with no reason is an exemption without the rule that earns it; and a reason
    attached to a route that needs none is dead contract content.
    """
    declaration: dict[str, object] = {
        "module": "codeclone.surfaces.mcp._session_state_mixin",
        **kwargs,
    }
    with pytest.raises(ValueError, match=expected):
        delivery.SurfaceDelivery(DeliverySurface.MCP, mode, **declaration)  # type: ignore[arg-type]


def test_every_surface_declares_the_module_that_performs_it() -> None:
    """The declaration names code, or the ratchet has nothing to check.

    ``DeliverySurface.CLI`` was declared and consumed by nothing: no production
    caller, and no guard reading the declaration either. A surface that appears
    only in an enum claims coverage it does not have.
    """
    for surface in DeliverySurface:
        assert delivery.DELIVERIES[surface].module.startswith("codeclone.")


def test_the_cli_declares_why_it_does_not_use_this_door() -> None:
    """The one sanctioned exemption, stated as a rule rather than an absence.

    The CLI resolves through ``config.resolver`` directly because it must pass
    its own ``explicit_cli_dests``; this door has none. That is why it is not a
    hole, and it is declared so the ratchet can tell a sanctioned exemption
    from a surface that simply never got wired.
    """
    cli = delivery.DELIVERIES[DeliverySurface.CLI]

    assert cli.route is delivery.DeliveryRoute.RESOLVER_DIRECT
    assert "explicit_cli_dests" in cli.route_reason
    assert delivery.delivery_modules(delivery.DeliveryRoute.RESOLVER_DIRECT) == {
        "codeclone.surfaces.cli.workflow"
    }
    assert delivery.delivery_modules(delivery.DeliveryRoute.THROUGH_THE_DOOR) == {
        "codeclone.surfaces.cli.memory_analysis",
        "codeclone.surfaces.mcp._session_state_mixin",
    }


def test_mcp_withholds_exactly_the_declared_set() -> None:
    """Pin the list itself, not a relation over it.

    Mutating the constant must red here: dropping `update_baseline` would let a
    repository make the server write a baseline, and adding a key would silently
    narrow delivery.
    """
    assert delivery.withheld_keys(DeliverySurface.MCP) == MCP_WITHHELD_EXACT


def test_cli_surfaces_withhold_nothing() -> None:
    """The terminal surface is the reference: it honours the whole contract."""
    assert delivery.withheld_keys(DeliverySurface.CLI) == frozenset()
    assert delivery.withheld_keys(DeliverySurface.CLI_MEMORY) == frozenset()


def test_declined_pyproject_declares_only_identity_keys() -> None:
    """Declining repository configuration must not change what is compared."""
    declared = _declared_keys(DeliverySurface.MCP_PYPROJECT_DECLINED)

    assert declared == DECLINED_DELIVERED_EXACT


def test_declined_reporting_projection_explains_every_other_key() -> None:
    """The complement is for explaining the decision, never for making it.

    ``withheld_keys`` over a ``DELIVER_ONLY`` surface subtracts the required keys
    from the declared universe, which is exactly why it cannot be the
    enforcement path: a key the universe does not know is not in the complement.
    """
    withheld = delivery.withheld_keys(DeliverySurface.MCP_PYPROJECT_DECLINED)

    assert delivery.configurable_keys() - withheld == DECLINED_DELIVERED_EXACT
    assert (
        delivery.withholding_reason(DeliverySurface.MCP_PYPROJECT_DECLINED, "min_loc")
        is not None
    )
    assert (
        delivery.withholding_reason(
            DeliverySurface.MCP_PYPROJECT_DECLINED, "baseline_scope_id"
        )
        is None
    )
    assert delivery.required_keys(DeliverySurface.MCP) == frozenset()


def test_authority_table_is_part_of_the_contract() -> None:
    """The nested authority table is validated outside the flat specs.

    It is why widening a flat allowlist could never reach the authority lane.
    """
    assert delivery.AUTHORITY_KEY in delivery.configurable_keys()


def test_declared_universe_covers_every_key_the_loader_publishes(
    tmp_path: Path,
) -> None:
    """The universe is producer-derived, or it is a guess about the producer.

    ``configurable_keys`` is the declared set of keys a repository can set. Its
    only honest basis is what ``load_pyproject_config`` actually publishes at
    top level: the flat specs plus each validated nested table. A universe that
    misses a published table names no rule and reads as "not configurable",
    which is precisely the silence this contract removes.
    """
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            (
                "[tool.codeclone]",
                "min_loc = 7",
                "[tool.codeclone.memory]",
                "max_records = 5",
                "[tool.codeclone.analytics]",
                "enabled = true",
                "[[tool.codeclone.authority]]",
                'contract_id = "delivery/v1"',
                'canonical_owner = "pkg.mod:f"',
                "allowed_adapters = []",
                "forbidden_raw_inputs = []",
                'required_provenance = ["resolver"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    published = frozenset(delivery.load_repository_config(tmp_path))

    undeclared = sorted(published - delivery.configurable_keys())

    assert undeclared == [], f"loader publishes undeclared top-level keys: {undeclared}"


# --------------------------------------------------------------------------------------
# Layer 2: the contract's projection over a config mapping (no surface involved)
# --------------------------------------------------------------------------------------


def test_withheld_key_is_absent_from_the_projection() -> None:
    """Input edge: a withheld key must be absent from what the surface hands over."""
    delivered = delivery.delivered_config_values(
        surface=DeliverySurface.MCP,
        config_values={"html_out": "report.html", "min_loc": 9},
    )

    assert "html_out" not in delivered
    assert delivered["min_loc"] == 9


def test_projected_key_reaches_the_resolver() -> None:
    """Input edge: a delivered key must land in the resolved configuration."""
    args = argparse.Namespace(min_loc=6, source_roots=None)
    delivered = delivery.delivered_config_values(
        surface=DeliverySurface.MCP,
        config_values={"min_loc": 11},
    )

    delivery.apply_repository_config(args=args, config_values=delivered)

    assert args.min_loc == 11


def test_source_roots_autodetect_needs_root_path(tmp_path: Path) -> None:
    """Output edge: declaring delivery is not enough — the resolver needs the root.

    Omitting `root_path` is a distinct failure from omitting the key, and it must
    red under a distinct witness: the value is not merely stale, it is never
    computed.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pkg").mkdir()
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")

    with_root = argparse.Namespace(source_roots=None)
    without_root = argparse.Namespace(source_roots=None)

    delivery.apply_repository_config(
        args=with_root, config_values={}, root_path=tmp_path
    )
    delivery.apply_repository_config(args=without_root, config_values={})

    assert with_root.source_roots == ("src",)
    assert without_root.source_roots is None


def _repository_with_authority(tmp_path: Path) -> Path:
    """A src-layout repository whose pyproject exercises every declared edge."""
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            (
                "[tool.codeclone]",
                "semantic_authority = true",
                "fail_on_authority_violation = true",
                'html_out = "should-never-be-honoured.html"',
                "update_baseline = true",
                f'baseline_scope_id = "{DECLARED_SCOPE_ID}"',
                "min_loc = 12",
                'baseline = "conf-baseline.json"',
                "[tool.codeclone.memory]",
                "max_records = 5",
                "",
            )
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_projection_keeps_the_authority_lane_inputs(tmp_path: Path) -> None:
    """The authority lane is enabled from three inputs; none reached MCP before.

    This holds the projection only. It is green with no MCP wiring whatsoever —
    which is why the surface test below exists.
    """
    root = _repository_with_authority(tmp_path)
    config_values = delivery.load_repository_config(root)

    delivered = delivery.delivered_config_values(
        surface=DeliverySurface.MCP, config_values=config_values
    )

    assert delivered["semantic_authority"] is True
    assert delivered["fail_on_authority_violation"] is True


def test_projection_drops_report_writes_and_baseline_updates(tmp_path: Path) -> None:
    """The two withholdings that protect a rule, not a preference.

    The first two assertions are the reachability half: a repository really can
    set both keys, and the loader really publishes them. Without that, "not in
    delivered" would be vacuously true and the guard could be unreachable.
    """
    root = _repository_with_authority(tmp_path)
    config_values = delivery.load_repository_config(root)

    assert config_values["update_baseline"] is True
    assert str(config_values["html_out"]).endswith("should-never-be-honoured.html")

    delivered = delivery.delivered_config_values(
        surface=DeliverySurface.MCP, config_values=config_values
    )

    assert "html_out" not in delivered
    assert "update_baseline" not in delivered
    assert (
        delivery.withholding_reason(DeliverySurface.MCP, "update_baseline") is not None
    )
    # ...and a key that is delivered has no rule stopping it.
    assert delivery.withholding_reason(DeliverySurface.MCP, "min_loc") is None


# --------------------------------------------------------------------------------------
# Layer 3: the MCP surface itself, through _build_args
# --------------------------------------------------------------------------------------


def _mcp_args(root: Path, *, respect_pyproject: bool = True) -> argparse.Namespace:
    """Whatever the MCP surface really hands to the pipeline for ``root``."""
    service = CodeCloneMCPService(history_limit=4)
    return service._build_args(
        root_path=root,
        request=MCPAnalysisRequest(respect_pyproject=respect_pyproject),
    )


def test_mcp_surface_autodetects_source_roots(tmp_path: Path) -> None:
    """The resolver runs on MCP, and it runs with the repository root.

    ``source_roots`` decides the import mount, so the same file is
    ``src.pkg.mod`` under an unset root and ``pkg.mod`` under the autodetected
    one — a different module identity, and different finding ids, for one file.
    """
    args = _mcp_args(_repository_with_authority(tmp_path))

    assert getattr(args, "source_roots", None) == ("src",)


def test_mcp_surface_delivers_the_authority_lane_inputs(tmp_path: Path) -> None:
    """Declared, delivered, and present on the namespace the pipeline reads."""
    args = _mcp_args(_repository_with_authority(tmp_path))

    assert getattr(args, "semantic_authority", None) is True
    assert getattr(args, "fail_on_authority_violation", None) is True


def _repository_enabling_only_the_authority_lane(root: Path, *, enabled: bool) -> Path:
    """A repository whose ONLY authority input is ``semantic_authority``.

    Deliberately one input, not three. ``_build_authority_result`` enables the
    lane on any of ``semantic_authority``, ``fail_on_authority_violation`` or a
    non-empty registry, so a fixture carrying two of them lets one mask the loss
    of the other: withholding a single key then leaves this test green.
    """
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    body = "[tool.codeclone]\n"
    if enabled:
        body += "semantic_authority = true\n"
    (root / "pyproject.toml").write_text(body, encoding="utf-8")
    return root


def _mcp_metrics_summary(root: Path) -> object:
    """Whatever the MCP surface reports after really analysing ``root``."""
    service = CodeCloneMCPService(history_limit=2)
    service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    return _field(service.get_report_section(section="metrics"), "summary")


def test_mcp_surface_enables_the_authority_lane(tmp_path: Path) -> None:
    """Output edge: a delivered key that switches nothing on is not delivered.

    Proven end to end through the surface, not through the private predicate:
    the lane either ran and reported, or its whole block is absent from the
    metrics summary. A key sitting in a dictionary does not close that edge.
    """
    enabled = _repository_enabling_only_the_authority_lane(
        tmp_path / "enabled", enabled=True
    )
    plain = _repository_enabling_only_the_authority_lane(
        tmp_path / "plain", enabled=False
    )

    enabled_summary = _mcp_metrics_summary(enabled)
    plain_summary = _mcp_metrics_summary(plain)

    assert isinstance(enabled_summary, dict)
    assert isinstance(plain_summary, dict)

    # Which authority-shaped lanes the run reported, as a value rather than a
    # lookup: a missing lane must read as an absent name, not as a KeyError.
    assert sorted(key for key in enabled_summary if "authority" in key) == [
        "semantic_authority"
    ]
    assert sorted(key for key in plain_summary if "authority" in key) == []
    assert _field(_field(enabled_summary, "semantic_authority"), "enabled") is True


def test_mcp_surface_never_honours_report_writes_or_baseline_updates(
    tmp_path: Path,
) -> None:
    """The guard, at the surface: the withheld keys must not arrive here.

    Distinct from the literal-set test above: that one reds on the declaration,
    this one reds on what the server would actually do with the repository's
    configuration.
    """
    args = _mcp_args(_repository_with_authority(tmp_path))

    assert args.html_out is None
    assert args.update_baseline is False


def test_request_overrides_beat_repository_configuration(tmp_path: Path) -> None:
    """Order is part of the contract: an explicit request field still wins.

    Repository configuration is delivered first and the request's own fields are
    applied after it. Reversing that would let a repository override the caller.
    """
    root = _repository_with_authority(tmp_path)
    service = CodeCloneMCPService(history_limit=4)

    args = service._build_args(
        root_path=root,
        request=MCPAnalysisRequest(
            respect_pyproject=True,
            min_loc=7,
            baseline_path="request-baseline.json",
        ),
    )

    assert args.min_loc == 7
    assert str(args.baseline).endswith("request-baseline.json")


def test_declined_surface_delivers_only_the_two_identity_keys(tmp_path: Path) -> None:
    """``respect_pyproject=false`` delivers the identity keys and nothing else.

    The guarantee is a whitelist, so it does not depend on the declared universe
    being complete: an unrecognised nested table cannot leak through it.
    """
    root = _repository_with_authority(tmp_path)

    args = _mcp_args(root, respect_pyproject=False)

    assert args.baseline_scope_id == DECLARED_SCOPE_ID
    assert args.min_loc == 10
    assert getattr(args, "semantic_authority", None) is None
    assert getattr(args, "memory", None) is None
    assert str(args.baseline).endswith("codeclone.baseline.json")


def test_declined_surface_still_autodetects_source_roots(tmp_path: Path) -> None:
    """Autodetection is the resolver's default, not repository configuration.

    Declining the repository's configuration must not also change the universe
    the run analyses: both MCP surfaces mount the same autodetected source root,
    so their module identities stay comparable.
    """
    args = _mcp_args(_repository_with_authority(tmp_path), respect_pyproject=False)

    assert getattr(args, "source_roots", None) == ("src",)


# --------------------------------------------------------------------------------------
# Layer 3: the CLI memory-analysis delivery site
# --------------------------------------------------------------------------------------


def test_memory_analysis_mounts_the_autodetected_source_root(tmp_path: Path) -> None:
    """The third delivery site passes the root, or it mounts the wrong tree.

    ``codeclone memory init`` runs its own analysis. Without the root the
    resolver cannot autodetect, so this site mounted ``.`` while the main CLI
    mounted ``src`` for the same repository — one repository, two module
    identities, two sets of finding ids.
    """
    root = (tmp_path / "repo").resolve()
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "pkg" / "mod.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8"
    )

    document = run_memory_analysis_report(root_path=root)

    manifest = _field(_field(document, "source_facts"), "module_identity_manifest")
    mounts = _rows(_field(manifest, "import_mounts"))
    groups = _field(_field(document, "findings"), "groups")
    dead_code_groups = _rows(_field(_field(groups, "dead_code"), "groups"))

    # The finding id is what the user is shown; the mount is why it says that.
    assert _field(dead_code_groups[0], "id") == "dead_code:pkg.mod:f"
    assert [_field(mount, "path") for mount in mounts] == ["src"]


def _repository_setting_min_loc(root: Path, value: int) -> Path:
    """A repository whose only configured key is one the report echoes back."""
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "pkg" / "mod.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        f"[tool.codeclone]\nmin_loc = {value}\n", encoding="utf-8"
    )
    return root


def test_memory_analysis_delivers_repository_configuration_through_the_door(
    tmp_path: Path,
) -> None:
    """CLI_MEMORY honours the repository, and it does so through its declaration.

    This is the reachability half of the CLI_MEMORY declaration. The surface
    read the loader and the resolver directly, so its declaration decided
    nothing: a withholding added for CLI_MEMORY was silently not applied, and
    no test could tell, because with no withholdings declared the two paths
    delivered the same values. Withhold ``min_loc`` from CLI_MEMORY and this
    assertion must move -- that is what proves an input reaches the door.
    """
    root = _repository_setting_min_loc((tmp_path / "repo").resolve(), 33)

    document = run_memory_analysis_report(root_path=root)

    profile = _field(_field(document, "meta"), "analysis_profile")

    assert _field(profile, "min_loc") == 33


def test_the_cli_keeps_an_explicit_flag_against_repository_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opposite boundary: the terminal surface must not over-deliver.

    ``CLI_MEMORY`` failing to honour the repository and the CLI honouring it
    too much are different defects. The CLI passes its own ``explicit_cli_dests``
    precisely so a value typed on the command line survives; routing it through
    this door would supply an empty set and let ``pyproject.toml`` win, which
    no projection test can see.
    """
    root = _repository_setting_min_loc((tmp_path / "repo").resolve(), 33)
    report_path = tmp_path / "report.json"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codeclone",
            str(root),
            "--min-loc",
            "7",
            "--json",
            str(report_path),
            "--quiet",
            "--no-progress",
        ],
    )
    cli_workflow.main()

    document = json.loads(report_path.read_text(encoding="utf-8"))
    profile = _field(_field(document, "meta"), "analysis_profile")

    assert _field(profile, "min_loc") == 7

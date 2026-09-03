# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``from x import *`` binds what the target says, and the wire says so.

The measured class: a package ``__init__`` that re-exports through a wildcard
carried live public API to its users while the analyzer, seeing no named
binding, asserted that API dead with high confidence. RULING 2026-09-01 moved
the export chain out of liveness and into external reachability: a symbol the
wildcard carries to a public module is REACHABLE, and with no internal evidence
it is ``unresolved`` under the open world - never dead, never silently live.

The targets here are PRIVATE modules on purpose. A public module exposes its
own public names by construction, so a wildcard into it would prove nothing;
only a private target lets the wildcard edge be the sole construct that
decides, which is what makes every pin below a statement about the binding:

* a name the target's ``__all__`` rule binds is carried, and it and its
  public methods are unresolved, not dead - the re-exporter's ``__all__``
  declares, it does not use (liveness policy v4);
* a name the target's ``__all__`` omits is not carried, and stays dead;
* an underscore name is never carried, whoever imports it;
* the chain continues through wildcard edges and through what a reached
  module imports by name, and it stops where nothing public carries it;
* a wildcard with no target ``__all__`` binds MORE than the named spelling
  of the same import, and the difference is reported as unresolved.

The pins are stated as rules over qualnames, never as counts: the seventeen
of the original ``httpx`` measurement was a property of one version.
"""

from __future__ import annotations

from pathlib import Path

from tests._liveness_report_helpers import (
    dead_code_family,
    dead_qualnames,
    live_root_reason_by_qualname,
    unresolved_by_qualname,
)

#: Baseline update and gating both require a stable canonical scope id.
_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f39"

_IMPL_SOURCE = """
class StarBoundWidget:
    def render_panel(self) -> str:
        return "panel"


class UnexportedWidget:
    def render_hidden(self) -> str:
        return "hidden"


def star_bound_helper() -> str:
    return "helper"


def unexported_helper() -> str:
    return "unexported"
"""

#: The measured class: the re-exporting ``__init__`` carries the wildcard and
#: an ``__all__`` naming part of what it bound. The target has no ``__all__``
#: of its own, so by the language every public name of the target is bound
#: into ``pkg`` - the re-exporter's ``__all__`` narrows ``from pkg import *``
#: downstream, not what ``pkg`` holds.
_STAR_TREE = {
    "pkg/__init__.py": """
from ._impl import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_impl.py": _IMPL_SOURCE,
}

#: The same tree with the wildcard spelled out. A named import binds exactly
#: the names it lists, so what the wildcard bound beyond them stays private.
_NAMED_TREE = {
    "pkg/__init__.py": """
from ._impl import StarBoundWidget, star_bound_helper

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_impl.py": _IMPL_SOURCE,
}

#: The ``httpx`` shape exactly: the target declares ``__all__`` too, so the
#: wildcard binds one name and the named spelling of that import agrees.
_STAR_TARGET_ALL_TREE = {
    "pkg/__init__.py": """
from ._impl import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/_impl.py": '__all__ = ["StarBoundWidget"]\n' + _IMPL_SOURCE,
}

_NAMED_TARGET_ALL_TREE = {
    "pkg/__init__.py": """
from ._impl import StarBoundWidget

__all__ = ["StarBoundWidget"]
""",
    "pkg/_impl.py": '__all__ = ["StarBoundWidget"]\n' + _IMPL_SOURCE,
}

#: No wildcard anywhere and nothing re-exports the private module: its own
#: ``__all__`` declares exports to nobody, so the class and its public method
#: are dead under any world - a declaration is not a use.
_NO_WILDCARD_TREE = {
    "pkg/__init__.py": "",
    "pkg/_impl.py": """
__all__ = ["LocalOnlyWidget"]


class LocalOnlyWidget:
    def render_local(self) -> str:
        return "local"
""",
}

#: A private class of the wildcard target, held live by a named import from a
#: sibling module. ``import *`` never binds an underscore name, and neither
#: does anything else.
_PRIVATE_TARGET_TREE = {
    "pkg/__init__.py": """
from ._impl import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/_impl.py": """
class StarBoundWidget:
    def render_panel(self) -> str:
        return "panel"


class _HiddenWidget:
    def render_secret(self) -> str:
        return "secret"
""",
    "pkg/consumer.py": """
from ._impl import _HiddenWidget


def take_hidden() -> object:
    return _HiddenWidget()
""",
}

#: The chain passes through a plain PRIVATE module by wildcard at both hops.
_CHAINED_STAR_TREE = {
    "pkg/__init__.py": """
from ._api import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_api.py": """
from ._impl import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_impl.py": _IMPL_SOURCE,
}

#: The same chain with a NAMED middle hop: the wildcard sits at the package
#: boundary, the reached module re-exports by name.
_CHAINED_NAMED_MIDDLE_TREE = {
    "pkg/__init__.py": """
from ._api import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_api.py": """
from ._impl import StarBoundWidget, star_bound_helper

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_impl.py": _IMPL_SOURCE,
}

#: Nothing public carries ``_api`` outward, so its wildcard exposes nothing.
_UNANCHORED_CHAIN_TREE = {
    "pkg/__init__.py": "",
    "pkg/_api.py": """
from ._impl import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_impl.py": _IMPL_SOURCE,
}

#: A PUBLIC plain module's wildcard is a public path by the language:
#: ``pkg.api.StarBoundWidget`` exists, whatever PEP 8 says about facades.
_PUBLIC_PLAIN_STAR_TREE = {
    "pkg/__init__.py": "",
    "pkg/api.py": """
from ._impl import *  # noqa: F403
""",
    "pkg/_impl.py": _IMPL_SOURCE,
}

#: Only a wildcard edge, or what a wildcard-reached module imports by name,
#: extends the chain. ``_impl`` is reached BY NAME, so what it imports goes
#: no further: ``pkg.DeepWidget`` does not exist at runtime.
_NAMED_EDGE_CEILING_TREE = {
    "pkg/__init__.py": """
from ._api import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/_api.py": """
from ._impl import StarBoundWidget

__all__ = ["StarBoundWidget"]
""",
    "pkg/_impl.py": """
from ._deep import DeepWidget


class StarBoundWidget:
    def render_panel(self) -> str:
        return DeepWidget().identify()
""",
    "pkg/_deep.py": """
class DeepWidget:
    def identify(self) -> str:
        return "deep"

    def render_deep(self) -> str:
        return "never reached from the package"
""",
}

#: Measured on ``qutip``: a reached module's private import is not an export.
_PRIVATE_IMPORT_ON_THE_CHAIN_TREE = {
    "pkg/__init__.py": """
from ._api import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/_api.py": """
from ._private import _Hidden
from ._impl import StarBoundWidget

__all__ = ["StarBoundWidget"]


def build_hidden() -> _Hidden:
    return _Hidden()
""",
    "pkg/_impl.py": """
class StarBoundWidget:
    def render_panel(self) -> str:
        return "panel"
""",
    "pkg/_private.py": """
class _Hidden:
    def secret_method(self) -> str:
        return "secret"
""",
}

#: Two re-exporters, one target: the walk converges rather than repeating.
_DIAMOND_CHAIN_TREE = {
    "pkg/__init__.py": """
from ._left import *  # noqa: F403
from ._right import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/_left.py": """
from ._impl import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/_right.py": """
from ._impl import *  # noqa: F403

__all__ = ["star_bound_helper"]
""",
    "pkg/_impl.py": _IMPL_SOURCE,
}

#: Mutual ``import *`` - legal Python, present in real packages, and the only
#: input here on which the walk's visited set is what ends the walk.
_CYCLIC_CHAIN_TREE = {
    "pkg/__init__.py": """
from ._a import *  # noqa: F403

__all__ = ["CycleWidget"]
""",
    "pkg/_a.py": """
from ._b import *  # noqa: F403

__all__ = ["CycleWidget"]
""",
    "pkg/_b.py": """
from ._a import *  # noqa: F403

__all__ = ["CycleWidget"]


class CycleWidget:
    def render_cycle(self) -> str:
        return "cycle"


class OrphanWidget:
    def never_called(self) -> int:
        return 1
""",
}

#: The binding fact is the TARGET's: ``__all__`` in the target decides what
#: the wildcard carries, whatever the re-exporter lists.
_TARGET_ALL_OMITS_TREE = {
    "pkg/__init__.py": """
from ._impl import *  # noqa: F403
""",
    "pkg/_impl.py": """
__all__ = ["StarBoundWidget"]


class StarBoundWidget:
    def render_panel(self) -> str:
        return "panel"


class OmittedWidget:
    def render_omitted(self) -> str:
        return "omitted"
""",
}

_TARGET_ALL_LISTS_TREE = {
    "pkg/__init__.py": _TARGET_ALL_OMITS_TREE["pkg/__init__.py"],
    "pkg/_impl.py": _TARGET_ALL_OMITS_TREE["pkg/_impl.py"].replace(
        '__all__ = ["StarBoundWidget"]',
        '__all__ = ["StarBoundWidget", "OmittedWidget"]',
    ),
}


def _lanes(
    tmp_path: Path,
    tree: dict[str, str],
    name: str,
    *,
    expect_warm_cache: bool = False,
) -> tuple[frozenset[str], dict[str, str]]:
    """Both lanes of one generated tree: the dead set, and unresolved -> witness."""

    family = dead_code_family(
        tmp_path,
        tree,
        name,
        scope_id=_SCOPE_ID,
        expect_warm_cache=expect_warm_cache,
    )
    # The export chain is reachability evidence now; a live root spelled
    # ``export_root`` would be the old lie in the old place.
    assert "export_root" not in set(live_root_reason_by_qualname(family).values())
    return dead_qualnames(family), {
        qualname: str(row["witness"])
        for qualname, row in unresolved_by_qualname(family).items()
    }


def test_wildcard_reexport_carries_the_bound_names_as_unresolved(
    tmp_path: Path,
) -> None:
    """The re-exporter's ``__all__`` declares; it does not use. Every name the
    wildcard carries to ``pkg`` - the class, the helper and the class's public
    method alike - has a public path and no internal evidence, so all of them
    are unresolved rows through the same witness, and none is dead."""

    dead, unresolved = _lanes(tmp_path, _STAR_TREE, "star")

    carried = {
        "pkg._impl:StarBoundWidget",
        "pkg._impl:StarBoundWidget.render_panel",
        "pkg._impl:star_bound_helper",
    }
    assert carried.isdisjoint(dead)
    assert {
        qualname: unresolved.get(qualname) for qualname in carried
    } == dict.fromkeys(carried, "star_reexport:pkg")


def test_a_wildcard_with_no_target_all_binds_what_the_reexporter_omits(
    tmp_path: Path,
) -> None:
    """``pkg.UnexportedWidget`` exists at runtime: the re-exporter's ``__all__``
    narrows ``from pkg import *``, not the names ``pkg`` holds."""

    dead, unresolved = _lanes(tmp_path, _STAR_TREE, "star-omits")

    for qualname in (
        "pkg._impl:UnexportedWidget",
        "pkg._impl:UnexportedWidget.render_hidden",
        "pkg._impl:unexported_helper",
    ):
        assert qualname not in dead, qualname
        assert unresolved[qualname] == "star_reexport:pkg", qualname


def test_a_named_reexport_leaves_the_unnamed_siblings_dead(tmp_path: Path) -> None:
    dead, unresolved = _lanes(tmp_path, _NAMED_TREE, "named")

    assert unresolved["pkg._impl:StarBoundWidget.render_panel"] == (
        "package_reexport:pkg"
    )
    assert "pkg._impl:UnexportedWidget" in dead
    assert "pkg._impl:UnexportedWidget.render_hidden" in dead
    assert "pkg._impl:unexported_helper" in dead
    assert not {name for name in unresolved if "nexported" in name}


def test_wildcard_and_named_reexport_agree_when_the_target_declares_all(
    tmp_path: Path,
) -> None:
    """The httpx shape: with a target ``__all__`` the two spellings bind the same
    names, so both lanes must agree - the wildcard only changes the witness."""

    star_dead, star_unresolved = _lanes(tmp_path, _STAR_TARGET_ALL_TREE, "star-all")
    named_dead, named_unresolved = _lanes(tmp_path, _NAMED_TARGET_ALL_TREE, "named-all")

    assert star_dead == named_dead
    assert set(star_unresolved) == set(named_unresolved)
    assert "pkg._impl:UnexportedWidget.render_hidden" in star_dead
    assert star_unresolved["pkg._impl:StarBoundWidget.render_panel"] == (
        "star_reexport:pkg"
    )
    assert named_unresolved["pkg._impl:StarBoundWidget.render_panel"] == (
        "package_reexport:pkg"
    )


def test_wildcard_reexport_never_binds_a_private_target_class(tmp_path: Path) -> None:
    dead, unresolved = _lanes(tmp_path, _PRIVATE_TARGET_TREE, "private-target")

    assert unresolved["pkg._impl:StarBoundWidget.render_panel"] == "star_reexport:pkg"
    assert "pkg._impl:_HiddenWidget.render_secret" in dead
    assert "pkg._impl:_HiddenWidget.render_secret" not in unresolved


def test_a_private_module_nothing_reexports_is_dead_with_its_own_all(
    tmp_path: Path,
) -> None:
    """The 30-of-104 class: a private module's ``__all__`` binds names for a
    wildcard nobody writes. It declares to nobody and uses nothing, so the
    class and its public method are dead, and nothing is unresolved."""

    dead, unresolved = _lanes(tmp_path, _NO_WILDCARD_TREE, "no-wildcard")

    assert dead == {
        "pkg._impl:LocalOnlyWidget",
        "pkg._impl:LocalOnlyWidget.render_local",
    }
    assert unresolved == {}


def test_chained_reexport_through_a_private_module_keeps_the_path(
    tmp_path: Path,
) -> None:
    for name, tree in (
        ("chain-star", _CHAINED_STAR_TREE),
        ("chain-named-middle", _CHAINED_NAMED_MIDDLE_TREE),
    ):
        dead, unresolved = _lanes(tmp_path, tree, name)
        assert "pkg._impl:StarBoundWidget" not in dead, name
        assert "pkg._impl:StarBoundWidget.render_panel" not in dead, name
        assert unresolved["pkg._impl:StarBoundWidget.render_panel"].startswith(
            "star_reexport:"
        ), name


def test_chained_reexport_still_reports_what_no_hop_carries(tmp_path: Path) -> None:
    """``_api`` imports two names from ``_impl``; ``UnexportedWidget`` is never
    bound anywhere on the chain, so no public path reaches it."""

    dead, unresolved = _lanes(tmp_path, _CHAINED_NAMED_MIDDLE_TREE, "chain-omits")

    assert "pkg._impl:UnexportedWidget" in dead
    assert "pkg._impl:UnexportedWidget.render_hidden" in dead
    assert "pkg._impl:unexported_helper" in dead
    assert "pkg._impl:UnexportedWidget.render_hidden" not in unresolved


def test_reexport_chain_is_anchored_at_the_public_frontier(tmp_path: Path) -> None:
    """``_api`` stars ``_impl`` and lists two names, but nothing public carries
    ``_api`` outward: the wildcard binds into a namespace no caller can spell
    and the listing declares to nobody. Dead, all of it, under the open world
    too - the binding and the declaration are facts about ``_api``'s
    namespace, and neither is a use."""

    dead, unresolved = _lanes(tmp_path, _UNANCHORED_CHAIN_TREE, "unanchored")

    assert {
        "pkg._impl:StarBoundWidget",
        "pkg._impl:StarBoundWidget.render_panel",
        "pkg._impl:star_bound_helper",
    } <= dead
    assert unresolved == {}


def test_a_public_plain_module_wildcard_is_a_public_path(tmp_path: Path) -> None:
    dead, unresolved = _lanes(tmp_path, _PUBLIC_PLAIN_STAR_TREE, "public-plain")

    assert "pkg._impl:StarBoundWidget.render_panel" not in dead
    assert unresolved["pkg._impl:StarBoundWidget.render_panel"] == (
        "star_reexport:pkg.api"
    )


def test_reexport_chain_walks_wildcard_edges_only(tmp_path: Path) -> None:
    dead, unresolved = _lanes(tmp_path, _NAMED_EDGE_CEILING_TREE, "named-ceiling")

    assert unresolved["pkg._impl:StarBoundWidget.render_panel"] == (
        "star_reexport:pkg._api"
    )
    assert "pkg._deep:DeepWidget.render_deep" in dead
    assert "pkg._deep:DeepWidget.render_deep" not in unresolved


def test_reached_module_does_not_reexport_its_private_imports(
    tmp_path: Path,
) -> None:
    dead, unresolved = _lanes(tmp_path, _PRIVATE_IMPORT_ON_THE_CHAIN_TREE, "qutip")

    assert unresolved["pkg._impl:StarBoundWidget.render_panel"] == (
        "star_reexport:pkg._api"
    )
    assert "pkg._private:_Hidden.secret_method" in dead


def test_reexport_chain_converges_on_a_shared_target(tmp_path: Path) -> None:
    dead, unresolved = _lanes(tmp_path, _DIAMOND_CHAIN_TREE, "diamond")

    assert "pkg._impl:StarBoundWidget.render_panel" not in dead
    assert unresolved["pkg._impl:StarBoundWidget.render_panel"].startswith(
        "star_reexport:pkg._"
    )


def test_reexport_chain_terminates_on_a_mutual_wildcard_cycle(
    tmp_path: Path,
) -> None:
    dead, unresolved = _lanes(tmp_path, _CYCLIC_CHAIN_TREE, "cycle")

    assert "pkg._b:CycleWidget" not in dead
    assert unresolved["pkg._b:CycleWidget.render_cycle"] == "star_reexport:pkg._a"
    # Not in _b's __all__, so no wildcard ever binds it: dead in a private
    # module, and not a row in the sibling lane.
    assert "pkg._b:OrphanWidget" in dead
    assert "pkg._b:OrphanWidget.never_called" in dead
    assert "pkg._b:OrphanWidget.never_called" not in unresolved


def test_wildcard_does_not_bind_a_name_the_target_all_omits(tmp_path: Path) -> None:
    dead, unresolved = _lanes(tmp_path, _TARGET_ALL_OMITS_TREE, "target-omits")

    assert unresolved["pkg._impl:StarBoundWidget.render_panel"] == "star_reexport:pkg"
    assert "pkg._impl:OmittedWidget" in dead
    assert "pkg._impl:OmittedWidget.render_omitted" in dead
    assert "pkg._impl:OmittedWidget.render_omitted" not in unresolved


def test_wildcard_binds_the_name_the_target_all_lists(tmp_path: Path) -> None:
    dead, unresolved = _lanes(tmp_path, _TARGET_ALL_LISTS_TREE, "target-lists")

    assert "pkg._impl:OmittedWidget" not in dead
    assert "pkg._impl:OmittedWidget.render_omitted" not in dead
    assert unresolved["pkg._impl:OmittedWidget.render_omitted"] == "star_reexport:pkg"


def test_wildcard_binding_survives_a_warm_cache(tmp_path: Path) -> None:
    """The binding fact rides the cache with the candidate, and reachability
    reads only wired facts, so a warm run utters exactly the cold lanes."""

    cold = _lanes(tmp_path, _TARGET_ALL_OMITS_TREE, "warm")
    warm = _lanes(tmp_path, _TARGET_ALL_OMITS_TREE, "warm", expect_warm_cache=True)

    assert "pkg._impl:OmittedWidget.render_omitted" in cold[0]
    assert cold[1]["pkg._impl:StarBoundWidget.render_panel"] == "star_reexport:pkg"
    assert warm == cold

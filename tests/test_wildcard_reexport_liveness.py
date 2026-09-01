# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``from x import *`` loses the binding, so a live public API reads as dead.

A package ``__init__`` that re-exports through a wildcard and then names those
symbols in its own ``__all__`` had no resolvable binding at all: the walk skips
every alias whose name is ``*``, so nothing rooted the re-exported symbol and
the export chain never reached the public methods of a re-exported class. The
measured consequence was not a missed finding but the opposite - a
high-confidence assertion that live public API is dead. On ``httpx`` the
wildcard spelling produced seventeen such findings where the equivalent named
imports produced none.

These pins hold the recovered binding at both layers, in both directions:

* an ``__all__`` entry with no local definition and no named import resolves
  through the wildcard edge (the target may carry no ``__all__`` of its own);
* the export chain reaches the public methods of a class the wildcard
  re-exports;
* a name the re-exporting ``__all__`` does NOT list stays dead, and a private
  class of the target stays dead even when the project holds it live - the
  wildcard never binds an underscore name;
* the wildcard spelling and its named equivalent produce the SAME dead set;
* a package with no wildcard re-export is untouched by this rule.

The pins are stated as rules over qualnames, never as counts: the seventeen is
a property of one ``httpx`` version, not of the defect.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# The CLI is SPAWNED, never imported: these pins live at the report layer and
# importing the CLI surface would make the module a ring-4 test reaching into
# ring-2 internals. Same pattern as the dependency-cycle policy suite.
_CLI_ENTRY = "from codeclone.surfaces.cli.workflow import main; main()"

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

#: The measured class: the re-exporting ``__init__`` carries BOTH the wildcard
#: and the ``__all__`` naming what the wildcard bound. The target module has no
#: ``__all__`` of its own, so the re-exporting ``__all__`` is the only static
#: export evidence in the tree.
_STAR_TREE = {
    "pkg/__init__.py": """
from .impl import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/impl.py": _IMPL_SOURCE,
}

#: Byte-for-byte the same tree with the wildcard spelled out. Whatever the
#: wildcard binds, this binds by name; the two dead sets must agree.
_NAMED_TREE = {
    "pkg/__init__.py": """
from .impl import StarBoundWidget, star_bound_helper

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/impl.py": _IMPL_SOURCE,
}

#: The ``httpx`` shape exactly: the target module also declares ``__all__``, so
#: the class was already live before this rule and ONLY its public methods were
#: falsely dead.
_STAR_TARGET_ALL_TREE = {
    "pkg/__init__.py": """
from .impl import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/impl.py": '__all__ = ["StarBoundWidget"]\n' + _IMPL_SOURCE,
}

#: No wildcard anywhere. The boundary of this wave: a class the project holds
#: live through its own ``__all__``, which no package ``__init__`` re-exports,
#: keeps its dead public method.
_NO_WILDCARD_TREE = {
    "pkg/__init__.py": "",
    "pkg/impl.py": """
__all__ = ["LocalOnlyWidget"]


class LocalOnlyWidget:
    def render_local(self) -> str:
        return "local"
""",
}

#: A private class of the wildcard target, held live by a named import from a
#: sibling module. ``import *`` never binds an underscore name, so the export
#: chain must not reach its public method.
_PRIVATE_TARGET_TREE = {
    "pkg/__init__.py": """
from .impl import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/impl.py": """
class StarBoundWidget:
    def render_panel(self) -> str:
        return "panel"


class _HiddenWidget:
    def render_secret(self) -> str:
        return "secret"
""",
    "pkg/consumer.py": """
from .impl import _HiddenWidget


def take_hidden() -> object:
    return _HiddenWidget()
""",
}


#: The residual class of the SAME defect: the chain passes through a plain
#: module. ``pkg`` re-exports ``pkg.api`` through ``import *`` + its own
#: ``__all__``, and ``pkg.api`` re-exports ``pkg.impl`` the same way. Both hops
#: carry the ``__all__`` this wave already treats as authoritative, so the class
#: itself resolves live - only the export chain stopped at the first hop that
#: was not a package ``__init__``, leaving the public method of a live
#: re-exported class asserted dead with HIGH confidence.
_CHAINED_STAR_TREE = {
    "pkg/__init__.py": """
from .api import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/api.py": """
from .impl import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/impl.py": _IMPL_SOURCE,
}

#: The same chain with a NAMED middle hop - the spelling a package facade most
#: often carries. The wildcard sits only at the package boundary, so the middle
#: module is reached wholesale and then re-exports by name.
_CHAINED_NAMED_MIDDLE_TREE = {
    "pkg/__init__.py": """
from .api import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/api.py": """
from .impl import StarBoundWidget, star_bound_helper

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/impl.py": _IMPL_SOURCE,
}

#: The ceiling of the chain rule, and the input that proves its origin guard is
#: reachable. ``pkg.api`` re-exports ``pkg.impl`` exactly as above, but NO
#: package ``__init__`` re-exports ``pkg.api``, so nothing carries those names
#: to a package boundary and the public method stays dead. A rule that followed
#: wildcard edges from anywhere - rather than from a package outward - would
#: move this verdict.
_UNANCHORED_CHAIN_TREE = {
    "pkg/__init__.py": "",
    "pkg/api.py": """
from .impl import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/impl.py": _IMPL_SOURCE,
}


#: The second ceiling: only a WILDCARD edge extends the chain. ``pkg.api``
#: reaches ``pkg.impl`` by NAME, so ``pkg.impl`` is not re-exported wholesale
#: and what IT imports by name never reaches the package. ``DeepWidget`` is
#: held live by that internal use, but ``pkg.DeepWidget`` does not exist at
#: runtime, so its public method is genuinely unreachable. A chain that walked
#: named edges as well would root it.
_NAMED_EDGE_CEILING_TREE = {
    "pkg/__init__.py": """
from .api import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/api.py": """
from .impl import StarBoundWidget

__all__ = ["StarBoundWidget"]
""",
    "pkg/impl.py": """
from .deep import DeepWidget


class StarBoundWidget:
    def render_panel(self) -> str:
        return DeepWidget().identify()
""",
    "pkg/deep.py": """
class DeepWidget:
    def identify(self) -> str:
        return "deep"

    def render_deep(self) -> str:
        return "never reached from the package"
""",
}


#: The third ceiling, measured on ``qutip``: a module the chain REACHED carries
#: only what put it on the chain. ``pkg.api`` is reached by a wildcard, which
#: skips underscore names, so its private named import is not an export - while
#: a package ``__init__`` doing the same import really does bind ``pkg._Hidden``
#: and keeps its pre-existing treatment.
_PRIVATE_IMPORT_ON_THE_CHAIN_TREE = {
    "pkg/__init__.py": """
from .api import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/api.py": """
from ._private import _Hidden
from .impl import StarBoundWidget

__all__ = ["StarBoundWidget"]


def build_hidden() -> _Hidden:
    return _Hidden()
""",
    "pkg/impl.py": """
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


#: Two re-exporters, one target: the chain must converge rather than walk the
#: same module twice. A diamond is the ordinary shape of a package facade, and
#: it is also the input that reaches the "already on the chain" arm of the walk.
_DIAMOND_CHAIN_TREE = {
    "pkg/__init__.py": """
from .left import *  # noqa: F403
from .right import *  # noqa: F403

__all__ = ["StarBoundWidget", "star_bound_helper"]
""",
    "pkg/left.py": """
from .impl import *  # noqa: F403

__all__ = ["StarBoundWidget"]
""",
    "pkg/right.py": """
from .impl import *  # noqa: F403

__all__ = ["star_bound_helper"]
""",
    "pkg/impl.py": _IMPL_SOURCE,
}


def _write_tree(root: Path, tree: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, source in tree.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.lstrip(), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        encoding="utf-8",
    )
    return root


def _dead_qualnames(tmp_path: Path, tree: dict[str, str], name: str) -> frozenset[str]:
    """Dead-code qualnames of one generated tree, behind the witness chain.

    A count read without its witness is the benchmark defect this project
    already measured: with no metrics flag the run silently degrades to
    ``clones_only`` and EVERY family reads zero. So the producer, the mode and
    the family are asserted before a single finding is read.
    """

    project_root = _write_tree(tmp_path / name, tree)
    report_path = tmp_path / f"{name}-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CLI_ENTRY,
            str(project_root),
            "--baseline",
            str(tmp_path / f"{name}-baseline.json"),
            "--cache-path",
            str(tmp_path / f"{name}-cache.json"),
            "--json",
            str(report_path),
            "--no-skip-metrics",
            "--no-skip-dead-code",
            "--no-progress",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert report_path.exists(), completed.stdout + completed.stderr
    payload = json.loads(report_path.read_text("utf-8"))
    assert isinstance(payload, dict)
    meta = payload["meta"]
    assert isinstance(meta, dict)
    assert meta["analysis_mode"] == "full", meta["analysis_mode"]
    assert "dead_code" in meta["computed_metric_families"]
    family = payload["metrics"]["families"]["dead_code"]
    assert isinstance(family, dict)
    return frozenset(str(item["qualname"]) for item in family["items"])


def test_wildcard_reexport_resolves_the_bindings_its_all_names(
    tmp_path: Path,
) -> None:
    """The core recovery: ``__all__`` plus a wildcard edge IS a binding.

    Neither symbol is defined in the re-exporting module and neither is
    imported by name, so before the recovery nothing rooted them at all.
    """

    dead = _dead_qualnames(tmp_path, _STAR_TREE, "star")

    assert "pkg.impl:StarBoundWidget" not in dead
    assert "pkg.impl:star_bound_helper" not in dead


def test_wildcard_reexport_carries_the_export_chain_to_public_methods(
    tmp_path: Path,
) -> None:
    """The measured ``httpx`` defect, stated as a rule rather than a count.

    No public method of a class a package re-exports through
    ``import *`` + ``__all__`` may be called dead - that is the
    high-confidence assertion the maintainer ruled unacceptable.
    """

    for tree, name in ((_STAR_TREE, "star"), (_STAR_TARGET_ALL_TREE, "startarget")):
        dead = _dead_qualnames(tmp_path, tree, name)
        assert "pkg.impl:StarBoundWidget.render_panel" not in dead, name


def test_wildcard_reexport_does_not_revive_what_all_omits(tmp_path: Path) -> None:
    """The opposite ditch: the recovery is a binding, not a blanket root."""

    dead = _dead_qualnames(tmp_path, _STAR_TREE, "star")

    assert "pkg.impl:unexported_helper" in dead
    assert "pkg.impl:UnexportedWidget" in dead
    assert "pkg.impl:UnexportedWidget.render_hidden" in dead


def test_wildcard_reexport_never_binds_a_private_target_class(
    tmp_path: Path,
) -> None:
    """``import *`` skips underscore names, so the chain must skip them too.

    The class is deliberately held live by a named import from a sibling
    module: without the underscore guard the export chain would reach it, so
    this input proves the guard is reachable rather than decorative.
    """

    dead = _dead_qualnames(tmp_path, _PRIVATE_TARGET_TREE, "private")

    assert "pkg.impl:StarBoundWidget.render_panel" not in dead
    assert "pkg.impl:_HiddenWidget.render_secret" in dead


def test_wildcard_and_named_reexport_agree_on_liveness(tmp_path: Path) -> None:
    """Equivalent spellings, one verdict.

    The wildcard was measured to be strictly WEAKER than the named import it
    stands for. Equality in both directions is the acceptance condition, so
    the assertion is set equality, not containment.
    """

    star = _dead_qualnames(tmp_path, _STAR_TREE, "star")
    named = _dead_qualnames(tmp_path, _NAMED_TREE, "named")

    assert star == named


def test_package_without_wildcard_keeps_its_dead_public_method(
    tmp_path: Path,
) -> None:
    """The frozen boundary of this wave.

    ``LocalOnlyWidget`` is live through its module's own ``__all__``, and no
    package ``__init__`` re-exports it. A rule that rooted the public methods
    of every live class - rather than of the classes a wildcard re-exports -
    would move this verdict, and this repository's own modules with it.
    """

    dead = _dead_qualnames(tmp_path, _NO_WILDCARD_TREE, "nowildcard")

    assert "pkg.impl:LocalOnlyWidget" not in dead
    assert "pkg.impl:LocalOnlyWidget.render_local" in dead


def test_chained_reexport_through_a_plain_module_keeps_public_methods_live(
    tmp_path: Path,
) -> None:
    """The residual of the measured class, stated as a rule.

    The re-exporting hop being a package ``__init__`` rather than a plain
    module is a spelling, not a fact about the API: both chains bind
    ``pkg.StarBoundWidget`` at runtime. Deciding liveness by the spelling is
    what produced a high-confidence assertion that live public API is dead.
    """

    for tree, name in (
        (_CHAINED_STAR_TREE, "chainstar"),
        (_CHAINED_NAMED_MIDDLE_TREE, "chainnamed"),
    ):
        dead = _dead_qualnames(tmp_path, tree, name)

        assert "pkg.impl:StarBoundWidget" not in dead, name
        assert "pkg.impl:StarBoundWidget.render_panel" not in dead, name


def test_chained_reexport_still_reports_what_the_chain_omits(
    tmp_path: Path,
) -> None:
    """The opposite ditch of the same edit.

    Following the chain one hop further must not become "every symbol of every
    module the chain touches is live": the names the chain never carries stay
    dead, class, method and function alike.
    """

    for tree, name in (
        (_CHAINED_STAR_TREE, "chainstar"),
        (_CHAINED_NAMED_MIDDLE_TREE, "chainnamed"),
    ):
        dead = _dead_qualnames(tmp_path, tree, name)

        assert "pkg.impl:UnexportedWidget" in dead, name
        assert "pkg.impl:UnexportedWidget.render_hidden" in dead, name
        assert "pkg.impl:unexported_helper" in dead, name


def test_reexport_chain_is_anchored_at_the_package_boundary(
    tmp_path: Path,
) -> None:
    """The origin guard, proven reachable by an input that trips it.

    ``pkg.api`` re-exports the class exactly as the chained trees do, and its
    own ``__all__`` still holds the class live - but no package ``__init__``
    carries those names outward, so the public method is genuinely unreachable
    and must stay dead.
    """

    dead = _dead_qualnames(tmp_path, _UNANCHORED_CHAIN_TREE, "unanchored")

    assert "pkg.impl:StarBoundWidget" not in dead
    assert "pkg.impl:StarBoundWidget.render_panel" in dead


def test_reexport_chain_walks_wildcard_edges_only(tmp_path: Path) -> None:
    """The chain carries a NAMESPACE, and only ``import *`` carries one.

    A named import binds one name for the importing module's own use. Treating
    it as a chain hop would root what a module merely consumes, which is the
    "hundreds of new false positives" ditch this wave has to stay out of.
    """

    dead = _dead_qualnames(tmp_path, _NAMED_EDGE_CEILING_TREE, "namededge")

    assert "pkg.impl:StarBoundWidget.render_panel" not in dead
    assert "pkg.deep:DeepWidget.render_deep" in dead


def test_reached_module_does_not_reexport_its_private_imports(
    tmp_path: Path,
) -> None:
    """The ``qutip`` measurement, stated as a rule.

    ``_Hidden`` is live - ``pkg.api`` builds one - but ``pkg._Hidden`` does not
    exist, because the wildcard that put ``pkg.api`` on the chain never binds an
    underscore name. Rooting its methods would retire a true finding, which is
    the same error as the defect, pointed the other way.
    """

    dead = _dead_qualnames(tmp_path, _PRIVATE_IMPORT_ON_THE_CHAIN_TREE, "privchain")

    assert "pkg.impl:StarBoundWidget.render_panel" not in dead
    assert "pkg._private:_Hidden.secret_method" in dead


def test_reexport_chain_converges_on_a_shared_target(tmp_path: Path) -> None:
    """A diamond is one chain, not two, and it still reports what it omits."""

    dead = _dead_qualnames(tmp_path, _DIAMOND_CHAIN_TREE, "diamond")

    assert "pkg.impl:StarBoundWidget.render_panel" not in dead
    assert "pkg.impl:UnexportedWidget.render_hidden" in dead

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every production ``RunStore`` construction states whether it may create.

``RunStore(path)`` creates the store it is handed: it makes the parent
directory, opens sqlite, and writes eleven tables of schema before the first
statement runs.  That is correct for a publish and a falsehood for a read --
a lookup that materializes what it failed to find turns "no analysis was
published here" into "an empty analysis was published here", and every later
question is answered by the second sentence.  ``create=False`` refuses before
anything touches the filesystem, and the prohibition on the bare constructor
is what keeps a new call from re-acquiring the defect.

A prose prohibition is a deferred defect, so this is the executable form:

    existing legacy bare construction   exact frozen inventory
    new or changed writer               ``create=True`` required
    reader or probe                     ``create=False`` required
    new bare construction anywhere      FAIL

**This is not an allowlist of files.**  A file-level permission becomes a
semantic one the moment a function is added to a "known writer" module: the
accidental bare constructor inherits a jurisdiction it was never granted.
Permission here attaches to a specific call -- the enclosing qualified name
AND the number of bare constructions inside it -- so a second bare call in an
already-frozen function is a violation, and so is the same call moved into a
neighbour.

**The inventory is structural, not textual.**  ``grep "RunStore("`` is blind
by construction to ``from ...store import RunStore as _RS`` followed by
``_RS(path)``, and to ``store_module.RunStore(path)``.  Import bindings are
resolved per module, relative imports included, so the class is recognized
through every spelling that names it.

Exit path -- this ratchet is transitional and is meant to be deleted.  As the
frozen inventory reaches zero, the last bare construction is gone and the
prohibition stops needing a test: it becomes a property of the API itself,
either ``create`` declared with no default so every caller must answer, or a
split constructor pair (``RunStore.open_existing(path)`` /
``RunStore.create(path)``) where the wrong intent is not spellable.  At that
point this module is removed rather than left green forever; a ratchet whose
floor is zero and whose API cannot be violated is measuring nothing.  Until
then the inventory must SHRINK only deliberately -- exact equality is
asserted in both directions, so retiring a legacy callsite is a recorded
event and not a silent loosening.
"""

from __future__ import annotations

import ast
import re
import subprocess
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]

#: Every dotted spelling that names the run-store class.  ``codeclone.canonical``
#: re-exports it, so an import through the package is the same construction as
#: an import through the module.
_RUN_STORE_TARGETS: Final = frozenset(
    {
        "codeclone.canonical.store.RunStore",
        "codeclone.canonical.RunStore",
    }
)

_DEFINING_MODULE: Final = "codeclone.canonical.store"

#: Generated trees are not source; excluding them is not a jurisdiction over
#: any file a human wrote.
_GENERATED_DIRECTORY_NAMES: Final = frozenset(
    {"__pycache__", "build", "dist", "node_modules", ".egg-info"}
)

#: The textual witness the structural inventory is reconciled against.  It is
#: deliberately weaker: ``\b`` refuses ``CodeCloneMCPRunStore(``, which is a
#: different class, and it cannot see an aliased construction at all.
_TEXTUAL_WITNESS: Final = re.compile(r"\bRunStore\s*\(")

_INTENT_CREATE: Final = "create=True"
_INTENT_READ: Final = "create=False"
_INTENT_IMPLICIT: Final = "implicit-create"
_INTENT_UNDECIDABLE: Final = "undecidable"

#: The frozen inventory: one entry per enclosing callsite, valued by the
#: number of bare constructions permitted there.  Adding a second bare call to
#: a frozen function is a violation; so is the same call in a neighbouring
#: function of the same file.  Both directions are asserted, so this mapping
#: is the record of the ratchet's floor and not a place to file new debt.
_LEGACY_IMPLICIT_CREATE: Final[Mapping[tuple[str, str], int]] = {
    # The publish path: it is the writer that brings the store into
    # existence, so creating is its whole point.  It is frozen rather than
    # rewritten because changing a working writer is a separate decision from
    # forbidding new ones.
    ("codeclone/core/canonical_snapshot.py", "_publish_enabled"): 1,
}


@dataclass(frozen=True)
class _Construction:
    """One resolved ``RunStore(...)`` callsite and the intent it declares."""

    path: str
    line: int
    qualname: str
    intent: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.path, self.qualname)


def _module_name(relative: Path) -> str:
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _absolute_import(current_module: str, module: str | None, level: int) -> str:
    """Resolve a possibly-relative ``from`` target to a dotted module path."""

    if level == 0:
        return module or ""
    owner = current_module.split(".")
    anchor = owner[: len(owner) - level] if level <= len(owner) else []
    return ".".join([*anchor, *([module] if module else [])])


def _name_bindings(tree: ast.AST, current_module: str) -> dict[str, str]:
    """Local name -> dotted path it binds, for every import in the module."""

    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    bindings[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_import(current_module, node.module, node.level)
            for alias in node.names:
                bound = f"{base}.{alias.name}" if base else alias.name
                bindings[alias.asname or alias.name] = bound
    if current_module == _DEFINING_MODULE:
        # Inside the defining module the class is a plain module-level name.
        bindings.setdefault("RunStore", f"{_DEFINING_MODULE}.RunStore")
    return bindings


def _dotted(func: ast.expr) -> list[str] | None:
    """Flatten ``a.b.C`` to ``["a", "b", "C"]``; ``None`` when not a name chain."""

    if isinstance(func, ast.Name):
        return [func.id]
    if isinstance(func, ast.Attribute):
        head = _dotted(func.value)
        return None if head is None else [*head, func.attr]
    return None


def _enclosing_qualnames(tree: ast.AST) -> dict[int, str]:
    """``id(call)`` -> the qualified name of the function enclosing it."""

    owners: dict[int, str] = {}

    def descend(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                descend(child, f"{prefix}.{child.name}" if prefix else child.name)
                continue
            if isinstance(child, ast.Call):
                owners[id(child)] = prefix or "<module>"
            descend(child, prefix)

    descend(tree, "")
    return owners


def _declared_intent(call: ast.Call) -> str:
    """What the callsite says about creating the store."""

    keywords = {keyword.arg: keyword for keyword in call.keywords}
    if None in keywords:
        # ``RunStore(path, **options)`` hides the answer from every reader,
        # human or mechanical, so it is not an answer.
        return _INTENT_UNDECIDABLE
    if "create" not in keywords:
        return _INTENT_IMPLICIT
    value = keywords["create"].value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, bool):
        return _INTENT_UNDECIDABLE
    return _INTENT_CREATE if value.value else _INTENT_READ


def _constructs_run_store(call: ast.Call, bindings: Mapping[str, str]) -> bool:
    """Does this call construct the run-store class, under any spelling?

    One predicate rather than a chain of guards in the caller: the question is
    single -- "does this name resolve to that class" -- and splitting it across
    the walk would make the loop the place where the answer is assembled.
    """

    chain = _dotted(call.func)
    if chain is None or chain[0] not in bindings:
        return False
    return ".".join([bindings[chain[0]], *chain[1:]]) in _RUN_STORE_TARGETS


def run_store_constructions(source: str, *, path: str) -> tuple[_Construction, ...]:
    """Every ``RunStore(...)`` construction in one module, with its intent.

    Exposed on source text rather than on a path so the classifier can be
    driven by a synthetic module: a guard nothing has been shown to trip is
    theatre, and the shapes that must trip it do not exist in this tree.
    """

    tree = ast.parse(source, filename=path)
    current_module = _module_name(Path(path))
    bindings = _name_bindings(tree, current_module)
    owners = _enclosing_qualnames(tree)
    found: list[_Construction] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _constructs_run_store(node, bindings):
            continue
        found.append(
            _Construction(
                path=path,
                line=node.func.lineno,
                qualname=owners[id(node)],
                intent=_declared_intent(node),
            )
        )
    return tuple(sorted(found, key=lambda site: (site.path, site.line)))


def _tracked_python_files() -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "--", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(Path(line) for line in completed.stdout.split() if line)


def production_python_files() -> tuple[Path, ...]:
    """Every production module, enumerated without a hand-written list.

    The roots are DERIVED from what git tracks rather than named here, and the
    files are then read off disk, so a module that is new and not yet tracked
    is still parsed.  ``tests/`` is the only exclusion with a reason of its
    own: the creating default is legitimate in a fixture, and it is used by
    hundreds of them.
    """

    tracked = [path for path in _tracked_python_files() if path.parts[0] != "tests"]
    roots = sorted({path.parts[0] for path in tracked})
    on_disk = {
        found.relative_to(_REPO_ROOT)
        for root in roots
        for found in (_REPO_ROOT / root).rglob("*.py")
        if not _GENERATED_DIRECTORY_NAMES.intersection(
            found.relative_to(_REPO_ROOT).parts
        )
    }
    return tuple(sorted(on_disk.union(tracked)))


def production_inventory() -> tuple[_Construction, ...]:
    """The whole structural inventory, over every production module."""

    found: list[_Construction] = []
    for relative in production_python_files():
        source = (_REPO_ROOT / relative).read_text("utf-8")
        found.extend(run_store_constructions(source, path=str(relative)))
    return tuple(found)


def _report(inventory: Iterable[_Construction]) -> str:
    counted = Counter(site.intent for site in inventory)
    unknown = counted[_INTENT_UNDECIDABLE] + sum(
        count
        for key, count in Counter(
            site.key for site in inventory if site.intent == _INTENT_IMPLICIT
        ).items()
        if count != _LEGACY_IMPLICIT_CREATE.get(key, 0)
    )
    return "\n".join(
        (
            f"  explicit create=True   {counted[_INTENT_CREATE]:>4}",
            f"  explicit create=False  {counted[_INTENT_READ]:>4}",
            f"  legacy implicit-create {counted[_INTENT_IMPLICIT]:>4}",
            f"  unknown/implicit new   {unknown:>4}",
            "",
            *(
                f"  {site.path}:{site.line} {site.qualname} -> {site.intent}"
                for site in inventory
            ),
        )
    )


# ---------------------------------------------------------------------------
# The invariant.
# ---------------------------------------------------------------------------


def test_no_production_run_store_is_constructed_by_accident() -> None:
    """Every construction is explicit, or it is one of the frozen legacy ones.

    Equality in both directions is deliberate.  A new bare construction fails
    because it is not in the inventory; a retired one fails because the floor
    moved, and a ratchet whose floor may drop without a word is not a ratchet.
    """

    inventory = production_inventory()

    undecidable = [site for site in inventory if site.intent == _INTENT_UNDECIDABLE]
    assert not undecidable, (
        "a construction hides its intent behind **kwargs or a non-literal:\n"
        + _report(inventory)
    )

    implicit = Counter(
        site.key for site in inventory if site.intent == _INTENT_IMPLICIT
    )
    assert dict(implicit) == dict(_LEGACY_IMPLICIT_CREATE), (
        "the bare RunStore(...) constructor is frozen: a writer declares "
        "create=True and a reader declares create=False.\n" + _report(inventory)
    )


# ---------------------------------------------------------------------------
# Probe validity: the inventory must be able to see what it claims to forbid.
# ---------------------------------------------------------------------------


def test_the_inventory_reaches_every_production_module() -> None:
    """The walk covers the tree, and a dumb text scan finds nothing it missed.

    A guard that inspects a hand-listed set of files is the same hole in a new
    costume, so this measures reach two ways.  The enumeration is derived from
    git and re-read off disk; the reconciliation then holds every line a plain
    regex can see against the structural inventory.  Text is a floor and never
    a ceiling: the structural walk legitimately sees aliased constructions no
    regex can, so a surplus is reported and only a DEFICIT fails.
    """

    files = production_python_files()
    assert files, "the production enumeration is empty; nothing was measured"
    assert Path("codeclone/core/canonical_snapshot.py") in files

    inventory = production_inventory()
    structural = {(site.path, site.line) for site in inventory}
    textual = {
        (str(relative), number)
        for relative in files
        for number, line in enumerate(
            (_REPO_ROOT / relative).read_text("utf-8").splitlines(), 1
        )
        if _TEXTUAL_WITNESS.search(line)
    }

    assert textual <= structural, (
        "the structural inventory missed a callsite a plain regex can see, so "
        "it does not reach the whole tree: "
        f"{sorted(textual - structural)}\n" + _report(inventory)
    )


def test_the_frozen_inventory_is_a_callsite_permission_not_a_file_one() -> None:
    """The classifier is driven over the shapes this tree does not contain.

    Reachability from the other side.  Every violating shape below is absent
    from the repository, so without a synthetic module none of them has ever
    been shown to trip the guard, and "the inventory is green" would say only
    that nothing tried.  The aliased case is the load-bearing one: a textual
    prohibition is blind to it by construction.
    """

    module = "codeclone/core/canonical_snapshot.py"

    frozen_owner = run_store_constructions(
        "from ..canonical.store import RunStore\n"
        "def _publish_enabled(path):\n"
        "    with RunStore(path) as store:\n"
        "        return store\n"
        "    \n",
        path=module,
    )
    assert [site.qualname for site in frozen_owner] == ["_publish_enabled"]
    assert frozen_owner[0].intent == _INTENT_IMPLICIT
    assert frozen_owner[0].key in _LEGACY_IMPLICIT_CREATE

    # A SECOND bare construction inside the very function the inventory
    # freezes: the count, not the name, is what is permitted.
    doubled = run_store_constructions(
        "from ..canonical.store import RunStore\n"
        "def _publish_enabled(path, other):\n"
        "    RunStore(path)\n"
        "    RunStore(other)\n",
        path=module,
    )
    assert len(doubled) == 2
    assert (
        Counter(site.key for site in doubled)[(module, "_publish_enabled")]
        != _LEGACY_IMPLICIT_CREATE[(module, "_publish_enabled")]
    )

    # The same bare call one function away, in a file that holds a frozen
    # callsite: a file-level allowlist would call this legal.
    neighbour = run_store_constructions(
        "from ..canonical.store import RunStore\n"
        "def a_new_neighbour(path):\n"
        "    RunStore(path)\n",
        path=module,
    )
    assert [site.intent for site in neighbour] == [_INTENT_IMPLICIT]
    assert neighbour[0].key not in _LEGACY_IMPLICIT_CREATE

    # Aliased, attribute-qualified, and package re-exported spellings: a
    # textual prohibition sees none of the first two.
    for source in (
        "from ..canonical.store import RunStore as _RS\ndef f(p):\n    _RS(p)\n",
        "from ..canonical import store as _s\ndef f(p):\n    _s.RunStore(p)\n",
        "from ..canonical import RunStore\ndef f(p):\n    RunStore(p)\n",
        "import codeclone.canonical.store as _m\ndef f(p):\n    _m.RunStore(p)\n",
        "import codeclone.canonical.store\ndef f(p):\n"
        "    codeclone.canonical.store.RunStore(p)\n",
    ):
        sites = run_store_constructions(source, path=module)
        assert [site.intent for site in sites] == [_INTENT_IMPLICIT], source

    # Declared intents are read, both ways, and an undeclarable one is not
    # quietly counted as declared.
    assert [
        site.intent
        for site in run_store_constructions(
            "from ..canonical.store import RunStore\n"
            "def f(p, o):\n"
            "    RunStore(p, create=True)\n"
            "    RunStore(p, create=False)\n"
            "    RunStore(p, **o)\n",
            path=module,
        )
    ] == [_INTENT_CREATE, _INTENT_READ, _INTENT_UNDECIDABLE]

    # A same-named class from somewhere else is NOT this class.
    assert not run_store_constructions(
        "from somewhere.else_ import RunStore\ndef f(p):\n    RunStore(p)\n",
        path=module,
    )

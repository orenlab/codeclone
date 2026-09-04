# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The correctness floor of a long-lived server: refuse to answer for code it
no longer runs.

An MCP server keeps the modules it imported at startup and keeps answering with
them while the checkout underneath moves on.  Measured: two server processes
held modules from before a landed engine commit and refused 1212 of 1212 files
with a *deterministic* ``run_id`` -- so the two agreed with each other and
looked healthy, while a fresh CLI on the same tree refused none.

``code_provenance.code_digest`` could not report that, by construction: it is
stamped once at process start, so a stale server honestly reports the digest it
was launched with and shows no drift ever.  It is a marker, and a marker
observes.  This module is the gate, and it decides.

Two checks, because one is not enough:

* **Entry.**  Before an operation executes, the generation of the code this
  process loaded is compared against the generation the loaded package root
  holds on disk *now*.  A difference raises :class:`StaleEngineError` and the
  operation does not run at all -- a refusal raised after the work ran would
  answer with exactly the stale code the fence exists to withhold.
* **During.**  The checkout can move while an analysis is running, and late
  imports make that worse: a module imported at minute two comes from the new
  tree while minute one came from the old.  The generation is therefore read
  again when the operation finishes and compared against the reading taken at
  entry; a move raises :class:`EngineChangedDuringOperationError` and the
  result is not published as a normal success.

Three properties this deliberately does not trade away:

**Content-bound, never stat-bound.**  The generation is the same content digest
:mod:`._code_provenance` derives -- path plus sha256 of bytes, for every ``*.py``
under the root.  A ``(mtime, size)`` key was rejected on measurement, not on
taste: a same-size edit restored inside one second is invisible to it, which is
precisely how a stale ``.pyc`` poisons a mutation battery in this repository.
The cost is real and is stated rather than optimised away: about 100 ms per
reading of this tree's 584 files, so roughly 200 ms per fenced call.

**Bound to the loaded package root, never to the root the caller passed.**
:func:`~._code_provenance.package_source_root` reads ``codeclone.__file__`` --
the directory the running interpreter actually imported.  "The repository I was
asked about" and "the code I am running" are routinely different objects: a
worktree ``.venv`` carries an editable finder rooted at the main checkout, and
an ``analyze_repository`` call against a worktree was measured returning
``source_root`` naming the main checkout instead.  A fence that compared the
requested root would pass on a sibling worktree that happens to still hold the
generation this process loaded, while the engine underneath it had already
moved.

**Fail closed.**  A root that becomes unreadable digests to ``"unknown"`` and
stops matching a real generation, so the operation is refused rather than
served on a guess.  The one case that cannot be fenced is an install with no
readable sources at all (compiled-only): both readings are ``"unknown"``, they
agree, and there is nothing to compare.  That is a property of the install, not
a hole in the gate, and it is pinned by a test so it stays deliberate.

The floor lives here, inside the server, and not in a client handshake: the
clients are Claude Code, Cursor and Codex, none of them ours, and none of them
obliged to send anything before a call.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final, cast

from ._code_provenance import (
    compute_code_provenance,
    package_source_root,
    process_code_provenance,
)
from .messages import errors as err_msgs

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Awaitable, Callable

    from mcp.server.fastmcp import FastMCP

    #: One executing entry point of the protocol, in the only shape the fence
    #: needs of it: awaitable, and taking whatever the protocol handed it.
    #: The wrapper never names the protocol's argument types -- naming the
    #: resource URI type would mean importing ``pydantic`` here, and pydantic
    #: is a dependency only CodeClone's sanctioned model store may carry.
    Delegate = Callable[..., Awaitable[object]]

#: Refusal code: the loaded engine is not the engine on disk.
STALE_ENGINE: Final = "STALE_ENGINE"
#: Refusal code: the engine on disk moved while the operation was running.
ENGINE_CHANGED_DURING_OPERATION: Final = "ENGINE_CHANGED_DURING_OPERATION"

_CODE_DIGEST_KEY: Final = "code_digest"
_SOURCE_ROOT_KEY: Final = "source_root"


class EngineFenceError(RuntimeError):
    """This process may not answer for the code the disk holds.

    A typed refusal, not a diagnostic: every subclass names a decision the
    fence made *instead of* serving a result.
    """

    #: Stable machine-readable code, carried at the head of ``str(exc)``.
    code: str = ""


class StaleEngineError(EngineFenceError):
    """The loaded generation is not the generation on disk. Nothing executed."""

    code = STALE_ENGINE


class EngineChangedDuringOperationError(EngineFenceError):
    """The generation moved mid-operation. The result is withheld, not published."""

    code = ENGINE_CHANGED_DURING_OPERATION


def loaded_engine_generation() -> str:
    """Generation of the code this process imported, pinned at process start.

    Read through the same owner the run summary and the receipt read, so the
    gate and the marker can never disagree about what was loaded.
    """

    return str(process_code_provenance().get(_CODE_DIGEST_KEY, ""))


def loaded_package_root() -> str:
    """Identity of the package directory this process imported.

    Provenance, not truth: it names *which* tree answered, and it is reported
    beside a generation rather than folded into one.
    """

    return str(process_code_provenance().get(_SOURCE_ROOT_KEY, ""))


def disk_engine_generation() -> str:
    """Generation the loaded package root holds on disk right now.

    Deliberately uncached and deliberately re-derived from
    :func:`package_source_root` on every call: a memo keyed by anything cheaper
    than content is the hole this fence exists to close, and a root taken from
    the caller's arguments would measure a tree this process never imported.
    """

    return str(compute_code_provenance(package_source_root()).get(_CODE_DIGEST_KEY, ""))


@contextmanager
def engine_fence(operation: str) -> Iterator[str]:
    """Bracket one operation with the entry and during-operation checks.

    Yields the generation observed at entry.  The entry check runs before the
    body, so a refused operation never executes; the closing check runs only
    when the body completed, because an operation that already failed has no
    result to withhold.
    """

    loaded = loaded_engine_generation()
    entry_generation = disk_engine_generation()
    if entry_generation != loaded:
        raise StaleEngineError(
            err_msgs.stale_engine(
                operation,
                loaded=loaded,
                on_disk=entry_generation,
                package_root=loaded_package_root(),
            )
        )
    yield entry_generation
    exit_generation = disk_engine_generation()
    if exit_generation != entry_generation:
        raise EngineChangedDuringOperationError(
            err_msgs.engine_changed_during_operation(
                operation,
                at_entry=entry_generation,
                at_exit=exit_generation,
                package_root=loaded_package_root(),
            )
        )


#: One class of registered handler, and how the framework executes it, as
#: pure data -- the repo's constants-table idiom
#: (``REPORT_SEMANTIC_PRODUCERS``), and deliberately not a dataclass: runtime
#: model shapes belong to the model store (the phase-39S boundary), while this
#: is a constants table.
#:
#: Not a framework method name written down somewhere.  A surface is *a
#: population somebody registered* plus the single entry point through which
#: that population runs, and the two are declared together so neither can be
#: read without the other.
#:
#: Keys:
#: ``kind``         the framework's own word for this class of handler
#: ``registry``     instance attribute holding the registered population
#: ``listers``      methods on that registry returning what was registered --
#:                  plural because a resource is registered either concretely
#:                  or as a template, and a templated resource is an entry
#:                  point a client can invoke
#: ``entry_point``  the framework method through which one of those handlers
#:                  executes
#: ``describe``     renders the operation name for a refusal from the
#:                  protocol's own arguments; deliberately untyped in its
#:                  parameters, because it renders whatever the protocol
#:                  handed the delegate and giving it a signature would name
#:                  those types a second time
ExecutableSurface = Mapping[str, object]

#: Every class of handler this framework can execute on our behalf.
#:
#: ``registry``/``listers`` are what let a ratchet ask how many are registered
#: TODAY instead of trusting a literal written once and outlived by the
#: framework: measured 2026-09-04, an equality against
#: ``{"call_tool", "read_resource"}`` was green while ``get_prompt`` executed
#: registered handlers outside the fence.  The fence covers every surface in
#: this table and the ratchet over the registered population reads the same
#: table, so a surface cannot be fenced in one place and forgotten in the
#: other.
#:
#: ``get_prompt`` is here although zero prompts are registered today: a fence
#: that waits for the first registration has to be added by whoever adds the
#: prompt, and the measured shape of that hole is that nobody does.  Fencing
#: an unregistered surface costs exactly zero -- an entry point nothing
#: reaches takes no reading.
#:
#: Catalogue reads (``list_tools`` / ``list_resources`` / ``list_prompts``)
#: are absent on purpose and must stay absent: they execute no registered
#: handler, and the diagnosing layer calls ``list_tools`` from INSIDE a fenced
#: ``call_tool`` to build a refusal.  A stale catalogue is a separate fact
#: from a stale answer.
EXECUTABLE_SURFACES: Final[tuple[ExecutableSurface, ...]] = (
    {
        "kind": "tool",
        "registry": "_tool_manager",
        "listers": ("list_tools",),
        "entry_point": "call_tool",
        "describe": lambda name, _arguments: f"tool {name}",
    },
    {
        "kind": "resource",
        "registry": "_resource_manager",
        "listers": ("list_resources", "list_templates"),
        "entry_point": "read_resource",
        "describe": lambda uri: f"resource {uri}",
    },
    {
        "kind": "prompt",
        "registry": "_prompt_manager",
        "listers": ("list_prompts",),
        "entry_point": "get_prompt",
        "describe": lambda name, _arguments=None: f"prompt {name}",
    },
)


def surface_entry_point(surface: ExecutableSurface) -> str:
    """The framework method through which ``surface``'s handlers execute."""

    return str(surface["entry_point"])


def surface_describe(surface: ExecutableSurface) -> Callable[..., str]:
    """``surface``'s refusal renderer, narrowed out of the constants table."""

    return cast("Callable[..., str]", surface["describe"])


def _fenced(delegate: Delegate, describe: Callable[..., str]) -> Delegate:
    """One fenced override, built from the method it wraps.

    Written once for every surface so they cannot drift into different gates,
    and parameterised on the delegate so the wrapper never has to name the
    protocol's own argument types.
    """

    async def fenced_method(
        server: object,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        with engine_fence(describe(*args, **kwargs)):
            return await delegate(server, *args, **kwargs)

    return fenced_method


def _delegate(base: type[FastMCP], entry_point: str) -> Delegate:
    """The unbound method the fence composes over, read off the runtime base.

    ``getattr`` rather than ``base.call_tool``, because the entry point is
    named by :data:`EXECUTABLE_SURFACES` and not written here; the result is
    narrowed immediately to the one shape a fenced override needs, so nothing
    downstream degrades to ``Any``.  Read off ``base`` and not off ``FastMCP``:
    the base is chosen at runtime and already carries the diagnosing layer,
    which a lookup on the protocol class would skip.
    """

    return cast("Delegate", getattr(base, entry_point))


def fenced_server_class(base: type[FastMCP]) -> type[FastMCP]:
    """``base`` with every executing entry point behind the fence.

    The overridden set is DERIVED from :data:`EXECUTABLE_SURFACES` -- the
    classes of handler the framework can execute -- rather than listed here.
    Every registered tool, resource and prompt reaches its handler through one
    of those entry points, so the gate covers them by construction rather than
    through a per-handler list somebody has to keep in step.  A guard wired at
    one call site, or keyed by a handler's name, is blind by construction --
    measured twice in this repository.

    The fence is deliberately the outermost layer, above the argument
    diagnosis: when the engine is stale, its reading of the caller's arguments
    is no more trustworthy than its analysis would have been.
    """

    # Built with ``type`` rather than a ``class`` statement, and delegating
    # through the unbound ``base.<method>`` rather than a zero-argument
    # ``super()``: the base is chosen at runtime (this fence composes over
    # whatever server class the runtime loader assembled), and a ``class``
    # statement over a runtime base is one neither type checker can resolve.
    return cast(
        "type[FastMCP]",
        type(
            "_EngineFencedFastMCP",
            (base,),
            {
                surface_entry_point(surface): _fenced(
                    _delegate(base, surface_entry_point(surface)),
                    surface_describe(surface),
                )
                for surface in EXECUTABLE_SURFACES
            },
        ),
    )


__all__ = [
    "ENGINE_CHANGED_DURING_OPERATION",
    "EXECUTABLE_SURFACES",
    "STALE_ENGINE",
    "EngineChangedDuringOperationError",
    "EngineFenceError",
    "ExecutableSurface",
    "StaleEngineError",
    "disk_engine_generation",
    "engine_fence",
    "fenced_server_class",
    "loaded_engine_generation",
    "loaded_package_root",
    "surface_describe",
    "surface_entry_point",
]

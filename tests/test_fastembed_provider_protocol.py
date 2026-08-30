# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Hold the fastembed protocols against the fastembed objects they describe.

``fastembed`` ships ``py.typed``, so everything this provider touches is
describable -- but the provider reached it through ``importlib.import_module``
and bound every result with ``cast``, and those two silences compose.  mypy
resolves a literal dynamic import only as far as ``ModuleType`` and hands back
``Any`` for every member, so an annotated binding on top of it says nothing;
the cast then covers the rest on every checker.

The suite's own doubles cannot close this: they are written against the
declared protocol, so a protocol that misdescribes the vendor is confirmed by
its own mock.  These pins read the installed objects instead.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest

from codeclone.memory.embedding import fastembed_provider
from codeclone.memory.embedding.fastembed_provider import FastEmbedEmbeddingProvider
from codeclone.memory.exceptions import MemorySemanticUnavailableError
from tests.test_lancedb_connection_protocol import (
    _binding_mismatches,
    _declared_methods,
    _resolve_return_type,
)

fastembed = pytest.importorskip("fastembed")
tokenizers = pytest.importorskip("tokenizers")

_SUPPRESSION_NAMES = frozenset({"Any", "cast"})
# The provider's own default, so both sides of every assertion below derive
# from the one model this repository actually configures.
_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_DIMENSION = 384
# Named once: the same string finds the owner, replaces it, and restores it.
_DOWNLOAD_MEMBER = "download_model"


def _installed_inner_model_type() -> type:
    """The registry entry ``TextEmbedding.__init__`` picks for our model name.

    Re-derived by the vendor's own selection rule rather than written down, so
    a registry reshuffle is reported instead of silently pinning the wrong
    class.
    """
    for candidate in fastembed.TextEmbedding.EMBEDDINGS_REGISTRY:
        for described in candidate._list_supported_models():
            if described.model.lower() == _MODEL_NAME.lower():
                assert isinstance(candidate, type)
                return candidate
    raise AssertionError(f"no fastembed registry entry serves {_MODEL_NAME}")


def _member_problems(protocol: type, installed: type, name: str) -> list[str]:
    """Every way this one declared member misdescribes the installed object.

    The binding rule itself is imported, never restated.  Every member paired
    here is a plain method, so an unreadable signature is reported rather than
    excused: a pin that cannot read what it is holding is not holding anything.
    """
    installed_member = inspect.getattr_static(installed, name, None)
    if installed_member is None:
        return [f"{installed.__name__} has no member {name!r}"]
    try:
        installed_signature = inspect.signature(installed_member)
    except (TypeError, ValueError) as exc:
        return [f"{installed.__name__}.{name} has no readable signature: {exc}"]
    declared = inspect.signature(_declared_methods(protocol)[name])
    return _binding_mismatches(declared, installed_signature)


def _signature_pairs() -> list[tuple[type, type]]:
    """Protocols whose members the vendor exposes on a class, so a signature
    can be read off it and held against the declaration."""
    return [
        (fastembed_provider._TextEmbeddingModel, fastembed.TextEmbedding),
        (fastembed_provider._TokenizingTextModel, _installed_inner_model_type()),
        (fastembed_provider._Tokenizer, tokenizers.Tokenizer),
        (fastembed_provider._BatchTokenizer, tokenizers.Tokenizer),
    ]


def _narrowed_only_protocols() -> list[type]:
    """Protocols whose members fastembed creates during ``__init__``.

    No class-level signature describes them, so the declaration cannot be held
    against a class.  Their check is the ``isinstance`` narrowing production
    performs on the live object, which is why each one must be
    ``runtime_checkable`` and must actually discriminate.
    """
    return [
        fastembed_provider._InnerModelHolder,
        fastembed_provider._TokenizerHolder,
    ]


_MEMBER_CASES = [
    (protocol, installed, name)
    for protocol, installed in _signature_pairs()
    for name in sorted(_declared_methods(protocol))
]


@pytest.mark.parametrize(
    ("protocol", "installed", "member"),
    _MEMBER_CASES,
    ids=[f"{protocol.__name__}.{name}" for protocol, _, name in _MEMBER_CASES],
)
def test_declared_member_binds_on_the_installed_object(
    protocol: type, installed: type, member: str
) -> None:
    """One case per declared member, so a break names the member it broke."""
    problems = _member_problems(protocol, installed, member)
    assert problems == [], (
        f"{protocol.__name__}.{member} does not describe "
        f"{installed.__name__}.{member}: {problems}"
    )


def test_the_pairing_reaches_every_protocol_the_module_declares() -> None:
    """A pairing that stopped early would pin nothing past the first protocol.

    The expected set is read off the module, not written down, so a protocol
    added later is unpinned loudly instead of silently.
    """
    declared = {
        name
        for name, value in vars(fastembed_provider).items()
        if isinstance(value, type)
        and getattr(value, "_is_protocol", False)
        and value.__module__ == fastembed_provider.__name__
    }
    reached = (
        {protocol.__name__ for protocol, _ in _signature_pairs()}
        | {protocol.__name__ for protocol in _narrowed_only_protocols()}
        | {fastembed_provider._TextEmbeddingFactory.__name__}
    )
    assert declared == reached, f"protocols never paired: {sorted(declared ^ reached)}"


def test_every_narrowed_protocol_can_be_asked_and_can_say_no() -> None:
    """A narrowing that answers yes to everything is not a check.

    Each of these is reached by ``isinstance`` rather than by a declaration a
    checker can verify, so the rule proves here that an input exists which
    reaches it and trips it, and another which passes it.
    """
    for protocol in _narrowed_only_protocols():
        members = sorted(
            set(_declared_methods(protocol))
            | set(vars(protocol).get("__annotations__", {}))
        )
        assert members, f"{protocol.__name__} declares nothing to narrow on"
        carrier = SimpleNamespace(**dict.fromkeys(members))
        # A protocol that is not runtime_checkable raises TypeError here, which
        # is the failure this asserts against -- read as behaviour rather than
        # off a private flag.
        assert isinstance(carrier, protocol), (
            f"{protocol.__name__} rejects an object carrying {members}"
        )
        assert not isinstance(object(), protocol), (
            f"{protocol.__name__} accepts an object carrying nothing"
        )


def test_the_factory_call_binds_on_the_installed_constructor() -> None:
    """The declared constructor keywords must bind on ``TextEmbedding``.

    ``local_files_only`` is not in the vendor's explicit signature; it is
    accepted through ``**kwargs``.  Naming it here states that the vendor still
    takes it -- and the download witness below states that the value still
    arrives at the decision it controls.
    """
    problems = _binding_mismatches(
        inspect.signature(fastembed_provider._TextEmbeddingFactory.__call__),
        inspect.signature(fastembed.TextEmbedding.__init__),
    )
    assert problems == [], (
        f"_TextEmbeddingFactory does not call TextEmbedding: {problems}"
    )


def test_the_binding_rule_rejects_a_shape_that_only_carries_the_names() -> None:
    """Name presence is all the silenced check saw; this rule reads signatures.

    Proves an input exists that reaches the rule and trips it -- a rule nothing
    can fail is theatre.
    """

    class _NamesOnlyModel:
        model: object

        def embed(self, payload: list[str], extra: int) -> list[object]:
            del payload, extra
            return []

    problems = _member_problems(
        fastembed_provider._TextEmbeddingModel, _NamesOnlyModel, "embed"
    )
    assert problems, "a wrong shape went unnoticed"


def test_the_module_carries_no_type_suppression() -> None:
    """``cast`` here is suppression by another name: it hid this exact defect.

    A cast silences the binding check on every checker, and it is what let the
    declared ``embed`` parameter drift away from the installed one unnoticed.
    """
    source = Path(str(fastembed_provider.__file__)).read_text(encoding="utf-8")
    found = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name | ast.Attribute)
    } & _SUPPRESSION_NAMES
    assert not found, f"type suppression is back in the module: {sorted(found)}"
    assert "type: ignore" not in source, "a type: ignore is back in the module"


def test_the_factory_enters_the_module_through_a_declared_protocol() -> None:
    """The constructor edge is where the vendor first becomes describable.

    ``Callable[..., object]`` erases every parameter, so the keywords this
    provider sends -- ``local_files_only`` among them -- bind against nothing.
    """
    resolver = FastEmbedEmbeddingProvider._resolve_text_embedding
    assert isinstance(resolver, FunctionType)
    declared = _resolve_return_type(resolver, FastEmbedEmbeddingProvider)
    assert declared is not None and getattr(declared, "_is_protocol", False), (
        f"_resolve_text_embedding declares {declared!r}, which describes nothing"
    )
    assert declared.__module__ == fastembed_provider.__name__


def _download_model_owner() -> type:
    """The class that defines the vendor's download decision, by the MRO."""
    for candidate in _installed_inner_model_type().__mro__:
        if _DOWNLOAD_MEMBER in vars(candidate):
            return candidate
    raise AssertionError(f"fastembed no longer defines {_DOWNLOAD_MEMBER}")


def test_the_download_switch_reaches_the_vendor_decision(tmp_path: Path) -> None:
    """``allow_model_download`` is enforced only if it reaches this call.

    The value is read at the vendor's own decision point -- the ``kwargs`` of
    ``ModelManagement.download_model``, which is where fastembed decides
    whether the network may be used -- and not at our call site, so a keyword
    that stops being forwarded is a failure here rather than a silent policy
    change.  Both settings are driven, so an inverted switch fails too.
    """
    owner = _download_model_owner()
    original = inspect.getattr_static(owner, _DOWNLOAD_MEMBER)
    seen: list[object] = []

    def _record(cls: type, /, model: object, cache_dir: str, **kwargs: object) -> Path:
        del cls, model, cache_dir
        seen.append(kwargs.get("local_files_only", "<never forwarded>"))
        raise RuntimeError("probe: the vendor download decision was reached")

    setattr(owner, _DOWNLOAD_MEMBER, classmethod(_record))
    try:
        for allow_model_download in (False, True):
            provider = FastEmbedEmbeddingProvider(
                model_name=_MODEL_NAME,
                dimension=_DIMENSION,
                cache_dir=tmp_path / "cache",
                allow_model_download=allow_model_download,
            )
            with pytest.raises(MemorySemanticUnavailableError):
                provider.embed_documents(["probe"])
    finally:
        setattr(owner, _DOWNLOAD_MEMBER, original)

    assert seen == [True, False], (
        f"the download switch did not arrive at the vendor decision as declared: {seen}"
    )

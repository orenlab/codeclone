# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from codeclone.config.memory import SemanticConfig
from codeclone.memory.embedding import (
    DeterministicHashEmbeddingProvider,
    embed_documents,
    embed_query,
    resolve_embedding_provider,
)
from codeclone.memory.exceptions import MemorySemanticUnavailableError


def _declared_truncation(max_length: int) -> dict[str, object]:
    """The truncation mapping ``tokenizers.Tokenizer`` hands a caller back.

    The installed tokenizer keeps its window under a key, not on an attribute,
    and these doubles used to declare the opposite -- so a provider that asked
    for the attribute was confirmed by every double here while it read ``None``
    off every real tokenizer.  ``tests/test_fastembed_provider_protocol.py``
    holds this shape against the installed object.
    """
    return {
        "max_length": max_length,
        "stride": 0,
        "strategy": "longest_first",
        "direction": "right",
    }


class _FakeTextEmbedding:
    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: str,
        local_files_only: bool,
        vector_value: float = 1.0,
        vectors: list[object] | None = None,
        raise_on_embed: bool = False,
        inner_model: object | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.local_files_only = local_files_only
        self.vector_value = vector_value
        self.vectors = vectors
        self.raise_on_embed = raise_on_embed
        self.inputs: list[str] = []
        self.model = inner_model or SimpleNamespace(tokenizer=None)

    def embed(self, texts: list[str]) -> list[object]:
        if self.raise_on_embed:
            raise RuntimeError("embed failed")
        self.inputs.extend(texts)
        if self.vectors is not None:
            return self.vectors
        return [[self.vector_value] * 384 for _ in texts]


def _install_fake_fastembed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    vector_value: float = 1.0,
    vectors: list[object] | None = None,
    raise_on_init: bool = False,
    raise_on_embed: bool = False,
    expose_text_embedding: bool = True,
    inner_model: object | None = None,
) -> list[_FakeTextEmbedding]:
    import importlib

    created: list[_FakeTextEmbedding] = []
    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None) -> Any:
        if name != "fastembed":
            return original_import_module(name, package)
        if not expose_text_embedding:
            return SimpleNamespace()

        class _ConfiguredFakeTextEmbedding(_FakeTextEmbedding):
            def __init__(
                self,
                *,
                model_name: str,
                cache_dir: str,
                local_files_only: bool,
            ) -> None:
                if raise_on_init:
                    raise RuntimeError("model unavailable")
                super().__init__(
                    model_name=model_name,
                    cache_dir=cache_dir,
                    local_files_only=local_files_only,
                    vector_value=vector_value,
                    vectors=vectors,
                    raise_on_embed=raise_on_embed,
                    inner_model=inner_model,
                )
                created.append(self)

        return SimpleNamespace(TextEmbedding=_ConfiguredFakeTextEmbedding)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)
    return created


def _resolve_fastembed_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    inner_model: object | None = None,
    vector_value: float = 1.0,
    vectors: list[object] | None = None,
    raise_on_init: bool = False,
    raise_on_embed: bool = False,
    expose_text_embedding: bool = True,
) -> tuple[Any, list[_FakeTextEmbedding]]:
    from codeclone.memory.embedding.fastembed_provider import FastEmbedEmbeddingProvider

    created = _install_fake_fastembed(
        monkeypatch,
        vector_value=vector_value,
        vectors=vectors,
        raise_on_init=raise_on_init,
        raise_on_embed=raise_on_embed,
        expose_text_embedding=expose_text_embedding,
        inner_model=inner_model,
    )
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)
    assert isinstance(provider, FastEmbedEmbeddingProvider)
    return provider, created


def test_deterministic_embedding_is_stable_and_correct_dimension() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=64)
    first = provider.embed(["recover after MCP restart"])
    second = provider.embed(["recover after MCP restart"])
    assert first == second  # same text -> same vector
    assert len(first) == 1
    assert len(first[0]) == 64


def test_deterministic_embedding_is_l2_normalized() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=128)
    (vector,) = provider.embed(["checkpoint degrades to scope_only"])
    norm = math.sqrt(sum(value * value for value in vector))
    assert math.isclose(norm, 1.0, abs_tol=1e-9)


def test_deterministic_embedding_distinguishes_texts() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=64)
    vectors = provider.embed(["alpha", "beta"])
    assert vectors[0] != vectors[1]


def test_deterministic_query_and_document_helpers_use_provider_methods() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=7)
    assert embed_query(provider, "alpha") == provider.embed_query("alpha")
    assert embed_documents(provider, ["beta"]) == provider.embed_documents(["beta"])


def test_deterministic_embedding_rejects_nonpositive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension must be positive"):
        DeterministicHashEmbeddingProvider(dimension=0)


def test_resolve_diagnostic_provider() -> None:
    config = SemanticConfig(embedding_provider="diagnostic", dimension=256)
    provider = resolve_embedding_provider(config)
    assert provider.model_id == "diagnostic-hash-v1"
    assert provider.dimension == 256


def test_resolve_local_model_provider_fails_clear() -> None:
    config = SemanticConfig(embedding_provider="local_model")
    with pytest.raises(MemorySemanticUnavailableError, match="local_model"):
        resolve_embedding_provider(config)


def test_resolve_api_provider_fails_clear() -> None:
    config = SemanticConfig(embedding_provider="api")
    with pytest.raises(MemorySemanticUnavailableError, match="api"):
        resolve_embedding_provider(config)


class _LegacyEmbeddingProvider:
    model_id = "legacy"
    dimension = 2

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0] for text in texts]


def test_embedding_helpers_fall_back_to_embed() -> None:
    provider = _LegacyEmbeddingProvider()
    assert embed_query(provider, "abc") == [3.0, 0.0]
    assert embed_documents(provider, ["a", "abcd"]) == [[1.0, 0.0], [4.0, 0.0]]


def test_fastembed_provider_uses_local_model_cache_and_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fake_fastembed(monkeypatch)
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)

    assert provider.model_id == "fastembed:BAAI/bge-small-en-v1.5"
    assert provider.dimension == 384
    assert embed_query(provider, "recover after restart") == [1.0] * 384
    assert embed_documents(provider, ["scope-aware hygiene"]) == [[1.0] * 384]
    assert created[0].local_files_only is True
    assert created[0].inputs == [
        "query: recover after restart",
        "passage: scope-aware hygiene",
    ]
    assert provider.embed(["legacy call"]) == [[1.0] * 384]


def test_fastembed_provider_defers_model_load_until_first_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fake_fastembed(monkeypatch)
    config = SemanticConfig(embedding_provider="fastembed")

    provider = resolve_embedding_provider(config)
    # Construction verifies the package but must NOT load the ONNX model yet.
    assert created == []
    assert provider.model_id == "fastembed:BAAI/bge-small-en-v1.5"

    embed_query(provider, "first call loads the model")
    assert len(created) == 1
    # A second embed reuses the cached model instead of reloading it.
    embed_documents(provider, ["reuse the model"])
    assert len(created) == 1


def test_fastembed_provider_honors_download_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _install_fake_fastembed(monkeypatch, vector_value=0.0)
    config = SemanticConfig(
        embedding_provider="fastembed",
        allow_model_download=True,
    )
    provider = resolve_embedding_provider(config)

    assert provider.dimension == 384
    # The download flag is passed when the model loads — i.e. at first embed.
    embed_query(provider, "trigger lazy model load")
    assert [item.local_files_only for item in created] == [False]


def test_fastembed_provider_fails_clear_without_text_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastembed(monkeypatch, expose_text_embedding=False)
    config = SemanticConfig(embedding_provider="fastembed")

    with pytest.raises(MemorySemanticUnavailableError, match="TextEmbedding"):
        resolve_embedding_provider(config)


@pytest.mark.parametrize(
    ("allow_model_download", "message"),
    [(False, "download disabled"), (True, "download allowed")],
)
def test_fastembed_provider_fails_clear_when_model_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_model_download: bool,
    message: str,
) -> None:
    _install_fake_fastembed(monkeypatch, raise_on_init=True)
    config = SemanticConfig(
        embedding_provider="fastembed",
        allow_model_download=allow_model_download,
    )

    # Resolve succeeds (cheap package check); the model load — and its failure —
    # is deferred to the first embed.
    provider = resolve_embedding_provider(config)
    with pytest.raises(MemorySemanticUnavailableError, match=message):
        embed_query(provider, "boom")


def test_fastembed_provider_fails_clear_when_embedding_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastembed(monkeypatch, raise_on_embed=True)
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)

    with pytest.raises(MemorySemanticUnavailableError, match="embedding failed"):
        embed_query(provider, "boom")


def test_fastembed_provider_fails_clear_on_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastembed(monkeypatch, vectors=[[1.0, 2.0]])
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)

    with pytest.raises(MemorySemanticUnavailableError, match="dimension mismatch"):
        embed_query(provider, "short vector")


def test_fastembed_provider_fails_clear_on_non_iterable_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastembed(monkeypatch, vectors=[object()])
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)

    with pytest.raises(MemorySemanticUnavailableError, match="non-iterable"):
        embed_query(provider, "bad vector")


def test_fastembed_provider_fails_clear_on_string_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_fastembed(monkeypatch, vectors=["bad"])
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)

    with pytest.raises(MemorySemanticUnavailableError, match="non-iterable"):
        embed_query(provider, "bad vector")


def test_fastembed_provider_coerces_numpy_float32_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real fastembed TextEmbedding.embed() yields numpy float32 1-D arrays;
    # iterating one produces numpy.float32 scalars, which are NOT Python
    # float/int subclasses. The provider must still coerce them to Python
    # floats instead of rejecting every real embedding as "non-numeric".
    numpy = pytest.importorskip("numpy")
    vector = numpy.asarray([0.5] * 384, dtype=numpy.float32)
    provider, _created = _resolve_fastembed_provider(monkeypatch, vectors=[vector])

    result = embed_query(provider, "numpy vector")

    assert len(result) == 384
    assert all(type(value) is float for value in result)
    assert result == [0.5] * 384


def test_fastembed_provider_rejects_non_real_vector_element(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-Real element *inside* an iterable vector (here a str) must be
    # rejected cleanly as "non-numeric" rather than surfacing a bare ValueError
    # from float("bad"). This pins the element-level numbers.Real branch, which
    # the whole-vector str guard (vectors=["bad"], caught as "non-iterable")
    # never reaches.
    provider, _created = _resolve_fastembed_provider(monkeypatch, vectors=[["bad"]])

    with pytest.raises(MemorySemanticUnavailableError, match="non-numeric"):
        embed_query(provider, "bad element")


def test_fastembed_provider_fails_clear_when_extra_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    original_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None) -> Any:
        if name == "fastembed":
            raise ImportError(name)
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    config = SemanticConfig(embedding_provider="fastembed")
    with pytest.raises(MemorySemanticUnavailableError, match="semantic-fastembed"):
        resolve_embedding_provider(config)


def test_fastembed_estimate_tokens_without_model_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.embedding.fastembed_provider import FastEmbedEmbeddingProvider

    created = _install_fake_fastembed(monkeypatch, vector_value=0.0)
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)
    assert isinstance(provider, FastEmbedEmbeddingProvider)

    (count,) = provider.estimate_token_counts(["hello"])
    assert count == 4  # ceil(len("passage: hello") / 4)
    assert created == []


def test_fastembed_max_sequence_tokens_without_model_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.embedding.fastembed_provider import FastEmbedEmbeddingProvider

    _install_fake_fastembed(monkeypatch)
    config = SemanticConfig(embedding_provider="fastembed")
    provider = resolve_embedding_provider(config)
    assert isinstance(provider, FastEmbedEmbeddingProvider)

    assert provider.max_sequence_tokens() == 512


class _FakeEncoding:
    def __init__(self, length: int) -> None:
        self.ids = list(range(length))


class _FakeTokenizer:
    def __init__(self) -> None:
        self._truncated = True
        self.truncation = _declared_truncation(512)

    def no_truncation(self) -> None:
        self._truncated = False

    def enable_truncation(self, *, max_length: int) -> None:
        self._truncated = True
        self.truncation = _declared_truncation(max_length)

    def encode(self, text: str, *, add_special_tokens: bool) -> _FakeEncoding:
        return self.encode_batch([text])[0]

    def decode(self, ids: list[int]) -> str:
        return "x" * len(ids)

    def encode_batch(self, texts: list[str]) -> list[_FakeEncoding]:
        length = 512 if self._truncated else 1000
        return [_FakeEncoding(length) for _ in texts]


class _FakeInnerModel:
    def __init__(self) -> None:
        self.tokenizer = _FakeTokenizer()

    def tokenize(self, documents: list[str]) -> list[_FakeEncoding]:
        return self.tokenizer.encode_batch(documents)


def test_fastembed_probe_passage_token_counts_reports_raw_and_effective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=_FakeInnerModel(),
    )
    assert provider.estimator_label == "fastembed_tokenizer"

    (counts,) = provider.probe_passage_token_counts(["x" * 4000])
    assert counts.raw == 1000
    assert counts.effective == 512
    assert created


def test_fastembed_chunk_text_splits_long_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WindowEncoding:
        def __init__(self, length: int) -> None:
            self.ids = list(range(length))

    class _ChunkTokenizer:
        _SPECIAL_TOKENS = 2

        def __init__(self) -> None:
            self._truncated = True
            self.truncation = _declared_truncation(512)

        def no_truncation(self) -> None:
            self._truncated = False

        def enable_truncation(self, *, max_length: int) -> None:
            self._truncated = True
            self.truncation = _declared_truncation(max_length)

        def encode(self, text: str, *, add_special_tokens: bool) -> _WindowEncoding:
            content_tokens = len(text)
            if add_special_tokens:
                return _WindowEncoding(content_tokens + self._SPECIAL_TOKENS)
            return _WindowEncoding(content_tokens)

        def decode(self, ids: list[int]) -> str:
            return f"chunk-{len(ids)}"

    class _ChunkInnerModel:
        def __init__(self) -> None:
            self.tokenizer = _ChunkTokenizer()

        def tokenize(self, documents: list[str]) -> list[_WindowEncoding]:
            return [
                self.tokenizer.encode(document, add_special_tokens=True)
                for document in documents
            ]

    provider, created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=_ChunkInnerModel(),
    )
    chunks = provider.chunk_text("x" * 4000)
    assert len(chunks) == 8
    assert chunks[0] == "chunk-501"
    assert chunks[-1] == "chunk-493"
    assert sum(int(chunk.removeprefix("chunk-")) for chunk in chunks) == 4000
    assert created


class _PassageBoundaryTokenizer:
    SPECIAL_TOKENS = 2

    def __init__(self) -> None:
        self._truncated = True
        self.truncation = _declared_truncation(512)

    def no_truncation(self) -> None:
        self._truncated = False

    def enable_truncation(self, *, max_length: int) -> None:
        self._truncated = True
        self.truncation = _declared_truncation(max_length)

    def encode(self, text: str, *, add_special_tokens: bool) -> _FakeEncoding:
        content_tokens = len(text.encode("utf-8"))
        if add_special_tokens:
            return _FakeEncoding(content_tokens + self.SPECIAL_TOKENS)
        return _FakeEncoding(content_tokens)

    def decode(self, ids: list[int]) -> str:
        return "a" * len(ids)


def _boundary_fastembed_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, list[_FakeTextEmbedding]]:
    class _BoundaryInnerModel:
        def __init__(self) -> None:
            self.tokenizer = _PassageBoundaryTokenizer()

        def tokenize(self, documents: list[str]) -> list[_FakeEncoding]:
            return [
                self.tokenizer.encode(document, add_special_tokens=True)
                for document in documents
            ]

    return _resolve_fastembed_provider(
        monkeypatch,
        inner_model=_BoundaryInnerModel(),
    )


@pytest.mark.parametrize(
    ("content_len", "expected_chunks"),
    [
        (499, 1),
        (500, 1),
        (501, 1),
        (502, 2),
        (503, 2),
    ],
)
def test_passage_chunk_boundary_token_counts(
    monkeypatch: pytest.MonkeyPatch,
    content_len: int,
    expected_chunks: int,
) -> None:
    provider, _created = _boundary_fastembed_provider(monkeypatch)
    text = "a" * content_len
    chunks = provider.chunk_text(text)
    assert len(chunks) == expected_chunks
    tokenizer = _PassageBoundaryTokenizer()
    for chunk in chunks:
        raw = len(tokenizer.encode(f"passage: {chunk}", add_special_tokens=True).ids)
        assert raw <= 512


def test_passage_chunks_cover_every_source_token_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.semantic.chunking import expand_projection
    from codeclone.memory.semantic.models import SemanticProjection
    from codeclone.memory.semantic.projection import text_hash

    provider, _created = _boundary_fastembed_provider(monkeypatch)
    text = "/repo/codeclone/memory/semantic/chunking.py - " + ("x" * 1200)
    tokenizer = _PassageBoundaryTokenizer()
    source_token_count = len(tokenizer.encode(text, add_special_tokens=False).ids)
    chunks = provider.chunk_text(text)
    chunk_token_counts = [
        len(tokenizer.encode(chunk, add_special_tokens=False).ids) for chunk in chunks
    ]
    assert sum(chunk_token_counts) == source_token_count
    assert all(count <= 501 for count in chunk_token_counts)
    projection = SemanticProjection(
        source="trajectory",
        source_id="traj-1",
        kind="trajectory",
        text=text,
        text_hash=text_hash(text),
    )
    units = expand_projection(projection, provider)
    assert len(units) > 1
    assert all(
        len(tokenizer.encode(f"passage: {unit.text}", add_special_tokens=True).ids)
        <= 512
        for unit in units
    )


def test_passage_chunk_boundaries_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _created = _boundary_fastembed_provider(monkeypatch)
    text = "deterministic " * 400
    assert provider.chunk_text(text) == provider.chunk_text(text)


def test_known_model_max_tokens_defaults_to_512() -> None:
    from codeclone.memory.embedding.fastembed_provider import known_model_max_tokens

    assert known_model_max_tokens("BAAI/bge-small-en-v1.5") == 512
    assert known_model_max_tokens("unknown-model") == 512


def test_fastembed_max_sequence_tokens_uses_loaded_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    class _Tokenizer:
        truncation = _declared_truncation(256)

    class _Inner:
        tokenizer = _Tokenizer()

    provider, created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=_Inner(),
    )
    provider.embed_documents(["warmup"])
    assert provider.max_sequence_tokens() == 256
    assert created


def test_fastembed_probe_passage_token_counts_without_encode_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Tokenizer:
        truncation = _declared_truncation(512)

        def encode(self, text: str, *, add_special_tokens: bool) -> _FakeEncoding:
            return _FakeEncoding(len(text))

    class _Inner:
        def __init__(self) -> None:
            self.tokenizer = _Tokenizer()

        def tokenize(self, documents: list[str]) -> list[_FakeEncoding]:
            return [
                self.tokenizer.encode(doc, add_special_tokens=True) for doc in documents
            ]

    provider, _created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=_Inner(),
    )
    provider.embed_documents(["warmup"])
    (counts,) = provider.probe_passage_token_counts(["hello"])
    assert counts.raw == counts.effective


def test_fastembed_chunk_text_without_tokenizer_returns_original() -> None:
    from codeclone.memory.embedding.fastembed_provider import FastEmbedEmbeddingProvider

    provider = FastEmbedEmbeddingProvider(
        model_name="BAAI/bge-small-en-v1.5",
        dimension=384,
        cache_dir=Path("/tmp/fastembed-cache"),
        allow_model_download=False,
    )
    provider._model = SimpleNamespace(model=SimpleNamespace(tokenizer=None))
    assert provider.chunk_text("short text") == ("short text",)


def test_fastembed_without_an_inner_model_falls_back_everywhere() -> None:
    """An embedding model carrying no inner model reaches the narrowing.

    The inner model used to be taken on trust through a cast, so this shape
    raised ``AttributeError`` deep inside a measurement instead of being
    answered.  It now reaches the ``isinstance`` question and trips it, which
    is the input that proves the question is asked at all.
    """
    from codeclone.memory.embedding.fastembed_provider import (
        FastEmbedEmbeddingProvider,
        known_model_max_tokens,
    )

    model_name = "BAAI/bge-small-en-v1.5"
    provider = FastEmbedEmbeddingProvider(
        model_name=model_name,
        dimension=384,
        cache_dir=Path("/tmp/fastembed-cache"),
        allow_model_download=False,
    )
    provider._model = SimpleNamespace()

    assert provider.chunk_text("short text") == ("short text",)
    assert provider.max_sequence_tokens() == known_model_max_tokens(model_name)
    (counts,) = provider.probe_passage_token_counts(["hello"])
    assert counts.raw == counts.effective > 0
    assert provider.estimate_token_counts(["hello"]) == (counts.raw,)


def test_fastembed_estimate_token_counts_uses_tokenize_when_model_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Inner:
        def tokenize(self, documents: list[str]) -> list[_FakeEncoding]:
            return [_FakeEncoding(len(document)) for document in documents]

    provider, _created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=_Inner(),
    )
    provider.embed_documents(["warmup"])
    assert provider.estimate_token_counts(["ab", "abcd"]) == (11, 13)


def test_fastembed_chunk_text_without_encode_ops_returns_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tokenizer that cannot encode is answered, not asserted away.

    The fallback used to be reached by replacing a module helper; the narrowing
    now asks the object itself, so this tokenizer -- which carries a truncation
    limit and nothing else -- reaches the same branch on its own.
    """
    from codeclone.memory.embedding.fastembed_provider import FastEmbedEmbeddingProvider

    class _Tokenizer:
        truncation = _declared_truncation(512)

    provider = FastEmbedEmbeddingProvider(
        model_name="BAAI/bge-small-en-v1.5",
        dimension=384,
        cache_dir=Path("/tmp/fastembed-cache"),
        allow_model_download=False,
    )
    provider._model = SimpleNamespace(model=SimpleNamespace(tokenizer=_Tokenizer()))
    assert provider.chunk_text("hello world") == ("hello world",)


def test_embed_documents_records_observability_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.embedding import embed_documents, embed_query
    from codeclone.models import ObservabilityConfig
    from codeclone.observability import bootstrap, shutdown

    provider = DeterministicHashEmbeddingProvider(dimension=8)
    bootstrap(ObservabilityConfig(enabled=True, profile=False), root=tmp_path)
    try:
        vectors = embed_documents(provider, ["one", "two"])
        query = embed_query(provider, "query")
    finally:
        shutdown()
    assert len(vectors) == 2
    assert len(query) == 8


def test_embed_batching_validation_and_empty_inputs() -> None:
    from codeclone.memory.embedding.batching import (
        EmbedBatchLimits,
        LengthScoredItem,
        pack_adaptive_batches,
        score_lengths,
    )

    with pytest.raises(ValueError, match="length score inputs must align"):
        score_lengths(
            ["a"],
            char_counts=[1],
            token_counts=[1, 2],
            source_kinds=["kind"],
            source_ids=["id"],
        )
    with pytest.raises(ValueError, match="embed batch limits must be positive"):
        pack_adaptive_batches(
            [], limits=EmbedBatchLimits(max_documents=0, max_padded_tokens=8)
        )
    assert (
        pack_adaptive_batches(
            [], limits=EmbedBatchLimits(max_documents=4, max_padded_tokens=32)
        )
        == []
    )
    (batch,) = pack_adaptive_batches(
        (
            LengthScoredItem(
                item="doc",
                char_count=3,
                token_count=2,
                source_kind="memory",
                source_id="id",
            ),
        ),
        limits=EmbedBatchLimits(max_documents=4, max_padded_tokens=32),
    )
    assert batch.items[0].item == "doc"


def test_deterministic_embedding_max_sequence_tokens_is_none() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=16)
    assert provider.max_sequence_tokens() is None


def test_fastembed_embed_records_infer_counters_when_observability_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.models import ObservabilityConfig
    from codeclone.observability import bootstrap, shutdown

    provider, _created = _resolve_fastembed_provider(monkeypatch)
    bootstrap(ObservabilityConfig(enabled=True, profile=False), root=tmp_path)
    try:
        vectors = provider.embed_documents(
            ["one", "two"],
            infer_counters={"lane_memory": 2},
        )
    finally:
        shutdown()
    assert len(vectors) == 2


def test_fastembed_tokenizer_helper_edge_paths() -> None:
    from codeclone.memory.embedding import fastembed_provider as provider_mod

    class _TokenizerWithTruncation:
        truncation = _declared_truncation(128)

    class _TokenizerWithAttributeTruncation:
        """The shape these doubles used to declare, which no vendor ships.

        Honouring it would mean the attribute question is back, so the reader
        answers ``None`` here and lets the model-name default speak.
        """

        truncation = SimpleNamespace(max_length=128)

    assert provider_mod._tokenizer_max_length(_TokenizerWithTruncation()) == 128
    assert (
        provider_mod._tokenizer_max_length(_TokenizerWithAttributeTruncation()) is None
    )
    assert provider_mod._tokenizer_max_length(object()) is None

    class _Encoding:
        ids: ClassVar[list[int]] = [1, 2, 3]

    assert provider_mod._encoding_length(_Encoding()) == 3
    assert provider_mod._encoding_length(object()) == 0

    class _StringIds:
        def __init__(self) -> None:
            self.ids = "abc"

    class _BoolTokenIds:
        def __init__(self) -> None:
            self.ids = [1, True, 3]

    assert provider_mod._encoding_token_ids(object()) == []
    assert provider_mod._encoding_token_ids(_StringIds()) == []
    assert provider_mod._encoding_token_ids(_BoolTokenIds()) == []
    assert provider_mod._encoding_token_ids(_Encoding()) == [1, 2, 3]


def test_fastembed_tokenizer_max_length_rejects_non_positive() -> None:
    from codeclone.memory.embedding import fastembed_provider as provider_mod

    class _TokenizerWithZeroWindow:
        truncation = _declared_truncation(0)

    class _TokenizerWithoutWindow:
        truncation: ClassVar[dict[str, object]] = {"strategy": "longest_first"}

    class _TokenizerWithBooleanWindow:
        truncation: ClassVar[dict[str, object]] = {"max_length": True}

    assert provider_mod._tokenizer_max_length(_TokenizerWithZeroWindow()) is None
    assert provider_mod._tokenizer_max_length(_TokenizerWithoutWindow()) is None
    assert provider_mod._tokenizer_max_length(_TokenizerWithBooleanWindow()) is None


def test_fastembed_verify_chunk_passage_input_raises_on_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.embedding import fastembed_provider as provider_mod
    from codeclone.memory.exceptions import SemanticChunkingInvariantError

    class _OverflowingTokenizer:
        def encode(self, sequence: str, *, add_special_tokens: bool) -> object:
            del sequence, add_special_tokens

            class _Encoding:
                ids: ClassVar[list[int]] = list(range(600))

            return _Encoding()

        def decode(self, ids: list[int]) -> str:
            return "x" * len(ids)

        def no_truncation(self) -> None:
            return None

        def enable_truncation(self, max_length: int) -> None:
            del max_length

    with pytest.raises(
        SemanticChunkingInvariantError, match="exceeds model token window"
    ):
        provider_mod._verify_chunk_passage_input(
            _OverflowingTokenizer(),
            "too-long",
            model_max_tokens=128,
        )


def test_fastembed_probe_without_tokenizer_uses_char_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=SimpleNamespace(tokenizer=None, tokenize=lambda _docs: []),
        vector_value=0.0,
    )
    counts = provider.probe_passage_token_counts(["hello"])
    assert counts[0].raw == counts[0].effective
    assert counts[0].raw > 0


def test_fastembed_chunk_text_raises_when_chunk_cannot_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.memory.exceptions import SemanticChunkingInvariantError

    class _Encoding:
        def __init__(self, ids: list[int]) -> None:
            self.ids = ids

    class _Tokenizer:
        truncation = _declared_truncation(8)

        def encode(self, text: str, *, add_special_tokens: bool = False) -> _Encoding:
            return _Encoding([1] * 32)

        def decode(self, ids: list[int]) -> str:
            return "x" * len(ids)

        def no_truncation(self) -> None:
            return None

        def enable_truncation(self, *, max_length: int) -> None:
            return None

    provider, _created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=SimpleNamespace(tokenizer=_Tokenizer()),
    )
    with pytest.raises(
        SemanticChunkingInvariantError, match="unable to fit passage chunk"
    ):
        provider.chunk_text("overflow")


def test_fastembed_estimate_token_counts_without_tokenize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _created = _resolve_fastembed_provider(
        monkeypatch,
        inner_model=SimpleNamespace(tokenizer=object()),
        vector_value=0.0,
    )
    provider._get_model()
    counts = provider.estimate_token_counts(["hello"])
    assert counts == (4,)


def test_fastembed_max_sequence_tokens_prefers_tokenizer_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live tokenizer's truncation limit wins over the model-name default,
    and every partially-shaped tokenizer falls back instead of crashing."""

    from typing import cast

    from codeclone.memory.embedding.fastembed_provider import (
        known_model_max_tokens,
    )

    _install_fake_fastembed(monkeypatch)
    config = SemanticConfig(embedding_provider="fastembed")
    provider = cast(Any, resolve_embedding_provider(config))
    default_tokens = known_model_max_tokens(provider.model_name)

    embed_query(provider, "load the model")
    inner = provider._inner_text_model()

    for tokenizer in (
        None,
        SimpleNamespace(truncation=None),
        SimpleNamespace(truncation=_declared_truncation(0)),
    ):
        inner.tokenizer = tokenizer
        assert provider.max_sequence_tokens() == default_tokens

    inner.tokenizer = SimpleNamespace(truncation=_declared_truncation(256))
    assert provider.max_sequence_tokens() == 256

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import numbers
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ...budget.estimator import (
    TOKEN_ESTIMATOR_CHARS_APPROX,
    estimate_texts_token_counts,
)
from ...observability import is_observability_enabled, span
from ..exceptions import MemorySemanticUnavailableError, SemanticChunkingInvariantError
from .length import PassageTokenCounts

_PASSAGE_PREFIX = "passage: "

_KNOWN_MODEL_MAX_TOKENS: dict[str, int] = {
    "baai/bge-small-en-v1.5": 512,
    "baai/bge-small-en": 512,
    "baai/bge-base-en-v1.5": 512,
    "baai/bge-base-en": 512,
    "baai/bge-large-en-v1.5": 512,
}


def known_model_max_tokens(model_name: str) -> int:
    return _KNOWN_MODEL_MAX_TOKENS.get(model_name.lower(), 512)


def _tokenizer_max_length(tokenizer: object) -> int | None:
    """The truncation window the tokenizer declares, if it declares one.

    ``tokenizers.Tokenizer.truncation`` answers with a mapping: ``None`` until
    ``enable_truncation`` is called and a ``dict`` afterwards, so the window
    lives under a key.  Measured across 0.13 through 0.23, no released version
    answers with an object -- asking one for a ``max_length`` attribute
    returned ``None`` in every configuration, and every caller then fell
    through to the model-name default without any sign that it had.
    """
    truncation = getattr(tokenizer, "truncation", None)
    if not isinstance(truncation, Mapping):
        return None
    max_length = truncation.get("max_length")
    if isinstance(max_length, bool) or not isinstance(max_length, int):
        return None
    return max_length if max_length > 0 else None


def _encoding_length(encoding: object) -> int:
    ids = getattr(encoding, "ids", None)
    if isinstance(ids, list):
        return len(ids)
    return 0


def _encoding_token_ids(encoding: object) -> list[int]:
    ids = getattr(encoding, "ids", ())
    if not isinstance(ids, Iterable) or isinstance(ids, str | bytes | bytearray):
        return []
    token_ids: list[int] = []
    for token_id in ids:
        if isinstance(token_id, bool) or not isinstance(token_id, int):
            return []
        token_ids.append(token_id)
    return token_ids


# Every parameter below is named as the installed object names it, so a
# vendor rename is a failure of the declaration rather than of the first
# keyword call that reaches production.  fastembed and tokenizers both ship
# ``py.typed``; what hides them from a checker is this module's own dynamic
# import, which mypy resolves no further than ``ModuleType``.  The protocols
# are therefore held against the installed objects by a runtime pin as well,
# and every one of them is reached by an ``isinstance`` question rather than
# by a ``cast`` that asserts the answer.


@runtime_checkable
class _Tokenizer(Protocol):
    """The tokenizer operations a single passage measurement needs."""

    def encode(self, sequence: str, *, add_special_tokens: bool) -> object: ...

    def decode(self, ids: list[int]) -> str: ...

    def no_truncation(self) -> None: ...

    def enable_truncation(self, max_length: int) -> None: ...


@runtime_checkable
class _BatchTokenizer(_Tokenizer, Protocol):
    """A tokenizer that can also measure a whole batch in one call."""

    def encode_batch(self, input: list[str]) -> list[object]: ...


def _special_token_count(tokenizer: _Tokenizer) -> int:
    with_special = _encoding_length(tokenizer.encode("x", add_special_tokens=True))
    without_special = _encoding_length(tokenizer.encode("x", add_special_tokens=False))
    return max(0, with_special - without_special)


def _passage_prefix_token_count(tokenizer: _Tokenizer) -> int:
    return _encoding_length(tokenizer.encode(_PASSAGE_PREFIX, add_special_tokens=False))


def _passage_model_input_token_count(
    tokenizer: _Tokenizer,
    chunk_text: str,
) -> int:
    return _encoding_length(
        tokenizer.encode(f"{_PASSAGE_PREFIX}{chunk_text}", add_special_tokens=True)
    )


def _chunk_payload_token_budget(
    tokenizer: _Tokenizer,
    *,
    model_max_tokens: int,
) -> int:
    special_tokens = _special_token_count(tokenizer)
    prefix_tokens = _passage_prefix_token_count(tokenizer)
    return max(1, model_max_tokens - special_tokens - prefix_tokens)


def _verify_chunk_passage_input(
    tokenizer: _Tokenizer,
    chunk_text: str,
    *,
    model_max_tokens: int,
) -> None:
    raw_tokens = _passage_model_input_token_count(tokenizer, chunk_text)
    if raw_tokens > model_max_tokens:
        raise SemanticChunkingInvariantError(
            "passage chunk exceeds model token window: "
            f"raw_tokens={raw_tokens}, model_max_tokens={model_max_tokens}"
        )


class _TextEmbeddingModel(Protocol):
    """The embedding model this provider drives."""

    def embed(self, documents: list[str]) -> Iterable[object]: ...


class _TextEmbeddingFactory(Protocol):
    """The constructor edge, where the download policy is handed to the vendor.

    ``local_files_only`` is absent from ``TextEmbedding.__init__``'s explicit
    signature and travels through its ``**kwargs``; naming it here is what
    makes a checker confirm the vendor still accepts it.
    """

    def __call__(
        self, *, model_name: str, cache_dir: str, local_files_only: bool
    ) -> _TextEmbeddingModel: ...


@runtime_checkable
class _InnerModelHolder(Protocol):
    """An embedding model that carries an inner model.

    Read-only on purpose: this provider never writes ``model``, and a read-only
    member is covariant, so the vendor may keep a narrower inner type than
    ``object``.  fastembed creates it in ``__init__``, so no class-level
    signature describes it and the ``isinstance`` question below is the check.
    """

    @property
    def model(self) -> object: ...


@runtime_checkable
class _TokenizerHolder(Protocol):
    """The inner model, as far as the tokenizer limit questions need it.

    fastembed declares ``TextEmbedding.model`` as ``TextEmbeddingBase``, which
    carries no tokenizer at all; the attribute is created when the ONNX
    subclass the registry picks loads its model.  The narrowing is therefore a
    real question, and asking it is what a cast used to skip.
    """

    tokenizer: object | None


@runtime_checkable
class _TokenizingTextModel(Protocol):
    """The inner model when it can tokenize a batch of documents.

    Deliberately independent of ``_TokenizerHolder``: an inner model may be
    able to tokenize without exposing a tokenizer, and the token-count path
    uses it in exactly that state.
    """

    def tokenize(self, documents: list[str]) -> list[object]: ...


def _inner_model_of(model: object) -> object | None:
    """The inner model an embedding model carries, if it carries one."""
    return model.model if isinstance(model, _InnerModelHolder) else None


def _tokenizer_of(inner: object) -> object | None:
    """The tokenizer an inner model exposes, if it exposes one at all."""
    return inner.tokenizer if isinstance(inner, _TokenizerHolder) else None


def _drivable_tokenizer(tokenizer: object) -> _Tokenizer | None:
    """The same tokenizer, once it is known to carry the encode operations."""
    return tokenizer if isinstance(tokenizer, _Tokenizer) else None


def _batch_tokenizer(tokenizer: object) -> _BatchTokenizer | None:
    """The same tokenizer, once it is known to measure a whole batch at once."""
    return tokenizer if isinstance(tokenizer, _BatchTokenizer) else None


def _tokenizing_model(inner: object) -> _TokenizingTextModel | None:
    """The inner model, once it is known to tokenize documents."""
    return inner if isinstance(inner, _TokenizingTextModel) else None


class FastEmbedEmbeddingProvider:
    """Local FastEmbed provider for semantic-quality community retrieval.

    FastEmbed remains an optional dependency. The provider runs local ONNX
    embeddings and uses explicit query/passage prefixes for retrieval models
    such as BAAI/bge-small-en-v1.5. Model download is disabled by default; users
    must opt in or pre-populate the cache.
    """

    def __init__(
        self,
        *,
        model_name: str,
        dimension: int,
        cache_dir: Path,
        allow_model_download: bool,
    ) -> None:
        self.model_name = model_name
        self.model_id = f"fastembed:{model_name}"
        self.dimension = dimension
        self.cache_dir = cache_dir
        self.allow_model_download = allow_model_download
        # Verify the optional package eagerly (cheap) so "extra not installed"
        # still fails at construction, but defer the expensive ONNX model load
        # (~hundreds of MB / seconds) to the first embed. A provider that is
        # built but never embeds — e.g. a semantic query against an index that
        # turns out to be unavailable — then costs nothing. Callers degrade
        # gracefully when the model is unavailable at embed time.
        self._text_embedding = self._resolve_text_embedding()
        self._model: _TextEmbeddingModel | None = None

    def _resolve_text_embedding(self) -> _TextEmbeddingFactory:
        """Bind the vendor constructor to the shape this provider calls.

        The import stays dynamic because the extra is optional, and the
        constructor is read as a plain attribute rather than through
        ``getattr`` with a literal: an annotated attribute read is the edge a
        checker can follow back to ``fastembed.TextEmbedding``, which is what
        holds the declared keywords -- ``local_files_only`` included -- against
        the installed signature.
        """
        try:
            fastembed = importlib.import_module("fastembed")
        except ImportError as exc:
            raise MemorySemanticUnavailableError(
                "fastembed embedding provider requires the optional "
                "`codeclone[semantic-fastembed]` extra"
            ) from exc
        try:
            text_embedding: _TextEmbeddingFactory = fastembed.TextEmbedding
        except AttributeError as exc:
            raise MemorySemanticUnavailableError(
                "fastembed package does not expose TextEmbedding"
            ) from exc
        return text_embedding

    def _get_model(self) -> _TextEmbeddingModel:
        if self._model is not None:
            return self._model
        with span(name="memory.embedding.model_load"):
            try:
                model = self._text_embedding(
                    model_name=self.model_name,
                    cache_dir=str(self.cache_dir),
                    local_files_only=not self.allow_model_download,
                )
            except Exception as exc:
                mode = (
                    "download disabled"
                    if not self.allow_model_download
                    else "download allowed"
                )
                raise MemorySemanticUnavailableError(
                    "fastembed embedding model is unavailable "
                    f"({self.model_name}; {mode}; cache={self.cache_dir}): {exc}"
                ) from exc
            self._model = model
        return self._model

    def _inner_text_model(self) -> object:
        """The inner model, undescribed until a caller asks what it carries.

        ``object`` is everything the vendor promises here; each caller narrows
        to the surface it actually uses, so an inner model that can tokenize
        without exposing a tokenizer is answered per question instead of being
        declared to be both.
        """
        return _inner_model_of(self._get_model())

    def _token_window(self, tokenizer: object) -> int:
        """The window every measurement in this provider is taken against.

        One owner for the whole provider: the window the tokenizer declares
        when it declares one, and the model-name default when it does not.
        The callers below differ in how they reach the tokenizer, never in how
        the window is decided.
        """
        return _tokenizer_max_length(tokenizer) or known_model_max_tokens(
            self.model_name
        )

    def max_sequence_tokens(self) -> int | None:
        # Asked before an embed as well, so an unloaded model answers from the
        # model name rather than paying for a load to look at a tokenizer.
        tokenizer = (
            _tokenizer_of(self._inner_text_model()) if self._model is not None else None
        )
        return self._token_window(tokenizer)

    @property
    def estimator_label(self) -> str:
        return "fastembed_tokenizer"

    def probe_passage_token_counts(
        self,
        texts: Sequence[str],
    ) -> tuple[PassageTokenCounts, ...]:
        prefixed = [f"passage: {text}" for text in texts]
        inner = self._inner_text_model()
        tokenizer = _tokenizer_of(inner)
        tokenizing = _tokenizing_model(inner)
        if tokenizer is None or tokenizing is None:
            counts = estimate_texts_token_counts(
                prefixed,
                estimator=TOKEN_ESTIMATOR_CHARS_APPROX,
            )
            return tuple(
                PassageTokenCounts(raw=count, effective=count) for count in counts
            )
        max_length = self._token_window(tokenizer)
        batch = _batch_tokenizer(tokenizer)
        if batch is not None:
            batch.no_truncation()
            raw_encodings = batch.encode_batch(prefixed)
            raw_counts = tuple(_encoding_length(encoding) for encoding in raw_encodings)
            batch.enable_truncation(max_length=max_length)
            effective_encodings = tokenizing.tokenize(prefixed)
            effective_counts = tuple(
                _encoding_length(encoding) for encoding in effective_encodings
            )
            return tuple(
                PassageTokenCounts(raw=raw, effective=effective)
                for raw, effective in zip(raw_counts, effective_counts, strict=True)
            )
        effective_counts = self.estimate_token_counts(texts)
        return tuple(
            PassageTokenCounts(raw=count, effective=count) for count in effective_counts
        )

    def chunk_text(self, text: str) -> tuple[str, ...]:
        tokenizer = _drivable_tokenizer(_tokenizer_of(self._inner_text_model()))
        if tokenizer is None:
            return (text,)
        max_length = self._token_window(tokenizer)
        tokenizer.no_truncation()
        try:
            if _passage_model_input_token_count(tokenizer, text) <= max_length:
                _verify_chunk_passage_input(
                    tokenizer, text, model_max_tokens=max_length
                )
                return (text,)
            content_encoding = tokenizer.encode(text, add_special_tokens=False)
            content_ids = _encoding_token_ids(content_encoding)
            payload_budget = _chunk_payload_token_budget(
                tokenizer,
                model_max_tokens=max_length,
            )
            chunks: list[str] = []
            start = 0
            while start < len(content_ids):
                end = min(start + payload_budget, len(content_ids))
                while end > start:
                    chunk = tokenizer.decode(content_ids[start:end])
                    if _passage_model_input_token_count(tokenizer, chunk) <= max_length:
                        break
                    end -= 1
                if end <= start:
                    raise SemanticChunkingInvariantError(
                        "unable to fit passage chunk within model token window "
                        f"at content offset {start}"
                    )
                _verify_chunk_passage_input(
                    tokenizer, chunk, model_max_tokens=max_length
                )
                chunks.append(chunk)
                start = end
            return tuple(chunks)
        finally:
            tokenizer.enable_truncation(max_length=max_length)

    def estimate_token_counts(self, texts: Sequence[str]) -> tuple[int, ...]:
        prefixed = [f"passage: {text}" for text in texts]
        if self._model is None:
            return estimate_texts_token_counts(
                prefixed,
                estimator=TOKEN_ESTIMATOR_CHARS_APPROX,
            )
        tokenizing = _tokenizing_model(self._inner_text_model())
        if tokenizing is None:
            return estimate_texts_token_counts(
                prefixed,
                estimator=TOKEN_ESTIMATOR_CHARS_APPROX,
            )
        encodings = tokenizing.tokenize(prefixed)
        return tuple(len(getattr(encoding, "ids", ())) for encoding in encodings)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        (vector,) = self._embed_prefixed([f"query: {text}"])
        return vector

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        infer_counters: Mapping[str, int] | None = None,
    ) -> list[list[float]]:
        return self._embed_prefixed(
            [f"passage: {text}" for text in texts],
            infer_counters=infer_counters,
        )

    def _embed_prefixed(
        self,
        texts: Sequence[str],
        *,
        infer_counters: Mapping[str, int] | None = None,
    ) -> list[list[float]]:
        with span(name="memory.embedding.infer") as infer_span:
            if is_observability_enabled():
                infer_span.set_counter("batch", len(texts))
                if infer_counters is not None:
                    for key, value in sorted(infer_counters.items()):
                        infer_span.set_counter(key, value)
            try:
                raw_vectors = list(self._get_model().embed(list(texts)))
            except Exception as exc:
                raise MemorySemanticUnavailableError(
                    f"fastembed embedding failed for model {self.model_name}: {exc}"
                ) from exc
            vectors = [self._coerce_vector(vector) for vector in raw_vectors]
            for vector in vectors:
                if len(vector) != self.dimension:
                    raise MemorySemanticUnavailableError(
                        "fastembed embedding dimension mismatch: "
                        f"expected {self.dimension}, got {len(vector)} for "
                        f"{self.model_name}"
                    )
            return vectors

    @staticmethod
    def _coerce_vector(raw_vector: object) -> list[float]:
        if not isinstance(raw_vector, Iterable) or isinstance(raw_vector, str):
            raise MemorySemanticUnavailableError(
                "fastembed returned a non-iterable embedding vector"
            )
        vector: list[float] = []
        for value in raw_vector:
            # Real fastembed output is a numpy float32 array; iterating it yields
            # numpy.float32 scalars, which are NOT Python `float`/`int` subclasses
            # but ARE registered as numbers.Real. numbers.Real also excludes str
            # (avoiding float("abc") surfacing a bare ValueError), while bool is
            # excluded explicitly so True/False are not coerced to 1.0/0.0.
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise MemorySemanticUnavailableError(
                    "fastembed returned a non-numeric embedding vector"
                )
            vector.append(float(value))
        return vector


__all__ = ["FastEmbedEmbeddingProvider", "known_model_max_tokens"]

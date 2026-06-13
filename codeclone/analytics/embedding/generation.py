# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from ...config.analytics import AnalyticsConfig
from ...contracts import CORPUS_EMBEDDING_CONTRACT_VERSION
from ...memory.embedding import EmbeddingProvider, embed_documents
from ...memory.embedding.fastembed_provider import FastEmbedEmbeddingProvider
from ...report.meta import current_report_timestamp_utc
from ..contracts import CorpusItemRecord, EmbeddingGenerationRecord, EmbeddingItemRecord
from ..exceptions import AnalyticsCapabilityError
from ..store.protocols import CorpusStore
from ..store.vectors_lancedb import AnalyticsVectorStore, vector_digest, vector_row_key


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    embedding_generation_id: str
    item_count: int


def _resolve_fastembed_provider(config: AnalyticsConfig) -> FastEmbedEmbeddingProvider:
    try:
        importlib.import_module("fastembed")
    except ImportError as exc:
        raise AnalyticsCapabilityError(
            "fastembed is required for analytics embeddings; "
            "install with: uv sync --extra analytics"
        ) from exc
    return FastEmbedEmbeddingProvider(
        model_name=config.embedding_model,
        dimension=config.embedding_dimension,
        cache_dir=config.embedding_cache_dir,
        allow_model_download=config.allow_model_download,
    )


def _provider_package_version(provider_id: str) -> str:
    if provider_id == "fastembed":
        module = importlib.import_module("fastembed")
        return str(getattr(module, "__version__", "unknown"))
    return "unknown"


def generate_embeddings_for_snapshot(
    *,
    store: CorpusStore,
    vector_store: AnalyticsVectorStore,
    config: AnalyticsConfig,
    snapshot_id: str,
    provider: EmbeddingProvider | None = None,
) -> EmbeddingBatchResult:
    items = store.list_items(snapshot_id)
    if not items:
        msg = f"snapshot has no items: {snapshot_id}"
        raise ValueError(msg)
    active_provider = provider or _resolve_fastembed_provider(config)
    texts = [item.normalized_text for item in items]
    vectors = embed_documents(active_provider, texts)
    generation_id = f"emb-{uuid.uuid4().hex[:16]}"
    provider_id = active_provider.model_id.split(":", 1)[0]
    if provider_id not in {"fastembed", "diagnostic-hash-v1"}:
        provider_id = (
            "fastembed" if "fastembed" in active_provider.model_id else "custom"
        )
    if active_provider.model_id.startswith("fastembed:"):
        provider_id = "fastembed"
    model_id = (
        active_provider.model_id.split(":", 1)[1]
        if ":" in active_provider.model_id
        else active_provider.model_id
    )
    generation = EmbeddingGenerationRecord(
        embedding_generation_id=generation_id,
        provider_id=provider_id,
        provider_package_version=_provider_package_version(provider_id),
        model_id=model_id,
        model_revision=None,
        model_artifact_fingerprint=None,
        exact_model_artifact_reproducibility=False,
        dimensions=active_provider.dimension,
        embedding_contract_version=CORPUS_EMBEDDING_CONTRACT_VERSION,
        embedding_similarity_metric="cosine",
        vector_preprocessing="l2_normalize",
        created_at_utc=current_report_timestamp_utc(),
    )
    store.insert_embedding_generation(generation)
    embedding_items: list[EmbeddingItemRecord] = []
    vector_rows: list[dict[str, object]] = []
    for item, vector in zip(items, vectors, strict=True):
        row_key = vector_row_key(
            embedding_generation_id=generation_id,
            snapshot_item_id=item.snapshot_item_id,
        )
        digest = vector_digest(vector)
        embedding_items.append(
            EmbeddingItemRecord(
                embedding_generation_id=generation_id,
                snapshot_item_id=item.snapshot_item_id,
                vector_row_key=row_key,
                vector_digest=digest,
                dimensions=len(vector),
            )
        )
        vector_rows.append(
            {
                "snapshot_item_id": item.snapshot_item_id,
                "vector": vector,
            }
        )
    store.insert_embedding_items(embedding_items)
    stored_items = store.list_embedding_items(embedding_generation_id=generation_id)
    if len(stored_items) != len(embedding_items):
        msg = (
            "embedding item count mismatch after persist: "
            f"expected {len(embedding_items)}, stored {len(stored_items)}"
        )
        raise ValueError(msg)
    vector_store.write_vectors(
        embedding_generation_id=generation_id,
        rows=vector_rows,
    )
    store.commit()
    return EmbeddingBatchResult(
        embedding_generation_id=generation_id,
        item_count=len(items),
    )


def load_snapshot_vectors(
    *,
    vector_store: AnalyticsVectorStore,
    embedding_generation_id: str,
    items: Sequence[CorpusItemRecord],
) -> list[list[float]]:
    item_ids = [item.snapshot_item_id for item in items]
    loaded = vector_store.read_vectors(
        embedding_generation_id=embedding_generation_id,
        snapshot_item_ids=item_ids,
    )
    vectors: list[list[float]] = []
    for item_id in item_ids:
        vector = loaded.get(item_id)
        if vector is None:
            msg = f"missing vector for snapshot item: {item_id}"
            raise ValueError(msg)
        vectors.append(vector)
    return vectors


__all__ = [
    "EmbeddingBatchResult",
    "generate_embeddings_for_snapshot",
    "load_snapshot_vectors",
]

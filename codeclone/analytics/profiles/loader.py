# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import math
import re
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ...contracts import (
    CORPUS_EMBEDDING_CONTRACT_VERSION,
    CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION,
)
from ...utils.json_io import json_text, read_json_object
from ..contracts import (
    INTENT_REPRESENTATION_DESCRIPTION,
    INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
)
from ..corpus.keys import sha256_hex
from ..exceptions import AnalyticsWorkflowError
from .models import (
    ClusteringProfileManifest,
    ProfileApplicability,
    ProfileRankingPolicy,
    ProfileSearchSpace,
    ProfileSuitabilityRules,
)

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_CANONICAL_REPRESENTATION_KINDS = frozenset(
    {
        INTENT_REPRESENTATION_DESCRIPTION,
        INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
    }
)


class _ApplicabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_size_class: Literal["small_intent"]
    min_record_count: int | None = Field(default=None, ge=0)
    max_record_count: int | None = Field(default=None, ge=0)
    embedding_contract_versions: tuple[str, ...] = (CORPUS_EMBEDDING_CONTRACT_VERSION,)

    @field_validator("embedding_contract_versions")
    @classmethod
    def _versions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({item.strip() for item in value if item.strip()}))
        if not normalized:
            raise ValueError("embedding_contract_versions must not be empty")
        return normalized

    @model_validator(mode="after")
    def _bounds(self) -> _ApplicabilityModel:
        if (
            self.min_record_count is not None
            and self.max_record_count is not None
            and self.min_record_count > self.max_record_count
        ):
            raise ValueError("min_record_count must be <= max_record_count")
        return self


class _SearchSpaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pca_dimensions: tuple[int, ...]
    min_cluster_size: tuple[int, ...]
    min_samples: tuple[int, ...]
    cluster_selection_method: tuple[Literal["eom", "leaf"], ...]

    @field_validator("pca_dimensions", "min_cluster_size", "min_samples")
    @classmethod
    def _positive_axis(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value or any(item <= 0 for item in value):
            raise ValueError("profile search axes require positive integers")
        return tuple(sorted(set(value)))

    @field_validator("cluster_selection_method")
    @classmethod
    def _method_axis(
        cls,
        value: tuple[Literal["eom", "leaf"], ...],
    ) -> tuple[Literal["eom", "leaf"], ...]:
        if not value:
            raise ValueError("cluster_selection_method must not be empty")
        return cast(
            "tuple[Literal['eom', 'leaf'], ...]",
            tuple(sorted(set(value))),
        )


class _SuitabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_non_noise_cluster_count: int | None = Field(default=None, ge=0)
    max_non_noise_cluster_count: int | None = Field(default=None, ge=0)
    max_dominant_cluster_ratio: float | None = None
    min_dominant_cluster_ratio: float | None = None
    min_noise_ratio: float | None = None
    max_noise_ratio: float | None = None
    min_non_noise_count: int | None = Field(default=None, ge=0)

    @field_validator(
        "max_dominant_cluster_ratio",
        "min_dominant_cluster_ratio",
        "min_noise_ratio",
        "max_noise_ratio",
    )
    @classmethod
    def _ratio(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("profile suitability ratios must be finite in [0, 1]")
        return value

    @model_validator(mode="after")
    def _bounds(self) -> _SuitabilityModel:
        _validate_pair(
            self.min_non_noise_cluster_count,
            self.max_non_noise_cluster_count,
            "non-noise cluster count",
        )
        _validate_pair(
            self.min_dominant_cluster_ratio,
            self.max_dominant_cluster_ratio,
            "dominant cluster ratio",
        )
        _validate_pair(self.min_noise_ratio, self.max_noise_ratio, "noise ratio")
        return self


class _RankingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_score_weight: float
    cluster_count_weight: float
    cluster_count_direction: Literal["prefer_higher", "prefer_lower", "neutral"]
    noise_weight: float
    noise_direction: Literal["prefer_lower", "prefer_higher", "neutral"]

    @field_validator(
        "base_score_weight",
        "cluster_count_weight",
        "noise_weight",
    )
    @classmethod
    def _weight(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("profile ranking weights must be finite and non-negative")
        return value


class _ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_schema_version: str
    profile_id: str
    profile_version: str
    lane: Literal["intent"]
    representation_kinds: tuple[str, ...]
    label: str
    description: str
    applicability: _ApplicabilityModel
    primary_space: _SearchSpaceModel
    suitability: _SuitabilityModel
    ranking: _RankingModel

    @field_validator("manifest_schema_version")
    @classmethod
    def _schema_version(cls, value: str) -> str:
        if value != CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported profile manifest schema version: {value}")
        return value

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or _PROFILE_ID_RE.fullmatch(normalized) is None:
            raise ValueError("profile_id must be a non-empty canonical identifier")
        return normalized

    @field_validator("profile_version")
    @classmethod
    def _profile_version(cls, value: str) -> str:
        normalized = value.strip()
        if _SEMVER_RE.fullmatch(normalized) is None:
            raise ValueError("profile_version must be valid semver")
        return normalized

    @field_validator("label", "description")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("profile label and description must not be empty")
        return normalized

    @field_validator("representation_kinds")
    @classmethod
    def _representation_kinds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("representation_kinds must not be empty")
        aliases = sorted(set(value) - _CANONICAL_REPRESENTATION_KINDS)
        if aliases:
            raise ValueError(
                "profile manifest uses non-canonical representation_kind: "
                + ", ".join(aliases)
            )
        return tuple(sorted(set(value)))


def load_manifest_file(path: Path) -> ClusteringProfileManifest:
    try:
        payload = read_json_object(path)
    except (OSError, TypeError, ValueError) as exc:
        raise AnalyticsWorkflowError(
            f"cannot load analytics profile manifest {path}: {exc}"
        ) from exc
    return load_manifest_value(payload)


def load_manifest_value(payload: dict[str, object]) -> ClusteringProfileManifest:
    try:
        model = _ManifestModel.model_validate(payload)
    except ValidationError as exc:
        raise AnalyticsWorkflowError(
            f"invalid analytics profile manifest: {exc}"
        ) from exc
    return _to_manifest(model)


def load_bundled_profiles() -> dict[str, ClusteringProfileManifest]:
    manifests = files("codeclone.analytics.profiles").joinpath("manifests")
    result: dict[str, ClusteringProfileManifest] = {}
    for resource in sorted(manifests.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".json"):
            continue
        try:
            import orjson

            payload = orjson.loads(resource.read_bytes())
        except (OSError, ValueError) as exc:
            raise AnalyticsWorkflowError(
                f"cannot load bundled analytics profile {resource.name}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise AnalyticsWorkflowError(
                f"bundled analytics profile must be an object: {resource.name}"
            )
        manifest = load_manifest_value(payload)
        if manifest.profile_id in result:
            raise AnalyticsWorkflowError(
                f"conflicting profile manifest for profile_id: {manifest.profile_id}"
            )
        result[manifest.profile_id] = manifest
    return result


def manifest_value(manifest: ClusteringProfileManifest) -> dict[str, object]:
    return asdict(manifest)


def canonical_manifest_json(manifest: ClusteringProfileManifest) -> str:
    return json_text(manifest_value(manifest), sort_keys=True)


def profile_manifest_digest(manifest: ClusteringProfileManifest) -> str:
    return sha256_hex(canonical_manifest_json(manifest))


def _to_manifest(model: _ManifestModel) -> ClusteringProfileManifest:
    applicability = model.applicability
    primary = model.primary_space
    suitability = model.suitability
    ranking = model.ranking
    return ClusteringProfileManifest(
        manifest_schema_version=model.manifest_schema_version,
        profile_id=model.profile_id,
        profile_version=model.profile_version,
        lane=model.lane,
        representation_kinds=model.representation_kinds,
        label=model.label,
        description=model.description,
        applicability=ProfileApplicability(
            corpus_size_class=applicability.corpus_size_class,
            min_record_count=applicability.min_record_count,
            max_record_count=applicability.max_record_count,
            embedding_contract_versions=applicability.embedding_contract_versions,
        ),
        primary_space=ProfileSearchSpace(
            pca_dimensions=primary.pca_dimensions,
            min_cluster_size=primary.min_cluster_size,
            min_samples=primary.min_samples,
            cluster_selection_method=primary.cluster_selection_method,
        ),
        suitability=ProfileSuitabilityRules(**suitability.model_dump()),
        ranking=ProfileRankingPolicy(**ranking.model_dump()),
    )


def _validate_pair(
    minimum: int | float | None,
    maximum: int | float | None,
    label: str,
) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"minimum {label} must be <= maximum")


__all__ = [
    "canonical_manifest_json",
    "load_bundled_profiles",
    "load_manifest_file",
    "load_manifest_value",
    "manifest_value",
    "profile_manifest_digest",
]

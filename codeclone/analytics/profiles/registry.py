# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from ..exceptions import AnalyticsWorkflowError
from .loader import (
    load_bundled_profiles,
    load_manifest_file,
    profile_manifest_digest,
)
from .models import ClusteringProfileManifest


@dataclass(frozen=True, slots=True)
class ProfileRegistry:
    profiles: Mapping[str, ClusteringProfileManifest]
    default_profile_id: str | None
    sources: Mapping[str, str]


def resolve_profile_registry(
    *,
    profile_paths: Sequence[Path] = (),
    default_profile_id: str | None = None,
    bundled_dir: Path | None = None,
) -> ProfileRegistry:
    sources: dict[str, str]
    if bundled_dir is None:
        bundled = load_bundled_profiles()
        sources = {
            profile_id: f"bundled:{_bundled_filename(profile_id)}"
            for profile_id in bundled
        }
    else:
        bundled = {}
        sources = {}
        for path in sorted(bundled_dir.glob("*.json")):
            manifest = load_manifest_file(path)
            if manifest.profile_id in bundled:
                raise AnalyticsWorkflowError(
                    "conflicting profile manifest for profile_id: "
                    f"{manifest.profile_id}"
                )
            bundled[manifest.profile_id] = manifest
            sources[manifest.profile_id] = f"bundled:{path.name}"
    profiles = dict(bundled)
    for path in profile_paths:
        manifest = load_manifest_file(path)
        existing = profiles.get(manifest.profile_id)
        if existing is not None and profile_manifest_digest(
            existing
        ) != profile_manifest_digest(manifest):
            raise AnalyticsWorkflowError(
                f"conflicting profile manifest for profile_id: {manifest.profile_id}"
            )
        if existing is None:
            profiles[manifest.profile_id] = manifest
            sources[manifest.profile_id] = str(path)
    if default_profile_id is not None and default_profile_id not in profiles:
        raise AnalyticsWorkflowError(f"unknown analytics profile: {default_profile_id}")
    return ProfileRegistry(
        profiles=MappingProxyType(dict(sorted(profiles.items()))),
        default_profile_id=default_profile_id,
        sources=MappingProxyType(dict(sorted(sources.items()))),
    )


def get_profile(
    registry: ProfileRegistry,
    profile_id: str,
) -> ClusteringProfileManifest:
    try:
        return registry.profiles[profile_id]
    except KeyError as exc:
        raise AnalyticsWorkflowError(
            f"unknown analytics profile: {profile_id}"
        ) from exc


def list_profiles(registry: ProfileRegistry) -> tuple[str, ...]:
    return tuple(sorted(registry.profiles))


def _bundled_filename(profile_id: str) -> str:
    manifests = files("codeclone.analytics.profiles").joinpath("manifests")
    expected = f"{profile_id}.json"
    for resource in manifests.iterdir():
        if resource.name == expected:
            return resource.name
    return expected


__all__ = [
    "ProfileRegistry",
    "get_profile",
    "list_profiles",
    "resolve_profile_registry",
]

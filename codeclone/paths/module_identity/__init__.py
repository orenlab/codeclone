# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Versioned file/module identity and portable-path contracts."""

from .manifest import (
    LEGACY_MODULE_IDENTITY_KILL_INVENTORY,
    ModuleIdentityCollisionError,
    build_module_identity_manifest,
    manifest_digest,
    manifest_json,
)
from .portable import normalize_identity_path, validate_portable_paths
from .resolver import (
    normalize_import_mounts,
    repository_relative_path,
    resolve_source_identity,
)

__all__ = [
    "LEGACY_MODULE_IDENTITY_KILL_INVENTORY",
    "ModuleIdentityCollisionError",
    "build_module_identity_manifest",
    "manifest_digest",
    "manifest_json",
    "normalize_identity_path",
    "normalize_import_mounts",
    "repository_relative_path",
    "resolve_source_identity",
    "validate_portable_paths",
]

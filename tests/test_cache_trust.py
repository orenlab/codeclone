# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Red-first trust laws for the cache persistence layer.

These pin three asserted persistence.trust review claims (Enacta @ ae8b4abf)
with executable evidence, not prose:

* Candidate 1 - the envelope ``v`` (the generation gate) must live inside the
  signed scope, so a migration/backup that rewrites ``v`` without re-signing is
  refused instead of trusted.
* Candidate 2 - the module-dependent reuse profile must be a function of every
  detector policy whose change can move a dependent-lane fact. The
  design-metrics algorithm revision is proven here; the closed-catalog families
  (security surfaces, runtime reachability) are pinned as documented,
  still-open gaps that need an owner-created contracts constant.
* Candidate 3 - the cache "signature" is a keyless checksum. This pins the
  CURRENT behavior (a hand-forged valid checksum is accepted) so the keyless
  nature is on the record while the vocabulary fork is an owner decision.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

import codeclone.cache.reuse as cache_reuse
from codeclone.cache.integrity import sign_cache_envelope
from codeclone.cache.reuse import build_module_dependent_profile
from codeclone.cache.store import Cache
from codeclone.cache.versioning import CacheStatus
from codeclone.models import DigestObject
from tests.test_cache import (
    _save_single_cache_entry,
)

_NEUTRAL = DigestObject(
    domain="codeclone.cache.profile.neutral.v1",
    algorithm="sha256",
    value="1" * 64,
)
_MANIFEST = DigestObject(
    domain="codeclone.module-registry.v1",
    algorithm="sha256",
    value="a" * 64,
)


def _reload_with_forged_envelope(
    cache_path: Path, mutate: Callable[[dict[str, object]], None]
) -> Cache:
    """Read the on-disk envelope, let a test forge it, then reload the cache."""

    raw = cast(dict[str, object], json.loads(cache_path.read_text("utf-8")))
    mutate(raw)
    cache_path.write_text(json.dumps(raw), "utf-8")
    loaded = Cache(cache_path, root=cache_path.parent)
    loaded.load()
    return loaded


def _dependent_profile_digest_under(
    monkeypatch: pytest.MonkeyPatch, policy_version_name: str
) -> tuple[str, str]:
    """Digest the dependent profile before/after shifting one policy version.

    A shift that the profile binds moves the digest; one it ignores (or a
    version name the profile never imports) does not. Missing names raise on
    ``setattr``, which the caller pins as a still-open gap.
    """

    baseline = build_module_dependent_profile(
        neutral_profile=_NEUTRAL,
        module_manifest_digest=_MANIFEST,
        collect_api_surface=False,
    )
    monkeypatch.setattr(cache_reuse, policy_version_name, "999")
    shifted = build_module_dependent_profile(
        neutral_profile=_NEUTRAL,
        module_manifest_digest=_MANIFEST,
        collect_api_surface=False,
    )
    return baseline.value, shifted.value


# --------------------------------------------------------------------------- #
# Candidate 1 - envelope ``v`` must be inside the signed scope.
# --------------------------------------------------------------------------- #


def test_cache_envelope_v_is_inside_signed_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rewriting only top-level ``v`` (payload/sig byte-identical) must fail.

    The review predicts the pre-fix code returns OK with fully decoded records:
    the sig covers only ``payload`` and ``v`` is compared before the sig check,
    so a runtime whose generation gate equals the forged mark trusts a payload
    it never signed under that mark. That is exactly the migration / backup /
    edit-in-place desync candidate 1 names.

    Cross-defect witness (Enacta): this test asserts the LOAD-BEARING half of a
    coupled pair. The envelope-``v`` defect existed only as the product of an
    unsigned ``v`` AND the ``{11, 17}`` unit-row decode tolerance in
    ``_wire_decode`` (dead-by-gate, owned elsewhere). Closing either half closes
    it; candidate 1 closes the ``v``-signing half here. This is why signing
    ``v`` is not redundant with the ``v == CACHE_VERSION`` gate - it is what
    keeps a retagged generation from reaching that still-tolerant decoder.
    Removing ``v`` from the signed scope while that tolerance survives
    reassembles the cross-defect (the mutation run proves this pin goes red).
    """

    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    genuine_mark = cast(str, json.loads(cache_path.read_text("utf-8"))["v"])
    forged_mark = f"{genuine_mark}-migrated"

    # Load with a runtime whose generation gate equals the forged mark, so the
    # version gate passes and only the signed scope can catch the desync.
    monkeypatch.setattr(Cache, "_CACHE_VERSION", forged_mark)
    # Tamper ONLY the generation gate; payload and sig stay byte-identical.
    loaded = _reload_with_forged_envelope(
        cache_path, lambda raw: raw.__setitem__("v", forged_mark)
    )

    assert loaded.load_status is CacheStatus.INTEGRITY_FAILED


def test_sign_cache_envelope_binds_the_generation_gate() -> None:
    """The narrow form: the signed digest must change when ``v`` changes.

    Two envelopes differing only in ``v`` must not share a signature. Pre-fix
    there is no envelope signer that takes ``v`` at all (the input does not
    exist); post-fix the digest binds it.
    """

    payload = {"py": "cp314", "fp": "3", "files": {}}
    assert sign_cache_envelope("3.4", payload) != sign_cache_envelope("3.5", payload)


# --------------------------------------------------------------------------- #
# Candidate 2 - the dependent profile must version every guarded policy.
# --------------------------------------------------------------------------- #


def test_dependent_profile_versions_design_metrics_algorithm_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """class_metrics (cbo/lcom4/risk) ride the dependent lane; a design-metrics
    algorithm-revision bump must move the dependent-profile digest, or a warm
    hit serves stale metrics values.

    Pre-fix ``build_module_dependent_profile`` neither imports nor consumes
    ``DESIGN_METRICS_ALGORITHM_REVISION``, so this is red immediately.
    """

    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "DESIGN_METRICS_ALGORITHM_REVISION"
    )
    assert baseline != shifted


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CONFIRMED-OPEN candidate 2 gap: the security_surfaces catalog "
        "(closed enum, entries.py) rides the dependent lane, but the dependent "
        "profile carries no version for it. Closing it needs an owner-created "
        "SECURITY_SURFACE_CATALOG_VERSION in contracts (fenced this wave). "
        "Remove this xfail when the constant is wired."
    ),
)
def test_dependent_profile_versions_security_surface_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "SECURITY_SURFACE_CATALOG_VERSION"
    )
    assert baseline != shifted


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CONFIRMED-OPEN candidate 2 gap: the runtime_reachability catalog "
        "(closed framework/edge enums, entries.py) rides the dependent lane, "
        "but the dependent profile carries no version for it. Needs an "
        "owner-created RUNTIME_REACHABILITY_CATALOG_VERSION in contracts "
        "(fenced this wave). Remove this xfail when the constant is wired."
    ),
)
def test_dependent_profile_versions_runtime_reachability_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, shifted = _dependent_profile_digest_under(
        monkeypatch, "RUNTIME_REACHABILITY_CATALOG_VERSION"
    )
    assert baseline != shifted


# --------------------------------------------------------------------------- #
# Candidate 3 - the "signature" is a keyless checksum (owner decision, no fix).
# --------------------------------------------------------------------------- #


def test_cache_signature_is_keyless_checksum_not_authentication(
    tmp_path: Path,
) -> None:
    """Pin the CURRENT behavior: a hand-forged valid checksum is accepted.

    An actor with only the public payload and the public algorithm - no secret
    material of any kind - injects a cached fact and re-mints a "signature" that
    the loader accepts. This proves the mechanism is a checksum (catches
    accidental corruption) and not authentication (nothing an attacker cannot
    reproduce). It stays keyless after candidate 1: binding ``v`` into the
    signed scope changes WHAT is summed, not that the sum needs a secret; the
    forgery here re-mints over the current public envelope algorithm. Whether
    that guarantee is enough is the owner's fork; this test only records that
    today it is keyless.
    """

    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    def forge(raw: dict[str, object]) -> None:
        payload = cast(dict[str, object], raw["payload"])
        files = cast(dict[str, object], payload["files"])
        (genuine_key,) = tuple(files)
        # Inject a cached fact with no key, no secret - just the public payload.
        files["forged.py"] = copy.deepcopy(files[genuine_key])
        # Re-mint the "signature" from the public algorithm alone (keyless).
        raw["sig"] = sign_cache_envelope(cast(str, raw["v"]), payload)

    loaded = _reload_with_forged_envelope(cache_path, forge)

    assert loaded.load_status is CacheStatus.OK
    assert loaded.get_file_entry("forged.py") is not None

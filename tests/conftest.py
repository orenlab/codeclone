from __future__ import annotations

from collections.abc import Callable

import pytest

from codeclone.contracts import REPORT_SCHEMA_VERSION

ReportMetaFactory = Callable[..., dict[str, object]]


@pytest.fixture
def report_meta_factory() -> ReportMetaFactory:
    def _make(**overrides: object) -> dict[str, object]:
        meta: dict[str, object] = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "codeclone_version": "1.4.0",
            "python_version": "3.13",
            "python_tag": "cp313",
            "baseline_path": "/repo/codeclone.baseline.json",
            "baseline_fingerprint_version": "1",
            "baseline_schema_version": "1.0",
            "baseline_python_tag": "cp313",
            "baseline_generator_name": "codeclone",
            "baseline_generator_version": "1.4.0",
            "baseline_payload_sha256": "a" * 64,
            "baseline_payload_sha256_verified": True,
            "baseline_loaded": True,
            "baseline_status": "ok",
            "cache_path": "/repo/.cache/codeclone/cache.json",
            "cache_schema_version": "1.2",
            "cache_status": "ok",
            "cache_used": True,
            "files_skipped_source_io": 0,
        }
        meta.update(overrides)
        return meta

    return _make

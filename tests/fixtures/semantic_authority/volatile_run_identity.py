from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def report_run_identity(report_document: Mapping[str, object]) -> str:
    report_bytes = json.dumps(
        report_document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(report_bytes).hexdigest()


def publish_run_reference(report_document: Mapping[str, object]) -> dict[str, str]:
    return {
        "run_id": report_run_identity(report_document),
        "report_digest": report_run_identity(report_document),
    }

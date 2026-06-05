# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from ..config.pyproject_loader import ConfigValidationError, load_pyproject_config
from .validation import (
    DEFAULT_AUDIT_PATH,
    DEFAULT_AUDIT_PAYLOADS,
    DEFAULT_AUDIT_RETENTION_DAYS,
    DEFAULT_AUDIT_TOKEN_ESTIMATOR,
    resolve_audit_path,
    validate_payload_mode,
    validate_retention_days,
    validate_token_estimator,
)
from .writer import AuditWriter, NullAuditWriter, SqliteAuditWriter


def open_audit_writer_for_root(root_path: Path) -> AuditWriter:
    """Return a configured audit writer for ``root_path``, or ``NullAuditWriter``."""

    try:
        config = load_pyproject_config(root_path)
    except (ConfigValidationError, OSError):
        return NullAuditWriter()
    if not bool(config.get("audit_enabled", False)):
        return NullAuditWriter()
    try:
        db_path = resolve_audit_path(
            root_path=root_path,
            value=config.get("audit_path", DEFAULT_AUDIT_PATH),
        )
        payloads = validate_payload_mode(
            config.get("audit_payloads", DEFAULT_AUDIT_PAYLOADS)
        )
        retention_days = validate_retention_days(
            config.get("audit_retention_days", DEFAULT_AUDIT_RETENTION_DAYS)
        )
        token_estimator = validate_token_estimator(
            config.get("audit_token_estimator", DEFAULT_AUDIT_TOKEN_ESTIMATOR)
        )
        return SqliteAuditWriter(
            db_path=db_path,
            payloads=payloads,
            retention_days=retention_days,
            token_estimator=token_estimator,
        )
    except Exception:
        return NullAuditWriter()


__all__ = ["open_audit_writer_for_root"]

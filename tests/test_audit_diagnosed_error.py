# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The audit configuration family is a diagnosed user error, not a fault.

Its own file, and the reason is the ring ratchet rather than taste: the audit
package is ``r2p`` and the configuration packages are ``r2``, so one module
cannot assert both classifications without importing across a frozen edge.
The classification itself is one property with one home per ring; the
envelope that reads it is pinned in ``test_diagnosed_user_errors``.
"""

from __future__ import annotations

from codeclone.audit.validation import AuditConfigError
from codeclone.contracts.errors import DiagnosedUserError


def test_an_invalid_audit_path_is_classified_diagnosed() -> None:
    """Raised only while validating a path the user configured.

    A sibling left off the classification is a sibling the CLI envelope will
    report as "Unexpected exception" with a bug-report link, which is the
    defect measured on the observability family on 2026-09-01.
    """

    assert issubclass(AuditConfigError, DiagnosedUserError)
    assert isinstance(
        AuditConfigError("audit_path must be a string"), DiagnosedUserError
    )

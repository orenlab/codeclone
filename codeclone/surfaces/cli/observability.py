# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI surface for the platform observability store (``codeclone observability``).

Read-only: opens the per-root store read-only, builds the ``TraceView`` read
model, and renders it as JSON or branded HTML. Never writes the store.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ...contracts import ExitCode
from ...observability.render_html import render_trace_html
from ...observability.render_json import render_trace_json
from ...observability.store.reader import (
    build_trace_view,
    open_observability_store_readonly,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeclone observability")
    sub = parser.add_subparsers(dest="command")
    trace = sub.add_parser("trace", help="Render the recorded operation trace.")
    trace.add_argument("--root", default=".", help="Repository root path.")
    trace.add_argument(
        "--last", type=int, default=None, help="Show the last N root operations."
    )
    trace.add_argument(
        "--operation", default=None, help="Focus one operation id and its chain."
    )
    trace.add_argument("--correlation", default=None, help="Filter by correlation id.")
    trace.add_argument("--json", default=None, help="Write JSON to this path.")
    trace.add_argument("--html", default=None, help="Write HTML to this path.")
    return parser


def _report_missing_store(root: Path) -> int:
    print(
        f"No observability store at {root}. Run with "
        "CODECLONE_OBSERVABILITY_ENABLED=1 to start collecting."
    )
    return int(ExitCode.SUCCESS)


def observability_main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "trace":
        parser.print_help()
        return int(ExitCode.CONTRACT_ERROR)

    root = Path(args.root).resolve()
    conn = open_observability_store_readonly(root)
    if conn is None:
        return _report_missing_store(root)
    try:
        trace = build_trace_view(
            conn,
            operation_id=args.operation,
            correlation_id=args.correlation,
            last=args.last,
        )
    finally:
        conn.close()

    outputs = [(args.json, render_trace_json), (args.html, render_trace_html)]
    wrote = False
    for path, render in outputs:
        if path is not None:
            Path(path).write_text(render(trace), encoding="utf-8")
            print(f"Wrote {path}")
            wrote = True
    if not wrote:
        print(render_trace_json(trace))
    return int(ExitCode.SUCCESS)


__all__ = ["observability_main"]

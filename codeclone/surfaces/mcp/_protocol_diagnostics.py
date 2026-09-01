# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Protocol diagnostics for arguments the tool schema rejects before we see them.

FastMCP validates every tool call against a model built from the handler
signature, so a wrongly typed argument never reaches a CodeClone handler at
all: the refusal is written by the validation library, in its vocabulary. For
a run id that vocabulary actively misleads. A short run id is the first eight
characters of a sha256 hexdigest, so about one id in forty-three is all
digits; a client that serializes such an id as a JSON number is told "Input
should be a valid string", which reads as *that id is malformed* rather than
*quote it*. The id is correct and the run exists — only the encoding is wrong.

Diagnosis is read from the two things this layer owns outright: the arguments
the caller sent, and the input schema those callers were published. It is
deliberately not read out of the validation error, so nothing here depends on
that library's error shape — and no new dependency edge is created for it.

Nothing about the identifier changes. ``run_id`` stays a string on the wire,
its schema is untouched, and the same id sent as a string resolves exactly as
it did before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .messages import errors as err_msgs

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from mcp.server.fastmcp import FastMCP
    from mcp.types import ContentBlock


def _declared_types(schema: dict[str, Any]) -> frozenset[str]:
    """JSON types a parameter schema admits, flattened across ``anyOf``.

    A variant that declares no type of its own contributes nothing nameable
    and drops out, so an unrecognized parameter simply fails to look like a
    string — the safe direction, since it is then left to the schema refusal.
    """

    variants = schema.get("anyOf") or (schema,)
    return frozenset(
        declared
        for variant in variants
        if isinstance(declared := variant.get("type"), str)
    )


def string_typed_run_id_parameters(
    input_schema: dict[str, Any],
) -> frozenset[str]:
    """Run-id parameters this tool publishes as a string and not as a number.

    A parameter that already admitted a number would not have been rejected
    for carrying one, so it must never be prescribed a correction. No such
    parameter exists today — every run-id parameter on every tool is a string
    — but widening one is a live proposal, and a diagnosis that kept telling
    those callers to quote a value the schema accepts unquoted would be
    prescribing a fix for a fault that is not there.
    """

    properties: dict[str, Any] = input_schema.get("properties") or {}
    return frozenset(
        name
        for name, schema in properties.items()
        if name.endswith("run_id")
        and "string" in (types := _declared_types(schema))
        and not types & {"integer", "number"}
    )


def quoted_digits(value: object) -> str | None:
    """Digits to quote back, or None when quoting would invent a value.

    Only a number that could have carried an all-digit id earns a correction.
    A boolean, a fraction or a negative cannot have come from one, so they keep
    the schema refusal rather than receive a prescription naming a value the
    caller never sent.

    One test decides that, deliberately: rendering first and admitting only
    digits rejects ``True`` and ``-1`` by the same rule that rejects anything
    else that does not read back as an id. An extra ``bool`` guard in front
    was measured redundant — mutation could not tell the two apart.
    """

    if isinstance(value, int):
        digits = str(value)
    elif isinstance(value, float) and value.is_integer():
        digits = str(int(value))
    else:
        return None
    return digits if digits.isdigit() else None


def numeric_run_id_refusal(
    tool: str,
    arguments: dict[str, Any],
    run_id_parameters: frozenset[str],
    rejection: str,
) -> str | None:
    """The executable refusal for this rejection, or None to leave it alone.

    The original rejection is always carried through. Quoting the id is enough
    only when the encoding was the sole fault, and this layer does not
    re-adjudicate that — so it never answers a call by hiding the other reason
    the call was refused.
    """

    corrections = tuple(
        (name, digits)
        for name in sorted(run_id_parameters)
        if (digits := quoted_digits(arguments.get(name))) is not None
    )
    if not corrections:
        return None
    return err_msgs.run_id_must_be_quoted(tool, corrections, rejection)


def diagnosing_server_class() -> type[FastMCP]:
    """FastMCP with the numeric-run-id refusal replaced by the executable one.

    The override sits on ``call_tool`` because that is the single seam every
    tool passes through: the schema rejection happens above all of the run-id
    handlers at once, so one boundary covers the whole population by
    construction rather than by a per-tool list somebody has to maintain.
    """

    from mcp.server.fastmcp import FastMCP as _FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

    class _RunIdDiagnosingFastMCP(_FastMCP):
        _run_id_parameters: dict[str, frozenset[str]] | None = None

        async def _run_id_parameters_for(self, tool: str) -> frozenset[str]:
            if self._run_id_parameters is None:
                self._run_id_parameters = {
                    published.name: string_typed_run_id_parameters(
                        dict(published.inputSchema or {})
                    )
                    for published in await self.list_tools()
                }
            return self._run_id_parameters.get(tool, frozenset())

        async def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
        ) -> Sequence[ContentBlock] | dict[str, Any]:
            try:
                return await super().call_tool(name, arguments)
            except ToolError as exc:
                refusal = numeric_run_id_refusal(
                    name,
                    arguments,
                    await self._run_id_parameters_for(name),
                    str(exc),
                )
                if refusal is None:
                    raise
                raise ToolError(refusal) from exc.__cause__

    return _RunIdDiagnosingFastMCP


__all__ = [
    "diagnosing_server_class",
    "numeric_run_id_refusal",
    "quoted_digits",
    "string_typed_run_id_parameters",
]

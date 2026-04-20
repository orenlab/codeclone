#!/usr/bin/env python3
from __future__ import annotations

from codeclone.config.spec import OPTIONS


def _default_repr(value: object) -> str:
    if value is None:
        return "`None`"
    if isinstance(value, tuple):
        return "`()`" if not value else f"`{list(value)!r}`"
    if isinstance(value, str):
        return f"`{value}`"
    return f"`{value}`"


def main() -> int:
    print("| Group | CLI | Pyproject | Default | Help |")
    print("| --- | --- | --- | --- | --- |")
    for option in OPTIONS:
        if option.flags:
            cli = ", ".join(option.flags)
        elif option.cli_kind == "positional":
            cli = "(positional)"
        else:
            cli = "-"
        pyproject = option.pyproject_key or "-"
        default = _default_repr(option.default) if option.has_default else "-"
        help_text = (option.help_text or "").replace("\n", " ")
        print(
            f"| {option.group or '-'} | `{cli}` | `{pyproject}` | "
            f"{default} | {help_text} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

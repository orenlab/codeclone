# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
# ruff: noqa: RUF001

"""CodeClone CLI mascot frame catalog and animation sequences.

Canonical loops include ``SCANNING`` tree growth and ``GRAPH_PULSE`` node pulse.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AsterState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    ANALYSIS = "analysis"
    CACHE = "cache"
    DEPENDENCIES = "dependencies"
    BLAST_RADIUS = "blast_radius"
    CONTROL = "control"
    REPORTING = "reporting"
    SUCCESS = "success"
    ATTENTION = "attention"
    BLOCKED = "blocked"


class AsterAnimation(str, Enum):
    """Named animation loops decoupled from mascot state."""

    NONE = "none"
    SCANNING = "scanning"
    ANALYSIS_BRANCH = "analysis_branch"
    GRAPH_PULSE = "graph_pulse"
    CACHE_CHAIN = "cache_chain"
    DEPENDENCIES = "dependencies"
    BLAST_RIPPLE = "blast_ripple"
    CONTROL_GATE = "control_gate"
    ORIGIN_HUB = "origin_hub"
    REPORTING = "reporting"
    BLOCKED_SPLIT = "blocked_split"


@dataclass(frozen=True, slots=True)
class AsterFrame:
    lines: tuple[str, ...]
    message: str
    style: str = "codeclone.primary"


_FRAMES_UNICODE: dict[AsterState, AsterFrame] = {
    AsterState.IDLE: AsterFrame(
        lines=("   ●   ", "  ╱│╲  ", " ○ ○ ○ "),
        message="Deterministic structural change control.",
    ),
    AsterState.SCANNING: AsterFrame(
        lines=("   ●   ", "  ╱│╲  ", " ○ ○ ○ "),
        message="Mapping repository structure…",
    ),
    AsterState.ANALYSIS: AsterFrame(
        lines=("   ◉   ", "  ╱│╲  ", " ○ ○ ○ ", " ╱╲ ╱╲ "),
        message="Running structural analysis…",
    ),
    AsterState.CACHE: AsterFrame(
        lines=("       ", " ●─○─○ ", "       "),
        message="Reusing structural facts…",
    ),
    AsterState.DEPENDENCIES: AsterFrame(
        lines=(
            "   ○   ",
            "  ╱│╲  ",
            " ○─●─○ ",
            "  ╲│╱  ",
            "   ○   ",
        ),
        message="Following dependencies…",
    ),
    AsterState.BLAST_RADIUS: AsterFrame(
        lines=(" · · · ", "·  ◉  ·", " · · · "),
        message="Mapping blast radius…",
    ),
    AsterState.CONTROL: AsterFrame(
        lines=(" ┌─────┐ ", " │  ◉  │ ", " └─────┘ "),
        message="Controlled change active.",
    ),
    AsterState.REPORTING: AsterFrame(
        lines=(" ┌───┐ ", " │ ● │ ", " └───┘ "),
        message="Compiling canonical report…",
    ),
    AsterState.SUCCESS: AsterFrame(
        lines=("   ●   ", "  ╲│╱  ", "   ✓   "),
        message="Analysis complete.",
        style="codeclone.success",
    ),
    AsterState.ATTENTION: AsterFrame(
        lines=("   ●   ", "  ╱│   ", "   !   "),
        message="Review required.",
        style="codeclone.attention",
    ),
    AsterState.BLOCKED: AsterFrame(
        lines=("   ◉   ", "  ╱■   ", "  STOP "),
        message="Boundary held.",
        style="codeclone.attention",
    ),
}

_FRAMES_ASCII: dict[AsterState, AsterFrame] = {
    AsterState.IDLE: AsterFrame(
        lines=("  o  ", " /|\\ ", "o o o"),
        message="Deterministic structural change control.",
    ),
    AsterState.SCANNING: AsterFrame(
        lines=("  o  ", " /|\\ ", "o o o"),
        message="Mapping repository structure...",
    ),
    AsterState.ANALYSIS: AsterFrame(
        lines=("  O  ", " /|\\ ", "o o o", " /\\/\\ "),
        message="Running structural analysis...",
    ),
    AsterState.CACHE: AsterFrame(
        lines=("     ", " o-o-o ", "     "),
        message="Reusing structural facts...",
    ),
    AsterState.DEPENDENCIES: AsterFrame(
        lines=("  o  ", " /|\\ ", "o-o-o", " \\|/ ", "  o  "),
        message="Following dependencies...",
    ),
    AsterState.BLAST_RADIUS: AsterFrame(
        lines=(" . . . ", ".  O  .", " . . . "),
        message="Mapping blast radius...",
    ),
    AsterState.CONTROL: AsterFrame(
        lines=(" +-----+ ", " |  O  | ", " +-----+ "),
        message="Controlled change active.",
    ),
    AsterState.REPORTING: AsterFrame(
        lines=(" +---+ ", " | o | ", " +---+ "),
        message="Compiling canonical report...",
    ),
    AsterState.SUCCESS: AsterFrame(
        lines=("  o  ", " \\|/ ", "  v  "),
        message="Analysis complete.",
        style="codeclone.success",
    ),
    AsterState.ATTENTION: AsterFrame(
        lines=("  o  ", " /|  ", "  !  "),
        message="Review required.",
        style="codeclone.attention",
    ),
    AsterState.BLOCKED: AsterFrame(
        lines=("  O  ", " /#  ", " STOP"),
        message="Boundary held.",
        style="codeclone.attention",
    ),
}

_SCANNING_ANIMATION_UNICODE: tuple[tuple[str, ...], ...] = (
    ("   ●   ", "  ╱│   ", " ○     "),
    ("   ●   ", "  ╱│╲  ", " ○ ○   "),
    ("   ●   ", "  │╲   ", " ○     "),
    ("   ●   ", "  ╱│╲  ", " ○ ○ ○ "),
)

_SCANNING_ANIMATION_ASCII: tuple[tuple[str, ...], ...] = (
    ("  o  ", " /|  ", " o   "),
    ("  o  ", " /|\\ ", " o o "),
    ("  o  ", "  |\\ ", " o   "),
    ("  o  ", " /|\\ ", "o o o"),
)

_ANALYSIS_BRANCH_UNICODE: tuple[tuple[str, ...], ...] = (
    ("   ◉   ", "  ╱│╲  ", " ○ ○ ○ "),
    ("   ◉   ", "  ╱│╲  ", " ○ ○ ○ ", " ╱╲ ╱╲ "),
    ("   ◉   ", "  ╱│╲  ", " ● ○ ● ", " ╱╲ ╱╲ "),
    ("   ◉   ", "  ╱│╲  ", " ○ ○ ○ ", " ╱╲ ╱╲ "),
)

_ANALYSIS_BRANCH_ASCII: tuple[tuple[str, ...], ...] = (
    ("  O  ", " /|\\ ", "o o o"),
    ("  O  ", " /|\\ ", "o o o", " /\\/\\ "),
    ("  O  ", " /|\\ ", "O o O", " /\\/\\ "),
    ("  O  ", " /|\\ ", "o o o", " /\\/\\ "),
)

_GRAPH_PULSE_UNICODE: tuple[tuple[str, ...], ...] = (
    (" ●─○─○─○ ",),
    (" ○─●─○─○ ",),
    (" ○─○─●─○ ",),
    (" ○─○─○─● ",),
)

_GRAPH_PULSE_ASCII: tuple[tuple[str, ...], ...] = (
    (" o-o-o-o ",),
    (" o-O-o-o ",),
    (" o-o-O-o ",),
    (" o-o-o-O ",),
)

_CACHE_ANIMATION_UNICODE: tuple[tuple[str, ...], ...] = (
    ("       ", " ●─○─○ ", "       "),
    ("       ", " ○─●─○ ", "       "),
    ("       ", " ○─○─● ", "       "),
    ("       ", " ●─○─○ ", "       "),
)

_CACHE_ANIMATION_ASCII: tuple[tuple[str, ...], ...] = (
    ("     ", " o-o-o ", "     "),
    ("     ", " o-O-o ", "     "),
    ("     ", " o-o-O ", "     "),
    ("     ", " o-o-o ", "     "),
)

_DEPENDENCIES_ANIMATION_UNICODE: tuple[tuple[str, ...], ...] = (
    ("   ○   ", "  ╱│╲  ", " ○─●─○ ", "  ╲│╱  ", "   ○   "),
    ("   ○   ", "  ╱│╲  ", " ●─○─○ ", "  ╲│╱  ", "   ○   "),
    ("   ○   ", "  ╱│╲  ", " ○─○─● ", "  ╲│╱  ", "   ○   "),
    ("   ○   ", "  ╱│╲  ", " ○─●─○ ", "  ╲│╱  ", "   ○   "),
)

_DEPENDENCIES_ANIMATION_ASCII: tuple[tuple[str, ...], ...] = (
    ("  o  ", " /|\\ ", "o-o-o", " \\|/ ", "  o  "),
    ("  o  ", " /|\\ ", "O-o-o", " \\|/ ", "  o  "),
    ("  o  ", " /|\\ ", "o-o-O", " \\|/ ", "  o  "),
    ("  o  ", " /|\\ ", "o-o-o", " \\|/ ", "  o  "),
)

_REPORTING_ANIMATION_UNICODE: tuple[tuple[str, ...], ...] = (
    (" ┌───┐ ", " │ ● │ ", " └───┘ "),
    (" ┌───┐ ", " │ ○ │ ", " └───┘ "),
    (" ┌───┐ ", " │ ● │ ", " └───┘ "),
    (" ┌───┐ ", " │ ○ │ ", " └───┘ "),
)

_REPORTING_ANIMATION_ASCII: tuple[tuple[str, ...], ...] = (
    (" +---+ ", " | o | ", " +---+ "),
    (" +---+ ", " |   | ", " +---+ "),
    (" +---+ ", " | o | ", " +---+ "),
    (" +---+ ", " |   | ", " +---+ "),
)

_BLOCKED_SPLIT_UNICODE: tuple[tuple[str, ...], ...] = (
    (" ◉─○   ○─◉ ", "  ╲│    │╱  ", "   ○     ○   "),
    (" ○─◉   ◉─○ ", "  │╱    ╲│  ", "   ○     ○   "),
)

_BLOCKED_SPLIT_ASCII: tuple[tuple[str, ...], ...] = (
    (" O-o   o-O ", "  \\|    |/  ", "   o     o   "),
    (" o-O   O-o ", "  |/    \\|  ", "   o     o   "),
)

_CONTROL_GATE_UNICODE: tuple[tuple[str, ...], ...] = (
    (" ┌─────┐ ", " │  ◉  │ ", " └─────┘ "),
    (" ┌─────┐ ", " │  ●  │ ", " └─────┘ "),
    (" ╔═════╗ ", " ║  ◉  ║ ", " ╚═════╝ "),
    (" ┌─────┐ ", " │  ◉  │ ", " └─────┘ "),
)

_CONTROL_GATE_ASCII: tuple[tuple[str, ...], ...] = (
    (" +-----+ ", " |  O  | ", " +-----+ "),
    (" +-----+ ", " |  o  | ", " +-----+ "),
    (" +=====+ ", " |  O  | ", " +=====+ "),
    (" +-----+ ", " |  O  | ", " +-----+ "),
)

_BLAST_RIPPLE_UNICODE: tuple[tuple[str, ...], ...] = (
    (" · · · ", "·  ◉  ·", " · · · "),
    ("·   · ", " · ◉ · ", "·   · "),
    (" ·   · ", "  ◉   ", " ·   · "),
    (" · · · ", "·  ◉  ·", " · · · "),
)

_BLAST_RIPPLE_ASCII: tuple[tuple[str, ...], ...] = (
    (" . . . ", ".  O  .", " . . . "),
    (".   . ", " . O . ", ".   . "),
    (" .   . ", "  O   ", " .   . "),
    (" . . . ", ".  O  .", " . . . "),
)

_ORIGIN_HUB_UNICODE: tuple[tuple[str, ...], ...] = (
    ("   ●   ", "  ╱│╲  ", " ○ ◉ ○ ", "   ╵   "),
    ("   ◉   ", "  ╱│╲  ", " ○ ○ ○ ", "   ╵   "),
    ("   ●   ", " ╱ │ ╲ ", " ○ ● ○ ", "   ╵   "),
    ("   ●   ", "  ╱│╲  ", " ○ ◉ ○ ", "   ●   "),
)

_ORIGIN_HUB_ASCII: tuple[tuple[str, ...], ...] = (
    ("  o  ", " /|\\ ", "o O o", "  |  "),
    ("  O  ", " /|\\ ", "o o o", "  |  "),
    ("  o  ", " / | \\ ", "o O o", "  |  "),
    ("  o  ", " /|\\ ", "o O o", "  o  "),
)

_ANIMATIONS_UNICODE: dict[AsterAnimation, tuple[tuple[str, ...], ...]] = {
    AsterAnimation.SCANNING: _SCANNING_ANIMATION_UNICODE,
    AsterAnimation.ANALYSIS_BRANCH: _ANALYSIS_BRANCH_UNICODE,
    AsterAnimation.GRAPH_PULSE: _GRAPH_PULSE_UNICODE,
    AsterAnimation.CACHE_CHAIN: _CACHE_ANIMATION_UNICODE,
    AsterAnimation.DEPENDENCIES: _DEPENDENCIES_ANIMATION_UNICODE,
    AsterAnimation.BLAST_RIPPLE: _BLAST_RIPPLE_UNICODE,
    AsterAnimation.CONTROL_GATE: _CONTROL_GATE_UNICODE,
    AsterAnimation.ORIGIN_HUB: _ORIGIN_HUB_UNICODE,
    AsterAnimation.REPORTING: _REPORTING_ANIMATION_UNICODE,
    AsterAnimation.BLOCKED_SPLIT: _BLOCKED_SPLIT_UNICODE,
}

_ANIMATIONS_ASCII: dict[AsterAnimation, tuple[tuple[str, ...], ...]] = {
    AsterAnimation.SCANNING: _SCANNING_ANIMATION_ASCII,
    AsterAnimation.ANALYSIS_BRANCH: _ANALYSIS_BRANCH_ASCII,
    AsterAnimation.GRAPH_PULSE: _GRAPH_PULSE_ASCII,
    AsterAnimation.CACHE_CHAIN: _CACHE_ANIMATION_ASCII,
    AsterAnimation.DEPENDENCIES: _DEPENDENCIES_ANIMATION_ASCII,
    AsterAnimation.BLAST_RIPPLE: _BLAST_RIPPLE_ASCII,
    AsterAnimation.CONTROL_GATE: _CONTROL_GATE_ASCII,
    AsterAnimation.ORIGIN_HUB: _ORIGIN_HUB_ASCII,
    AsterAnimation.REPORTING: _REPORTING_ANIMATION_ASCII,
    AsterAnimation.BLOCKED_SPLIT: _BLOCKED_SPLIT_ASCII,
}

_STATE_DEFAULT_ANIMATION: dict[AsterState, AsterAnimation] = {
    AsterState.SCANNING: AsterAnimation.SCANNING,
    AsterState.ANALYSIS: AsterAnimation.ANALYSIS_BRANCH,
    AsterState.CACHE: AsterAnimation.CACHE_CHAIN,
    AsterState.DEPENDENCIES: AsterAnimation.DEPENDENCIES,
    AsterState.BLAST_RADIUS: AsterAnimation.BLAST_RIPPLE,
    AsterState.CONTROL: AsterAnimation.CONTROL_GATE,
    AsterState.REPORTING: AsterAnimation.REPORTING,
    AsterState.BLOCKED: AsterAnimation.BLOCKED_SPLIT,
}


def frame_for_state(state: AsterState, *, use_unicode: bool = True) -> AsterFrame:
    catalog = _FRAMES_UNICODE if use_unicode else _FRAMES_ASCII
    return catalog[state]


def scanning_animation_frames(
    *,
    use_unicode: bool = True,
) -> tuple[tuple[str, ...], ...]:
    if use_unicode:
        return _SCANNING_ANIMATION_UNICODE
    return _SCANNING_ANIMATION_ASCII


def graph_pulse_animation_frames(
    *,
    use_unicode: bool = True,
) -> tuple[tuple[str, ...], ...]:
    if use_unicode:
        return _GRAPH_PULSE_UNICODE
    return _GRAPH_PULSE_ASCII


def animation_frames_for_kind(
    kind: AsterAnimation,
    *,
    use_unicode: bool = True,
) -> tuple[tuple[str, ...], ...] | None:
    if kind is AsterAnimation.NONE:
        return None
    catalog = _ANIMATIONS_UNICODE if use_unicode else _ANIMATIONS_ASCII
    return catalog.get(kind)


def animation_frames_for_state(
    state: AsterState,
    *,
    use_unicode: bool = True,
) -> tuple[tuple[str, ...], ...] | None:
    kind = _STATE_DEFAULT_ANIMATION.get(state)
    if kind is None:
        return None
    return animation_frames_for_kind(kind, use_unicode=use_unicode)


def resolve_animation(
    state: AsterState,
    *,
    animation: AsterAnimation | None,
    animate: bool,
    use_unicode: bool = True,
) -> tuple[tuple[str, ...], ...] | None:
    if not animate:
        return None
    kind = animation if animation is not None else _STATE_DEFAULT_ANIMATION.get(state)
    if kind is None or kind is AsterAnimation.NONE:
        return None
    return animation_frames_for_kind(kind, use_unicode=use_unicode)


__all__ = [
    "AsterAnimation",
    "AsterFrame",
    "AsterState",
    "animation_frames_for_kind",
    "animation_frames_for_state",
    "frame_for_state",
    "graph_pulse_animation_frames",
    "resolve_animation",
    "scanning_animation_frames",
]

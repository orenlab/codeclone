# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI presentation layer: mascot, interactive help tour, progress presenter."""

from .help_presenter import (
    help_flag_present,
    interactive_help_requested,
    print_static_help_mascot,
    static_help_mascot_lines,
)
from .help_tour import HelpTourStep, run_interactive_help_tour
from .mascot import Aster, mascot_use_unicode
from .mascot_frames import (
    AsterAnimation,
    AsterFrame,
    AsterState,
    animation_frames_for_kind,
    animation_frames_for_state,
    graph_pulse_animation_frames,
    resolve_animation,
)
from .progress_presenter import ProgressPresenter
from .tour_panel import TourStatsLines, build_step_panel
from .typewriter import TypewriterPanel

__all__ = [
    "Aster",
    "AsterAnimation",
    "AsterFrame",
    "AsterState",
    "HelpTourStep",
    "ProgressPresenter",
    "TourStatsLines",
    "TypewriterPanel",
    "animation_frames_for_kind",
    "animation_frames_for_state",
    "build_step_panel",
    "graph_pulse_animation_frames",
    "help_flag_present",
    "interactive_help_requested",
    "mascot_use_unicode",
    "print_static_help_mascot",
    "resolve_animation",
    "run_interactive_help_tour",
    "static_help_mascot_lines",
]

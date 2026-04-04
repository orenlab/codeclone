"use strict";

const HELP_TOPICS = [
  "workflow",
  "analysis_profile",
  "suppressions",
  "baseline",
  "latest_runs",
  "review_state",
  "changed_scope",
];

const HOTSPOT_GROUPS = [
  { id: "newRegressions", label: "New Regressions", icon: "diff-added" },
  { id: "productionHotspots", label: "Production Hotspots", icon: "target" },
  { id: "changedFiles", label: "Changed Files", icon: "git-commit" },
  { id: "overloadedModules", label: "Overloaded Modules", icon: "symbol-module" },
];

const HOTSPOT_FOCUS_MODES = [
  {
    id: "recommended",
    label: "Recommended",
    description: "Show the highest-signal review surfaces for the current run.",
  },
  {
    id: "new",
    label: "New Regressions",
    description: "Focus only on baseline-new findings.",
  },
  {
    id: "production",
    label: "Production",
    description: "Focus only on production hotspots.",
  },
  {
    id: "changed",
    label: "Changed Files",
    description: "Focus only on findings touching the selected diff.",
  },
  {
    id: "reportOnly",
    label: "Report-only",
    description: "Focus only on report-only Overloaded Module candidates.",
  },
  {
    id: "all",
    label: "All Groups",
    description: "Show every hotspot group, including empty ones.",
  },
];

const HOTSPOT_GROUPS_BY_MODE = {
  recommended: HOTSPOT_GROUPS.map((group) => group.id),
  new: ["newRegressions"],
  production: ["productionHotspots"],
  changed: ["changedFiles"],
  reportOnly: ["overloadedModules"],
  all: HOTSPOT_GROUPS.map((group) => group.id),
};

const ANALYSIS_PROFILE_OPTIONS = [
  {
    id: "defaults",
    label: "Conservative",
    description: "Recommended",
    detail: "Use repo defaults or pyproject for the first pass.",
  },
  {
    id: "deeperReview",
    label: "Deeper review",
    description: "Higher sensitivity",
    detail:
      "Lower thresholds for a deliberate second pass on smaller repeated units.",
  },
  {
    id: "custom",
    label: "Custom",
    description: "Workspace settings",
    detail: "Use the explicit function, block, and segment thresholds in settings.",
  },
];

const REVIEW_DECORATION_THEMES = {
  new: {
    badge: "N",
    color: "problemsErrorIcon.foreground",
    tooltip: "CodeClone new regression",
  },
  production: {
    badge: "P",
    color: "problemsWarningIcon.foreground",
    tooltip: "CodeClone production hotspot",
  },
  changed: {
    badge: "C",
    color: "charts.blue",
    tooltip: "CodeClone changed-files review item",
  },
};

const WORKSPACE_STATE_HOTSPOT_FOCUS_MODE = "codeclone.hotspotFocusMode";
const WORKSPACE_STATE_LAST_HELP_TOPIC = "codeclone.lastHelpTopic";

module.exports = {
  HELP_TOPICS,
  ANALYSIS_PROFILE_OPTIONS,
  HOTSPOT_GROUPS,
  HOTSPOT_FOCUS_MODES,
  HOTSPOT_GROUPS_BY_MODE,
  REVIEW_DECORATION_THEMES,
  WORKSPACE_STATE_HOTSPOT_FOCUS_MODE,
  WORKSPACE_STATE_LAST_HELP_TOPIC,
};

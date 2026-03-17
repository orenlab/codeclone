# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

# ruff: noqa: E501

from __future__ import annotations

from string import Template

FONT_CSS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700&"
    "family=JetBrains+Mono:wght@400;500&"
    "display=swap"
)

REPORT_TEMPLATE = Template(
    r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="${font_css_url}" rel="stylesheet">

<style>
/* ============================
   CodeClone UI
   ============================ */

:root {
  /* Neutral Palette */
  --surface-0: #0E1117;
  --surface-1: #161B22;
  --surface-2: #1F2937;
  --surface-3: #374151;
  --surface-4: #4B5563;

  --text-primary: #F3F4F6;
  --text-secondary: #D1D5DB;
  --text-tertiary: #9CA3AF;
  --text-muted: #6B7280;

  --border-subtle: #1F2937;
  --border-default: #374151;
  --border-strong: #4B5563;
  --border: var(--border-default);
  --border-soft: var(--border-subtle);

  /* Refined Accent - Blue */
  --accent-primary: #3B82F6;
  --accent-secondary: #60A5FA;
  --accent-subtle: rgba(59, 130, 246, 0.1);
  --accent-muted: rgba(59, 130, 246, 0.13);

  /* Semantic Colors - Muted & Professional */
  --success: #10B981;
  --success-subtle: rgba(16, 185, 129, 0.1);
  --success-strong: var(--success);
  --warning: #F59E0B;
  --warning-subtle: rgba(245, 158, 11, 0.1);
  --warning-strong: var(--warning);
  --error: #EF4444;
  --error-subtle: rgba(239, 68, 68, 0.1);
  --danger: var(--error);
  --danger-subtle: var(--error-subtle);
  --info: #3B82F6;
  --info-subtle: rgba(59, 130, 246, 0.1);
  --panel: color-mix(in oklab, var(--surface-1) 84%, var(--surface-0) 16%);
  --panel-soft: color-mix(in oklab, var(--surface-1) 74%, var(--surface-0) 26%);
  --shadow-sm: var(--elevation-1);

  /* Elevation - Subtle Professional Shadows */
  --elevation-0: none;
  --elevation-1: 0 1px 3px rgba(0, 0, 0, 0.2);
  --elevation-2: 0 2px 6px rgba(0, 0, 0, 0.25);
  --elevation-3: 0 4px 12px rgba(0, 0, 0, 0.3);
  --elevation-4: 0 8px 24px rgba(0, 0, 0, 0.35);

  /* Typography */
  --font-sans: 'Inter', -apple-system, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', Consolas, monospace;

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.125rem;
  --text-xl: 1.25rem;
  --text-2xl: 1.5rem;

  --leading-tight: 1.25;
  --leading-normal: 1.5;
  --leading-relaxed: 1.75;

  /* Spacing */
  --radius-sm: 4px;
  --radius: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;
  --control-height: 36px;
  --control-height-sm: 30px;
  --control-radius: 6px;
  --badge-height: 22px;
  --badge-pad-x: 8px;
  --badge-font-size: 0.72rem;
  --badge-radius: 6px;

  /* Transitions - Calm & Smooth */
  --transition-fast: 120ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-slow: 300ms cubic-bezier(0.4, 0, 0.2, 1);
}

html[data-theme="light"] {
  --surface-0: #FFFFFF;
  --surface-1: #F9FAFB;
  --surface-2: #F3F4F6;
  --surface-3: #E5E7EB;
  --surface-4: #D1D5DB;

  --text-primary: #111827;
  --text-secondary: #374151;
  --text-tertiary: #6B7280;
  --text-muted: #9CA3AF;

  --border-subtle: #E5E7EB;
  --border-default: #D1D5DB;
  --border-strong: #9CA3AF;
  --border: var(--border-default);
  --border-soft: var(--border-subtle);

  --accent-primary: #2563EB;
  --accent-secondary: #3B82F6;
  --accent-subtle: rgba(37, 99, 235, 0.1);
  --accent-muted: rgba(37, 99, 235, 0.10);
  --success-strong: var(--success);
  --warning-strong: var(--warning);
  --danger: var(--error);
  --danger-subtle: var(--error-subtle);
  --panel: color-mix(in oklab, var(--surface-1) 94%, white 6%);
  --panel-soft: color-mix(in oklab, var(--surface-2) 92%, white 8%);
  --shadow-sm: var(--elevation-1);

  --elevation-1: 0 1px 3px rgba(0, 0, 0, 0.08);
  --elevation-2: 0 2px 6px rgba(0, 0, 0, 0.12);
  --elevation-3: 0 4px 12px rgba(0, 0, 0, 0.15);
  --elevation-4: 0 8px 24px rgba(0, 0, 0, 0.18);
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

.icon {
  width: 1em;
  height: 1em;
  display: inline-block;
  vertical-align: middle;
  flex-shrink: 0;
}

html {
  scroll-behavior: smooth;
}

body {
  background: var(--surface-0);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: 1.58;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

::selection {
  background: var(--accent-subtle);
  color: var(--text-primary);
}

/* Layout */
.container {
  max-width: 1520px;
  margin: 0 auto;
  padding: 26px 24px 24px;
  flex: 1;
}

/* Topbar */
.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: color-mix(in oklab, var(--surface-0) 88%, black 12%);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-subtle);
  box-shadow: var(--elevation-2);
}

html[data-theme="light"] .topbar {
  background: rgba(255, 255, 255, 0.95);
}

.topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 72px;
  padding: 0 24px;
  max-width: 1520px;
  margin: 0 auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-logo {
  flex-shrink: 0;
}

.brand-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.brand h1 {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.brand-project {
  font-weight: 500;
  color: var(--text-secondary);
}

.brand-project-name {
  font-family: var(--font-mono);
  font-size: 0.72em;
  font-weight: 500;
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  vertical-align: middle;
}

.brand-meta {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 400;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.top-actions .btn {
  min-width: 40px;
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: var(--control-height);
  padding: 0 12px;
  border-radius: var(--control-radius);
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 500;
  font-family: var(--font-sans);
  transition:
    border-color var(--transition-base),
    background var(--transition-base),
    transform var(--transition-fast);
  white-space: nowrap;
  user-select: none;
}

.btn .icon {
  width: 0.95em;
  height: 0.95em;
}

.btn:hover {
  background: var(--surface-2);
  border-color: var(--border-strong);
}

.btn:active {
  transform: translateY(1px);
}

.btn:focus-visible {
  outline: 2px solid var(--accent-primary);
  outline-offset: 2px;
}

.btn.ghost {
  background: color-mix(in oklab, var(--surface-1) 80%, var(--surface-0) 20%);
  border-color: var(--border-subtle);
  padding: 0 10px;
}

.btn.ghost:hover {
  background: var(--surface-2);
  border-color: var(--border-default);
}

/* Info button - unified with the rest of UI */
.btn.ghost[data-metrics-btn] {
  background: color-mix(in oklab, var(--surface-2) 90%, white 10%);
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  padding: 0 11px;
  font-size: var(--text-xs);
  font-weight: 500;
  border-radius: var(--radius);
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast),
    color var(--transition-fast);
}

.btn.ghost[data-metrics-btn]:hover {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
  color: white;
}

.btn.primary {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
  color: white;
  font-weight: 600;
}

.btn.primary:hover {
  background: var(--accent-secondary);
  border-color: var(--accent-secondary);
}

.btn.hotkey {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: 0.01em;
}

/* Form Elements */
.select {
  appearance: none;
  -webkit-appearance: none;
  padding: 0 32px 0 12px;
  height: var(--control-height);
  border-radius: var(--control-radius);
  border: 1px solid var(--border-default);
  background: var(--surface-1) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239CA3AF' stroke-width='2.5'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E") no-repeat right 10px center;
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  cursor: pointer;
  transition:
    border-color var(--transition-base),
    background var(--transition-base);
}

.select:hover {
  border-color: var(--border-strong);
}

.select:focus {
  outline: 2px solid var(--accent-primary);
  outline-offset: 2px;
}

/* Sections */
.section {
  margin-top: 34px;
}

/* Meta Panel */
.meta-panel {
  margin-top: 14px;
  margin-bottom: 18px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  overflow: hidden;
}

.meta-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid transparent;
  transition:
    background var(--transition-base),
    border-color var(--transition-base);
}

.meta-header:hover {
  background: var(--surface-2);
  border-bottom-color: var(--border-subtle);
}

.meta-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.meta-hint {
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--text-muted);
  font-style: italic;
}

.meta-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  transition: transform var(--transition-base);
  color: var(--text-muted);
}

.meta-toggle.collapsed {
  transform: rotate(-90deg);
}

.meta-content {
  max-height: none;
  opacity: 1;
  overflow: visible;
  transition: opacity var(--transition-base);
}

.meta-content.collapsed {
  max-height: 0;
  opacity: 0;
}

.meta-sections {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 10px 16px 16px;
}

.meta-section {
  margin: 0;
}

.meta-section-title {
  margin: 0 0 8px;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 600;
  letter-spacing: 0.01em;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-auto-flow: row dense;
  gap: 14px;
  padding: 10px 16px 16px;
}

.meta-section .meta-grid {
  padding: 0;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 7px;
  grid-column: span 4;
  min-width: 0;
  padding: 12px 13px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: color-mix(in oklab, var(--surface-0) 75%, var(--surface-1) 25%);
}

.meta-item-wide {
  grid-column: 1 / -1;
}

.meta-item-boolean .meta-value {
  display: inline-flex;
  align-items: center;
  width: fit-content;
}

.meta-bool {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: var(--badge-radius);
  font-size: var(--text-xs);
  font-weight: 600;
  border: 1px solid var(--border-default);
}

.meta-bool-true {
  background: var(--success-subtle);
  color: var(--success);
}

.meta-bool-false {
  background: var(--error-subtle);
  color: var(--error);
}

.meta-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.meta-value {
  font-size: var(--text-sm);
  color: var(--text-primary);
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
  word-break: normal;
  line-height: 1.42;
}

/* Section Title */
.section-title {
  display: block;
  margin: 0 0 10px;
}

.section-title h2,
h2.section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: clamp(1.5rem, 1.15rem + 1vw, 2rem);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.count-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--badge-height);
  padding: 0 var(--badge-pad-x);
  background: var(--accent-subtle);
  color: var(--accent-primary);
  border-radius: var(--badge-radius);
  font-size: var(--badge-font-size);
  font-weight: 600;
  line-height: 1;
}

/* Toolbar */
.toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px 14px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: var(--elevation-1);
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.toolbar-right {
  justify-content: flex-end;
}

.novelty-tabs {
  display: inline-flex;
  align-items: stretch;
  gap: 0;
  position: relative;
  bottom: -1px;
}

.global-novelty {
  margin-top: 14px;
  margin-bottom: 18px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: var(--elevation-1);
  overflow: hidden;
}

.global-novelty-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 16px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.global-novelty-head h2 {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.01em;
  padding-bottom: 12px;
}

.novelty-tab {
  height: auto;
  padding: 8px 14px 10px;
  font-size: var(--text-xs);
  border-radius: 0;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    border-color var(--transition-fast),
    background var(--transition-fast);
}

.novelty-tab:hover {
  background: var(--surface-2);
  color: var(--text-primary);
}

.novelty-tab.is-active {
  color: var(--accent-primary);
  border-bottom-color: var(--accent-primary);
  font-weight: 600;
  background: transparent;
}

.novelty-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  background: color-mix(in oklab, var(--surface-2) 90%, var(--surface-0) 10%);
  font-family: var(--font-mono);
  font-size: 0.68rem;
  line-height: 1;
}

.novelty-tab.is-active .novelty-count {
  background: color-mix(in oklab, var(--accent-primary) 15%, transparent 85%);
  color: var(--accent-primary);
}

.novelty-note {
  margin: 0;
  padding: 10px 16px 12px;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  line-height: 1.4;
}

.tab-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin: 12px 0 0;
  padding: 0 8px;
  border-bottom: 1px solid var(--border-subtle);
  border-radius: 10px 10px 0 0;
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid transparent;
  border-bottom: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 10px 10px 0 0;
  padding: 10px 16px;
  font-size: var(--text-xs);
  font-weight: 600;
  cursor: pointer;
  transition: all var(--transition-fast);
  margin-bottom: -1px;
}

.tab-btn:hover {
  color: var(--text-primary);
  background: var(--surface-1);
}

.tab-btn.active {
  background: var(--surface-0);
  border-color: var(--border-subtle);
  border-bottom-color: var(--surface-0);
  color: var(--accent-primary);
  position: relative;
  z-index: 2;
  box-shadow: 0 1px 0 var(--surface-0);
}

.tab-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 0.66rem;
  line-height: 1;
  background: color-mix(in oklab, var(--surface-2) 86%, var(--surface-0) 14%);
  color: var(--text-tertiary);
}

.tab-btn.active .tab-count {
  background: color-mix(in oklab, var(--accent-primary) 16%, transparent 84%);
  color: var(--accent-primary);
}

.tab-panel {
  display: none;
  padding: 20px 20px 24px;
  border: 1px solid var(--border-subtle);
  border-top: none;
  border-radius: 0 0 10px 10px;
  background: var(--surface-0);
}

.tab-panel.active {
  display: block;
}

.tab-panel > .section:first-child,
.tab-panel .section:first-child,
.clone-panel .section {
  margin-top: 0;
}

.subsection-title {
  margin: 20px 0 10px;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 600;
  letter-spacing: 0.01em;
}

.subsection-title:first-child,
.insight-banner + .subsection-title {
  margin-top: 0;
}

.insight-banner {
  margin: 0 0 14px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--border-subtle);
  background: color-mix(in oklab, var(--surface-1) 82%, var(--surface-0) 18%);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.insight-question {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
}

.insight-answer {
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-mono);
  line-height: 1.45;
}

.insight-banner.insight-ok {
  border-color: color-mix(in oklab, var(--success) 35%, var(--border-default) 65%);
}

.insight-banner.insight-warn {
  border-color: color-mix(in oklab, var(--warning) 40%, var(--border-default) 60%);
}

.insight-banner.insight-risk {
  border-color: color-mix(in oklab, var(--error) 45%, var(--border-default) 55%);
}

/* Search */
.search-box {
  position: relative;
  width: clamp(260px, 38vw, 460px);
}

.search-box input {
  width: 100%;
  height: var(--control-height);
  padding: 0 34px 0 34px;
  border-radius: var(--control-radius);
  border: 1px solid var(--border-default);
  background: var(--surface-0);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  transition:
    border-color var(--transition-base),
    outline var(--transition-base);
}

.search-box input:focus {
  outline: 2px solid var(--accent-primary);
  outline-offset: 0;
  border-color: var(--accent-primary);
}

.search-box input::placeholder {
  color: var(--text-muted);
}

.search-box .search-ico {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  font-size: 0.95rem;
  pointer-events: none;
  display: inline-flex;
}

.search-box .clear-btn {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  padding: 4px;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    opacity var(--transition-base),
    background var(--transition-fast),
    color var(--transition-fast);
  opacity: 0;
  pointer-events: none;
}

.search-box .clear-btn:hover {
  background: var(--surface-2);
  color: var(--text-primary);
}

.search-box input:not(:placeholder-shown) + .clear-btn {
  opacity: 1;
  pointer-events: auto;
}

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-meta {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
  min-width: 160px;
  text-align: center;
}

/* Group Card */
.group {
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  margin-bottom: 18px;
  overflow: hidden;
  transition:
    border-color var(--transition-base),
    box-shadow var(--transition-base);
}

.group:hover {
  border-color: color-mix(in oklab, var(--accent-primary) 35%, var(--border-default) 65%);
  box-shadow: var(--elevation-3);
}

.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 14px;
  cursor: pointer;
  user-select: none;
  gap: 10px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--transition-base);
}

.group-head:hover {
  background: var(--surface-2);
}

.group-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.group-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  transition: transform var(--transition-base);
  color: var(--text-tertiary);
}

.group-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.group-name {
  font-size: 0.94rem;
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-sans);
  letter-spacing: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-summary {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  letter-spacing: 0.01em;
}

.group-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* Primary badge: clone instances count */
.clone-count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--badge-height);
  min-width: var(--badge-height);
  gap: 4px;
  padding: 0 var(--badge-pad-x);
  background: var(--accent-subtle);
  color: var(--accent-primary);
  border-radius: var(--badge-radius);
  font-size: var(--badge-font-size);
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.clone-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--badge-height);
  gap: 4px;
  padding: 0 var(--badge-pad-x);
  border-radius: var(--badge-radius);
  border: 1px solid color-mix(in oklab, var(--border-subtle) 70%, var(--surface-3) 30%);
  background: color-mix(in oklab, var(--surface-2) 70%, var(--surface-0) 30%);
  color: var(--text-secondary);
  font-size: var(--badge-font-size);
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

/* Group Body */
.group-body {
  background: color-mix(in oklab, var(--surface-1) 88%, var(--surface-0) 12%);
  padding: 12px;
}

.items {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-items: stretch;
}

/* Clone Item */
.item {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 0;
  border: 1px solid color-mix(in oklab, var(--border-subtle) 70%, var(--surface-3) 30%);
  border-radius: 10px;
  background: var(--surface-0);
  overflow: hidden;
  transition:
    border-color var(--transition-base),
    box-shadow var(--transition-base);
}

.item:hover {
  border-color: color-mix(in oklab, var(--accent-primary) 30%, var(--border-default) 70%);
  box-shadow: var(--elevation-2);
}

.item-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: color-mix(in oklab, var(--surface-1) 82%, var(--surface-0) 18%);
  margin-bottom: 0;
  min-width: 0;
}

.item-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono);
  line-height: 1.36;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-loc {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0.85;
}

.item .codebox {
  flex: 1;
  min-height: 0;
  max-height: 460px;
  margin-top: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.item .codebox pre {
  padding: 10px 12px 12px;
}

/* Group explainability facts */
.group-explain {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
  padding: 0 12px 10px;
}

.group-head + .group-explain {
  margin-top: 12px;
}

.group-explain-item {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--badge-height);
  font-family: var(--font-mono);
  font-size: var(--badge-font-size);
  line-height: 1.1;
  padding: 0 var(--badge-pad-x);
  border-radius: var(--badge-radius);
  border: 1px solid var(--border-default);
  background: color-mix(in oklab, var(--surface-2) 82%, var(--surface-1) 18%);
  color: var(--text-secondary);
  white-space: nowrap;
}

.group-explain-warn {
  color: var(--warning);
  border-color: color-mix(in oklab, var(--warning) 45%, var(--border-default) 55%);
  background: color-mix(in oklab, var(--warning-subtle) 75%, var(--surface-2) 25%);
}

.group-explain-muted {
  color: var(--text-tertiary);
}

.group-explain-note {
  flex-basis: 100%;
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: 0.74rem;
  line-height: 1.35;
}

.group-head .btn {
  height: var(--control-height-sm);
  padding: 0 10px;
  font-size: 0.74rem;
}

.group-head .btn.ghost {
  background: var(--surface-0);
  border-color: var(--border-subtle);
}

.group-head .btn.ghost:hover {
  background: var(--surface-2);
  border-color: var(--border-default);
}

.group-compare-note {
  margin: 12px 12px 0;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: color-mix(in oklab, var(--surface-1) 72%, var(--surface-0) 28%);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  line-height: 1.45;
}

.group-compare-note + .group-explain {
  margin-top: 10px;
}

.item-path {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  overflow-wrap: break-word;
  word-break: break-all;
  margin-top: 2px;
}

.item-compare-meta {
  padding: 0 12px 8px;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  line-height: 1.35;
}

/* Code Block */
.codebox {
  background: color-mix(in oklab, var(--surface-0) 90%, black 10%);
  border: 1px solid color-mix(in oklab, var(--border-subtle) 80%, var(--surface-3) 20%);
  border-radius: 0 0 10px 10px;
  overflow: auto;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.codebox pre {
  margin: 0;
  padding: 8px 12px;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 18px;
}

.codebox code {
  display: block;
  min-width: max-content;
}

.codebox .line,
.codebox .hitline {
  white-space: pre;
  margin: 0;
  padding: 0 0 0 5px;
  line-height: 18px;
  min-height: 18px;
  border-left: 3px solid transparent;
}

.codebox .hitline {
  background: var(--accent-muted);
  border-left-color: var(--accent-primary);
}

/* Metrics modal */
.metrics-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 1000;
  display: none;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn var(--transition-base);
}

.metrics-modal.active {
  display: flex;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.metrics-card {
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  max-width: 720px;
  width: 100%;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: var(--elevation-4);
  animation: slideUp var(--transition-slow);
}

.help-card {
  max-width: min(1140px, 96vw);
}

.finding-why-card {
  max-width: min(1180px, 96vw);
}

.finding-why-text {
  margin: 0 0 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.finding-why-list {
  margin: 0;
  padding-left: 20px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.finding-why-list li + li {
  margin-top: 8px;
}

.finding-why-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.finding-why-note {
  margin: 0 0 12px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.finding-why-examples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.finding-why-example {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.finding-why-example-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.finding-why-example-label {
  font-weight: 700;
  color: var(--text-primary);
}

.finding-why-example-meta {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.metrics-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-subtle);
}

.metrics-header h3 {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-primary);
}

.metrics-close {
  width: 32px;
  height: 32px;
  border-radius: var(--radius);
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

.metrics-close:hover {
  background: var(--surface-3);
  color: var(--text-primary);
  border-color: var(--border-strong);
}

.metrics-body {
  padding: 24px;
}

.metrics-section {
  margin-bottom: 24px;
}

.metrics-section:last-child {
  margin-bottom: 0;
}

.metrics-section-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 12px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
}

.metric-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 500;
  white-space: nowrap;
}

.metric-value {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono);
}

.metric-value-compact {
  font-size: var(--text-sm);
  line-height: 1.4;
  word-break: break-word;
}

.metric-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: var(--text-xs);
  font-weight: 500;
  word-break: break-word;
  white-space: normal;
}

.metric-badge.success {
  background: var(--success-subtle);
  color: var(--success);
}

.metric-badge.warning {
  background: var(--warning-subtle);
  color: var(--warning);
}

.metric-badge.error {
  background: var(--error-subtle);
  color: var(--error);
}

.metric-badge.info {
  background: var(--info-subtle);
  color: var(--info);
}

.metric-link-item {
  padding: 0;
  background: transparent;
  border: 0;
}

.help-card .metrics-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.help-card .metrics-section:first-child .metrics-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.help-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-2);
  color: var(--text-primary);
  text-decoration: none;
  transition:
    border-color var(--transition-base),
    background var(--transition-base),
    transform var(--transition-base);
}

.help-link:hover {
  border-color: var(--border-strong);
  background: var(--surface-3);
  transform: translateY(-1px);
}

.help-link-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.help-link-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.help-link-meta {
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.help-link-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

/* Code Preview */
.code-preview {
  margin-top: 8px;
  background: var(--surface-0);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 12px;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Toast notifications */
.toast-container {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast {
  padding: 12px 18px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevation-3);
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 280px;
  max-width: 400px;
  font-size: var(--text-sm);
  color: var(--text-primary);
  animation: slideInRight var(--transition-slow);
  pointer-events: auto;
}

@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(100%);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.toast.success {
  border-left: 3px solid var(--success);
}

.toast.warning {
  border-left: 3px solid var(--warning);
}

.toast.error {
  border-left: 3px solid var(--error);
}

.toast.info {
  border-left: 3px solid var(--info);
}

/* Command Palette */
.cmd-palette {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  z-index: 1500;
  display: none;
  align-items: flex-start;
  justify-content: center;
  padding-top: 100px;
}

.cmd-palette.active {
  display: flex;
}

.cmd-palette-content {
  width: min(720px, 92vw);
  max-height: min(76vh, 680px);
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  box-shadow: var(--elevation-4);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: slideDown var(--transition-slow);
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.cmd-search {
  width: 100%;
  padding: 14px 16px;
  border: none;
  border-bottom: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-primary);
  font-size: 1.75rem;
  line-height: 1.2;
  font-family: var(--font-sans);
}

.cmd-search:focus {
  outline: none;
}

.cmd-list {
  max-height: min(56vh, 460px);
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--surface-1);
}

.cmd-item {
  width: 100%;
  max-width: 100%;
  min-height: 64px;
  box-sizing: border-box;
  appearance: none;
  -webkit-appearance: none;
  border: 0;
  border-bottom: 1px solid var(--border-subtle);
  border-radius: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  cursor: pointer;
  transition: background var(--transition-base);
}

.cmd-item:last-child {
  border-bottom: none;
}

.cmd-item:hover {
  background: var(--surface-2);
}

.cmd-item.selected {
  background: var(--surface-2);
  box-shadow: inset 2px 0 0 var(--accent-primary);
}

.cmd-item:focus-visible {
  outline: 2px solid var(--accent-primary);
  outline-offset: -2px;
}

.cmd-item-icon {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
}

.cmd-item-text {
  flex: 1;
}

.cmd-item-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

.cmd-item-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.cmd-item-shortcut {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: var(--font-mono);
  padding: 2px 6px;
  background: var(--surface-0);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
}

.cmd-empty {
  padding: 16px 20px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

/* Footer */
.report-footer {
  margin-top: auto;
  padding: 16px 24px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.footer-kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
}

.footer-sep {
  color: var(--text-muted);
}

/* Provenance Summary Bar */
.prov-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 6px 16px 8px;
  font-size: 0.65rem;
  font-family: var(--font-mono);
  color: var(--text-muted);
  border-top: 1px solid var(--border-subtle);
}

.prov-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 500;
  font-size: 0.65rem;
  line-height: 1.6;
  white-space: nowrap;
  opacity: 0.85;
}

.prov-badge.green  { background: var(--success-subtle); color: var(--success); }
.prov-badge.amber  { background: #fef3c7; color: #92400e; }
.prov-badge.red    { background: var(--danger-subtle);  color: var(--danger); }
.prov-badge.neutral { background: var(--surface-2); color: var(--text-secondary); }

html[data-theme="dark"] .prov-badge.amber { background: rgba(251,191,36,0.15); color: #fbbf24; }

.prov-sep {
  color: var(--text-muted);
  user-select: none;
}

.prov-explain {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-style: italic;
  padding: 4px 16px 0;
}

/* Tab Empty State */
.tab-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}

.tab-empty-icon {
  width: 48px;
  height: 48px;
  margin-bottom: 12px;
  color: var(--text-muted);
  opacity: 0.5;
}

.tab-empty-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.tab-empty-desc {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  max-width: 360px;
}

/* Stats and Charts */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 0 0 16px;
}

.stat-card {
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 14px;
}

.stat-value {
  font-size: var(--text-2xl);
  font-weight: 700;
  font-family: var(--font-mono);
}

.stat-label {
  margin-top: 4px;
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.chart-container {
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 14px;
  margin: 0 0 16px;
}

.chart-title {
  font-size: var(--text-base);
  font-weight: 600;
  margin-bottom: 10px;
}

#complexity-canvas {
  width: 100%;
  height: 220px;
}

/* ============================
   Data Tables
   ============================ */
.table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 0 0 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-1);
  box-shadow: var(--elevation-1);
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
  line-height: 1.5;
  table-layout: auto;
}

.table thead {
  position: sticky;
  top: 0;
  z-index: 1;
}

.table th {
  padding: 10px 14px;
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: color-mix(in oklab, var(--surface-2) 60%, var(--surface-1) 40%);
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
}

.table th:first-child { border-radius: 10px 0 0 0; }
.table th:last-child  { border-radius: 0 10px 0 0; }

.table td {
  padding: 9px 14px;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-subtle);
  vertical-align: top;
}

.table tbody tr:last-child td { border-bottom: none; }

.table tbody tr {
  transition: background var(--transition-fast);
}

.table tbody tr:hover {
  background: color-mix(in oklab, var(--accent-subtle) 40%, transparent 60%);
}

/* Alternating rows */
.table tbody tr:nth-child(even) {
  background: color-mix(in oklab, var(--surface-0) 50%, var(--surface-1) 50%);
}

.table tbody tr:nth-child(even):hover {
  background: color-mix(in oklab, var(--accent-subtle) 40%, transparent 60%);
}

/* Semantic column types (class-based, not position-based) */
.table .col-name {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: 500;
  word-break: break-word;
}

.table .col-path {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table .col-num {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  text-align: right;
  white-space: nowrap;
}

.table .col-badge {
  white-space: nowrap;
  text-align: center;
}

.table .col-cat {
  white-space: nowrap;
}

.table .col-wide {
  word-break: break-word;
}

.table .col-steps {
  white-space: nowrap;
}

/* ============================
   Risk Badges (inline in tables)
   ============================ */
.risk-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: var(--badge-radius);
  font-size: var(--badge-font-size);
  font-weight: 600;
  line-height: 1;
}

.risk-low,
.risk-easy     { background: var(--success-subtle); color: var(--success); }
.risk-medium,
.risk-moderate { background: var(--warning-subtle); color: var(--warning); }
.risk-high,
.risk-hard     { background: var(--error-subtle);   color: var(--error); }

/* Severity badges */
.severity-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: var(--badge-radius);
  font-size: var(--badge-font-size);
  font-weight: 600;
  line-height: 1;
}

.severity-critical { background: var(--error-subtle);   color: var(--error); }
.severity-warning  { background: var(--warning-subtle); color: var(--warning); }
.severity-info     { background: var(--info-subtle);    color: var(--info); }

/* Category badges */
.category-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 8px;
  border-radius: var(--badge-radius);
  font-size: var(--badge-font-size);
  font-weight: 500;
  line-height: 1;
  background: color-mix(in oklab, var(--surface-2) 80%, var(--surface-3) 20%);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

/* ============================
   Dependency Stats & Graph
   ============================ */
/* ---- Dependency Stats ---- */
.dep-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.dep-stats .meta-item { grid-column: span 1; }

.dep-stat-detail {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  line-height: 1.3;
  margin-top: 2px;
}

.dep-stat-ok .meta-value { color: var(--success); }
.dep-stat-warn .meta-value { color: #d97706; }
.dep-stat-risk .meta-value { color: var(--danger); }

/* ---- Top Hubs Bar ---- */
.dep-hub-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 8px 14px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}

.dep-hub-label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-right: 2px;
}

.dep-hub-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: 100px;
  background: var(--accent-subtle);
  border: 1px solid color-mix(in oklab, var(--accent-primary) 20%, transparent 80%);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
}

.dep-hub-name { color: var(--text-primary); font-weight: 500; }
.dep-hub-deg  { color: var(--accent-primary); font-weight: 700; font-size: 0.68rem; }

/* ---- Dependency Graph ---- */
.dep-graph-wrap {
  margin: 0 0 6px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.dep-graph-svg {
  display: block;
  width: 100%;
  max-height: 560px;
  border-radius: 10px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
}

.dep-graph-svg text {
  font-family: var(--font-mono);
  fill: var(--text-tertiary);
  pointer-events: none;
  transition: fill var(--transition-fast), opacity var(--transition-fast);
}

.dep-graph-svg .dep-node {
  cursor: pointer;
  transition: r var(--transition-fast), opacity var(--transition-fast);
}

.dep-graph-svg .dep-edge {
  transition: stroke-opacity var(--transition-fast), stroke-width var(--transition-fast);
}

/* Hover: fade everything, highlight connected */
.dep-graph-svg.has-hover .dep-node:not(.highlighted) { opacity: 0.15; }
.dep-graph-svg.has-hover .dep-edge:not(.highlighted) { stroke-opacity: 0.04 !important; }
.dep-graph-svg.has-hover .dep-label:not(.highlighted) { opacity: 0.15; }
.dep-graph-svg.has-hover .dep-edge.highlighted { stroke-width: 2.5 !important; stroke-opacity: 0.85 !important; }
.dep-graph-svg.has-hover .dep-node.highlighted { opacity: 1; }
.dep-graph-svg.has-hover .dep-label.highlighted { opacity: 1; fill: var(--text-primary); }

/* ---- Graph Legend ---- */
.dep-legend {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 6px 4px;
}

.dep-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* ---- Chain Flow ---- */
.chain-flow {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-wrap: wrap;
}

.chain-node {
  display: inline-flex;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-primary);
  white-space: nowrap;
}

.chain-arrow {
  color: var(--text-muted);
  font-size: 0.65rem;
  flex-shrink: 0;
}

/* ============================
   Health Score Gauge (Overview)
   ============================ */
.health-gauge {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 14px;
}

.health-ring {
  position: relative;
  width: 100px;
  height: 100px;
}

.health-ring svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.health-ring-bg {
  fill: none;
  stroke: var(--surface-3);
  stroke-width: 8;
}

.health-ring-fg {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.5s ease;
}

.health-ring-label {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
}

.health-ring-score {
  font-size: var(--text-2xl);
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
  line-height: 1;
}

.health-ring-grade {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-tertiary);
  margin-top: 2px;
}

/* ---- Overview Dashboard ---- */
.overview-dashboard {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 16px;
  margin-bottom: 20px;
  align-items: stretch;
}

.overview-hero {
  display: flex;
  align-items: center;
  padding: 16px 20px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: var(--elevation-1);
}

.overview-hero .health-gauge {
  padding: 0;
  gap: 0;
}

.overview-kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  align-content: center;
}

.overview-kpi {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px 16px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}

.kpi-head {
  display: flex;
  align-items: center;
  gap: 5px;
}

.overview-kpi-label {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.overview-kpi-value {
  font-size: var(--text-2xl);
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-primary);
  line-height: 1;
}

.kpi-detail {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  line-height: 1.3;
}

.kpi-help {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--surface-3);
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 700;
  font-family: var(--font-sans);
  cursor: help;
  flex-shrink: 0;
  position: relative;
}

.kpi-help::after {
  content: attr(data-tip);
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  padding: 6px 10px;
  background: var(--surface-3);
  color: var(--text-primary);
  font-size: var(--text-xs);
  font-weight: 400;
  border-radius: 6px;
  width: max-content;
  max-width: 220px;
  white-space: normal;
  line-height: 1.4;
  display: none;
  pointer-events: none;
  z-index: 10;
  box-shadow: var(--elevation-2);
}

.kpi-help:hover::after {
  display: block;
}

/* Inside tables: disable CSS tooltip — JS handles it via .tip-float */
.table-wrap .kpi-help::after {
  display: none !important;
}

.tip-float {
  position: fixed;
  transform: translateX(-50%);
  padding: 6px 10px;
  background: var(--surface-3);
  color: var(--text-primary);
  font-size: var(--text-xs);
  font-weight: 400;
  border-radius: 6px;
  max-width: 220px;
  white-space: normal;
  line-height: 1.4;
  pointer-events: none;
  z-index: 1000;
  box-shadow: var(--elevation-2);
}

/* ---- Clone Sub-Navigation ---- */
.clone-nav {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 20px;
}

.clone-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 600;
  font-family: var(--font-sans);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    border-color var(--transition-fast),
    background var(--transition-fast);
}

.clone-nav-btn:hover {
  color: var(--text-primary);
  background: var(--surface-2);
}

.clone-nav-btn.active {
  color: var(--accent-primary);
  border-bottom-color: var(--accent-primary);
}

.clone-panel {
  display: none;
}

.clone-panel.active {
  display: block;
}

@media (max-width: 768px) {
  .overview-dashboard {
    grid-template-columns: 1fr;
  }

  .overview-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .clone-nav {
    flex-wrap: wrap;
  }

  .dep-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dep-hub-bar {
    flex-direction: column;
    align-items: flex-start;
  }
}

/* Suggestions table tweaks */
.table details summary {
  cursor: pointer;
  color: var(--accent-primary);
  font-size: var(--text-xs);
  font-weight: 500;
  user-select: none;
}

.table details summary:hover {
  color: var(--accent-secondary);
}

.table details[open] summary {
  margin-bottom: 6px;
}

.table details ol {
  margin: 0;
  padding-left: 18px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: 1.6;
}

.table .coupled-details .coupled-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.table .coupled-details .coupled-more {
  color: var(--text-muted);
  font-size: var(--text-xs);
  white-space: nowrap;
}

.table .coupled-details .coupled-expanded {
  margin-top: 6px;
}

/* Longest chain wrap */
.table td .chain {
  word-break: break-word;
  white-space: normal;
  line-height: 1.6;
}

.muted {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
}

.inline-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.source-kind-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: var(--text-xs);
  font-weight: 600;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  color: var(--text-secondary);
}

.source-kind-production {
  border-color: color-mix(in srgb, var(--success) 32%, var(--border));
  color: var(--success-strong);
}

.source-kind-tests {
  border-color: color-mix(in srgb, var(--warning) 35%, var(--border));
  color: var(--warning-strong);
}

.source-kind-fixtures {
  border-color: color-mix(in srgb, var(--accent-primary) 35%, var(--border));
  color: var(--accent-secondary);
}

.source-kind-mixed {
  border-color: color-mix(in srgb, var(--danger) 25%, var(--border));
  color: var(--danger);
}

.overview-cluster {
  margin-top: 24px;
  padding: 14px 16px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-1);
  box-shadow: var(--elevation-1);
}

.overview-cluster-header {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  margin-bottom: 12px;
}

.overview-cluster-header .subsection-title {
  margin: 0;
}

.overview-cluster-copy {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  line-height: 1.5;
  letter-spacing: 0.01em;
  max-width: 68ch;
}

.overview-cluster-empty {
  border: 1px dashed var(--border-soft);
  border-radius: 16px;
  background: var(--panel-soft);
  color: var(--text-secondary);
  padding: 16px 18px;
}

.overview-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.suggestions-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  align-items: start;
}

.overview-summary-item,
.suggestion-card {
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  padding: 16px;
  box-shadow: none;
}

.overview-summary-item {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  background: var(--surface-0);
}

.overview-summary-label {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.overview-summary-value {
  color: var(--text-primary);
  line-height: 1.55;
}

.overview-summary-list {
  margin: 0;
  padding-left: 18px;
  color: var(--text-primary);
  line-height: 1.6;
}

.overview-summary-list li + li {
  margin-top: 6px;
}

.overview-list {
  display: grid;
  gap: 12px;
}

.overview-row {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
  gap: 14px;
  align-items: start;
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  background: var(--surface-0);
  padding: 14px 16px;
}

.overview-row-main,
.overview-row-side,
.suggestion-card-head {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.overview-row-title,
.suggestion-card-title {
  font-size: 0.94rem;
  font-weight: 600;
  line-height: 1.4;
  color: var(--text-primary);
}

.overview-row-summary,
.suggestion-card-summary {
  font-size: var(--text-sm);
  line-height: 1.55;
}

.overview-row-summary {
  color: var(--text-secondary);
}

.overview-row-context,
.overview-row-location,
.suggestion-card-context {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  line-height: 1.5;
  word-break: break-word;
}

.overview-row-stats,
.suggestion-card-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.overview-row-location {
  font-family: var(--font-mono);
}

.suggestion-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: var(--surface-1);
}

.suggestion-card-summary {
  color: var(--text-primary);
  max-width: 76ch;
}

.suggestion-card-context {
  text-transform: none;
  letter-spacing: 0.01em;
}

.suggestion-sections {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 0;
}

.suggestion-disclosures {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 0;
}

.suggestion-section {
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  background: var(--surface-0);
  padding: 12px 14px;
  min-width: 0;
}

.suggestion-section-title {
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.suggestion-fact-list {
  margin: 0;
  display: grid;
  gap: 10px;
}

.suggestion-fact-list div {
  display: grid;
  gap: 4px;
}

.suggestion-fact-list dt,
.suggestion-context-line .muted {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
}

.suggestion-fact-list dd {
  margin: 0;
  color: var(--text-primary);
  line-height: 1.55;
  word-break: break-word;
}

.suggestion-empty {
  color: var(--text-secondary);
}

.suggestion-location-list,
.suggestion-steps {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--text-primary);
}

.suggestion-location-list li {
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
  margin-bottom: 10px;
}

.suggestion-location-path {
  word-break: break-word;
  font-size: var(--text-sm);
}

.suggestion-location-qualname {
  color: var(--text-secondary);
  font-size: var(--text-xs);
  word-break: break-word;
}

.suggestion-disclosure,
.suggestion-extra {
  margin: 0;
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  background: var(--surface-0);
  padding: 12px 14px;
}

.suggestion-disclosure summary,
.suggestion-extra summary {
  cursor: pointer;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: var(--text-sm);
  font-weight: 600;
  list-style: none;
}

.suggestion-disclosure-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  padding: 4px 8px;
  border-radius: 999px;
  background: color-mix(in oklab, var(--surface-3) 75%, var(--surface-0) 25%);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
}

.suggestion-disclosure[open] summary,
.suggestion-extra[open] summary {
  margin-bottom: 8px;
}

.suggestion-disclosure summary::-webkit-details-marker,
.suggestion-extra summary::-webkit-details-marker {
  display: none;
}

.finding-occurrences-more {
  margin-top: 10px;
}

.finding-occurrences-more summary {
  cursor: pointer;
  color: var(--accent-primary);
  font-size: var(--text-sm);
  font-weight: 600;
}

/* ---- Structural Findings ---- */
.sf-group {
  margin-bottom: 1rem;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-1);
  overflow: hidden;
  transition: border-color var(--transition-base);
}

.sf-group:last-child {
  margin-bottom: 0;
}

.sf-group:hover {
  border-color: color-mix(in oklab, var(--accent-primary) 25%, var(--border-default) 75%);
}

.sf-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 14px;
  flex-wrap: wrap;
  background: color-mix(in oklab, var(--surface-1) 80%, var(--surface-0) 20%);
  border-bottom: 1px solid var(--border-subtle);
}

.sf-group-body {
  padding: 0;
}

.sf-group-body .table-wrap {
  border-radius: 0;
  border: none;
  border-top: none;
}

.sf-group-body .table {
  border-radius: 0;
}

.sf-occ-count {
  font-size: var(--text-sm);
  font-weight: 600;
  white-space: nowrap;
  color: var(--text-primary);
}

.sf-kind-meta {
  font-weight: 400;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

/* ---- Suggestions toolbar (two-row layout) ---- */
.suggestions-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  margin-bottom: 14px;
  box-shadow: var(--elevation-1);
}

.suggestions-toolbar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.suggestions-toolbar-row--secondary {
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}

.suggestions-count-label {
  margin-left: auto;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

/* ---- Executive Summary 2-col grid ---- */
.overview-summary-grid--2col {
  grid-template-columns: repeat(2, minmax(240px, 1fr));
}

/* Pygments token styles */
${pyg_dark}
${pyg_light}

@media (max-width: 1280px) {
  .meta-item {
    grid-column: span 4;
  }

  .suggestions-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 980px) {
  .meta-item {
    grid-column: span 6;
  }

  .items {
    grid-template-columns: 1fr;
  }

  .overview-cluster-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .overview-row {
    grid-template-columns: 1fr;
  }

  .suggestion-sections,
  .suggestion-disclosures {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1100px) {
  .help-card .metrics-grid,
  .help-card .metrics-section:first-child .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Responsive */
@media (max-width: 768px) {
  .container {
    padding: 16px 16px 60px;
  }

  .topbar-inner {
    padding: 0 16px;
  }

  .brand h1 {
    font-size: var(--text-lg);
  }

  .section-title h2,
  h2.section-title {
    font-size: var(--text-xl);
  }

  .toolbar {
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .toolbar-left,
  .toolbar-right {
    width: 100%;
    justify-content: flex-start;
  }

  .global-novelty-head {
    align-items: flex-start;
  }

  .search-box {
    width: 100%;
  }

  .pagination {
    flex-wrap: wrap;
  }

  .meta-grid {
    grid-template-columns: repeat(1, minmax(0, 1fr));
  }

  .meta-item,
  .meta-item-wide {
    grid-column: span 1;
  }

  .metrics-grid {
    grid-template-columns: 1fr;
  }

  .help-card .metrics-grid,
  .help-card .metrics-section:first-child .metrics-grid {
    grid-template-columns: 1fr;
  }

  .global-novelty-head {
    padding: 12px 12px 0;
  }

  .novelty-note {
    padding: 10px 12px 12px;
  }

  .items {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: 1fr 1fr;
  }

  .group-head {
    padding: 12px;
  }

  .group-head-left {
    align-items: flex-start;
    gap: 10px;
  }

  .group-head-right {
    margin-left: auto;
  }


  .cmd-search {
    font-size: 1.35rem;
  }

  .suggestions-toolbar-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .suggestions-toolbar-row--secondary {
    flex-direction: column;
    align-items: flex-start;
  }

  .suggestions-count-label {
    margin-left: 0;
  }

  .overview-summary-grid--2col {
    grid-template-columns: 1fr;
  }

  .sf-group-head {
    padding: 10px 12px;
    gap: 6px;
  }
}

/* Empty State */
.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  padding: 40px 20px;
}

.empty-card {
  text-align: center;
  max-width: 480px;
  padding: 40px 32px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  box-shadow: var(--elevation-2);
}

.empty-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  margin: 0 auto 20px;
  background: var(--success-subtle);
  border-radius: 50%;
  color: var(--success);
}

.empty-card h2 {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.empty-card p {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  margin-top: 4px;
}

.empty-card .muted {
  color: var(--text-muted);
  font-size: var(--text-xs);
}

/* Section Color Accents */
section[data-section="functions"] .group {
  border-left: 3px solid #3B82F6;
}

section[data-section="blocks"] .group {
  border-left: 3px solid #10B981;
}

section[data-section="segments"] .group {
  border-left: 3px solid #F59E0B;
}

/* Print Styles */
@media print {
  .topbar,
  .toolbar,
  .btn,
  .toast-container,
  .cmd-palette,
  .metrics-modal {
    display: none !important;
  }

  .group {
    page-break-inside: avoid;
    break-inside: avoid;
  }

  .group-body {
    display: block !important;
  }

  .group-toggle {
    display: none;
  }
}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <svg class="brand-logo" width="32" height="32" viewBox="0 0 32 32" fill="none">
        <rect x="9" y="3" width="18" height="23" rx="3.5" stroke="var(--accent-primary)" stroke-width="1.5" opacity="0.25"/>
        <rect x="5" y="6" width="18" height="23" rx="3.5" stroke="var(--accent-primary)" stroke-width="1.5"/>
        <path d="M11 14L7.5 17.5 11 21" stroke="var(--accent-primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M17 14l3.5 3.5L17 21" stroke="var(--accent-primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <div class="brand-text">
        <h1>CodeClone Report${brand_project_html}</h1>
        <div class="brand-meta">${brand_meta}</div>
      </div>
    </div>
    <div class="top-actions">
      <button class="btn ghost" id="theme-toggle" aria-label="Toggle theme" title="Toggle theme (T)">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="5"/>
          <path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
        </svg>
      </button>
      <button class="btn hotkey" id="help-btn" aria-label="Open help" data-shortcut-title="mod+I">
        <span data-shortcut="mod+I"></span>
      </button>
      <button class="btn hotkey" id="cmd-btn" aria-label="Open command palette" data-shortcut-title="mod+K">
        <span data-shortcut="mod+K"></span>
      </button>
      <button class="btn primary" id="export-btn" aria-label="Export report as JSON" data-shortcut-title="mod+E">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4m14-7l-5-5m0 0L7 8m5-5v12"/>
        </svg>
        Export
      </button>
    </div>
  </div>
</div>

<div class="container">
  ${report_meta_html}
  ${analysis_tabs_html}
</div>

<footer class="report-footer" aria-label="Report footer">
  <span>Generated by CodeClone v${version}</span>
  <span class="footer-sep">•</span>
  <span>search</span>
  <span class="footer-kbd">/</span>
  <span class="footer-sep">•</span>
  <span>commands</span>
  <span class="footer-kbd" data-shortcut="mod+K"></span>
  <span class="footer-sep">•</span>
  <span>help</span>
  <span class="footer-kbd" data-shortcut="mod+I"></span>
  <span class="footer-sep">•</span>
  <span>theme</span>
  <span class="footer-kbd">T</span>
</footer>

<!-- Command Palette -->
<div class="cmd-palette" id="cmd-palette">
  <div class="cmd-palette-content">
    <input
      type="text"
      class="cmd-search"
      id="cmd-search"
      placeholder="Type a command..."
      aria-label="Command search"
    />
    <div class="cmd-list" id="cmd-list"></div>
  </div>
</div>

<!-- Metrics modal template -->
<div class="metrics-modal" id="metrics-modal">
  <div class="metrics-card">
    <div class="metrics-header">
      <h3>Clone Group Metrics</h3>
      <button class="metrics-close" id="metrics-close" aria-label="Close">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </button>
    </div>
    <div class="metrics-body" id="metrics-body">
      <!-- Filled dynamically by JavaScript -->
    </div>
  </div>
</div>

<!-- Help Modal -->
<div class="metrics-modal" id="help-modal">
  <div class="metrics-card help-card">
    <div class="metrics-header">
      <h3>Help & Support</h3>
      <button class="metrics-close" id="help-close" aria-label="Close help">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </button>
    </div>
    <div class="metrics-body">
      <div class="metrics-section">
        <div class="metrics-section-title">Quick Shortcuts</div>
        <div class="metrics-grid">
          <div class="metric-item">
            <div class="metric-label">Command Palette</div>
            <div class="metric-badge info" data-shortcut="mod+K"></div>
          </div>
          <div class="metric-item">
            <div class="metric-label">Search</div>
            <div class="metric-badge info">/</div>
          </div>
          <div class="metric-item">
            <div class="metric-label">Toggle Theme</div>
            <div class="metric-badge info">T</div>
          </div>
          <div class="metric-item">
            <div class="metric-label">Close Overlays</div>
            <div class="metric-badge info">Esc</div>
          </div>
        </div>
      </div>
      <div class="metrics-section">
        <div class="metrics-section-title">Project Links</div>
        <div class="metrics-grid">
          <div class="metric-item metric-link-item">
            <a
              class="help-link"
              href="${repository_url}"
              target="_blank"
              rel="noopener noreferrer"
              title="${repository_url}"
            >
              <span class="help-link-main">
                <span class="help-link-title">Open Repository</span>
                <span class="help-link-meta">github.com/orenlab/codeclone</span>
              </span>
              <svg class="icon help-link-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M7 17L17 7"/>
                <path d="M8 7h9v9"/>
              </svg>
            </a>
          </div>
          <div class="metric-item metric-link-item">
            <a
              class="help-link"
              href="${issues_url}"
              target="_blank"
              rel="noopener noreferrer"
              title="${issues_url}"
            >
              <span class="help-link-main">
                <span class="help-link-title">Open Issues</span>
                <span class="help-link-meta">github.com/orenlab/codeclone/issues</span>
              </span>
              <svg class="icon help-link-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M7 17L17 7"/>
                <path d="M8 7h9v9"/>
              </svg>
            </a>
          </div>
          <div class="metric-item metric-link-item">
            <a
              class="help-link"
              href="${docs_url}"
              target="_blank"
              rel="noopener noreferrer"
              title="${docs_url}"
            >
              <span class="help-link-main">
                <span class="help-link-title">Open Docs</span>
                <span class="help-link-meta">github.com/orenlab/codeclone/docs</span>
              </span>
              <svg class="icon help-link-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M7 17L17 7"/>
                <path d="M8 7h9v9"/>
              </svg>
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Structural Finding Why Modal -->
<div class="metrics-modal" id="finding-why-modal">
  <div class="metrics-card finding-why-card">
    <div class="metrics-header">
      <h3>Why This Finding Was Reported</h3>
      <button class="metrics-close" id="finding-why-close" aria-label="Close Why dialog">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 6L6 18M6 6l12 12"/>
        </svg>
      </button>
    </div>
    <div class="metrics-body" id="finding-why-body">
      <!-- Filled dynamically by JavaScript -->
    </div>
  </div>
</div>

<!-- Toast Container -->
<div class="toast-container" id="toast-container"></div>

<script>
(function () {
  'use strict';

  const $$$$ = (s) => document.querySelectorAll(s);
  const $$ = (s) => document.querySelector(s);

  const state = {
    theme: localStorage.getItem('theme') || 'dark',
    commandPaletteOpen: false,
    chartVisible: false,
    stats: {},
    findingWhyModalOpen: false,
    currentMetrics: null,
    helpModalOpen: false,
    globalNovelty: 'all',
    cloneScopeCounts: {},
    cloneTotalCounts: {}
  };
  const sectionRefreshers = [];

  // ========== Platform ==========
  const isMac = /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || '');
  const modKey = isMac ? '\u2318' : 'Ctrl+';

  function initShortcutLabels() {
    $$$$('[data-shortcut]').forEach(function (el) {
      const raw = el.getAttribute('data-shortcut') || '';
      el.textContent = raw.replace('mod+', modKey);
    });
    $$$$('[data-shortcut-title]').forEach(function (el) {
      const raw = el.getAttribute('data-shortcut-title') || '';
      el.setAttribute('title', raw.replace('mod+', modKey));
    });
  }

  // ========== Theme ==========
  function initTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
  }

  function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', state.theme);
    localStorage.setItem('theme', state.theme);
    showToast('Theme switched to ' + state.theme, 'info');
  }

  // ========== Toast ==========
  function showToast(msg, type = 'info') {
    const container = $$('#toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast ' + type;

    const icons = {
      success: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/></svg>',
      warning: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><path d="M12 9v4m0 4h.01"/></svg>',
      error: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6m0-6l6 6"/></svg>',
      info: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4m0-4h.01"/></svg>'
    };

    const safeMessage = escapeHtml(msg);
    toast.innerHTML = (icons[type] || icons.info) + '<span>' + safeMessage + '</span>';
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  // ========== Metrics Modal ==========
  function openMetricsModal(groupData) {
    const modal = $$('#metrics-modal');
    const body = $$('#metrics-body');
    if (!modal || !body) return;

    state.currentMetrics = groupData;

    // Build HTML with metrics
    let html = '';

    function formatPercent(value) {
      const raw = String(value || '').trim();
      if (!raw) return '';
      const normalized = raw.replace(/%+$$/u, '');
      if (!normalized) return '';
      return normalized + '%';
    }

    // Section: General information
    html += '<div class="metrics-section">';
    html += '<div class="metrics-section-title">General Information</div>';
    html += '<div class="metrics-grid">';

    if (groupData.clone_size) {
      html += '<div class="metric-item">';
      html += '<div class="metric-label">';
      html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3"/></svg>';
      html += 'Block Size';
      html += '</div>';
      html += '<div class="metric-value">' + escapeHtml(groupData.clone_size) + '</div>';
      html += '</div>';
    }

    if (groupData.items_count) {
      html += '<div class="metric-item">';
      html += '<div class="metric-label">';
      html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87m-4-12a4 4 0 010 7.75"/></svg>';
      html += 'Clone Instances';
      html += '</div>';
      html += '<div class="metric-value">' + escapeHtml(groupData.items_count) + '</div>';
      html += '</div>';
    }

    html += '</div></div>';

    // Section: Technical metrics
    html += '<div class="metrics-section">';
    html += '<div class="metrics-section-title">Technical Metrics</div>';
    html += '<div class="metrics-grid">';

    if (groupData.matchRule) {
      html += '<div class="metric-item">';
      html += '<div class="metric-label">';
      html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8m8 4H8m2-8H8"/></svg>';
      html += 'Match Rule';
      html += '</div>';
      html += '<div class="metric-badge info">' + escapeHtml(groupData.matchRule) + '</div>';
      html += '</div>';
    }

    if (groupData.signature_kind) {
      html += '<div class="metric-item">';
      html += '<div class="metric-label">';
      html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg>';
      html += 'Signature';
      html += '</div>';
      html += '<div class="metric-value metric-value-compact">' + escapeHtml(groupData.signature_kind) + '</div>';
      html += '</div>';
    }

    const patternDisplayValue = groupData.pattern_label || groupData.pattern;
    if (patternDisplayValue) {
      html += '<div class="metric-item">';
      html += '<div class="metric-label">';
      html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>';
      html += 'Pattern';
      html += '</div>';
      html += '<div class="metric-value metric-value-compact">' + escapeHtml(patternDisplayValue) + '</div>';
      html += '</div>';
    }

    html += '</div></div>';

    // Section: Quality metrics
    if (groupData.assert_ratio || groupData.hint_label || groupData.hint_confidence || groupData.merged_regions) {
      html += '<div class="metrics-section">';
      html += '<div class="metrics-section-title">Quality Metrics</div>';
      html += '<div class="metrics-grid">';

      if (groupData.assert_ratio) {
        const ratioText = formatPercent(groupData.assert_ratio);
        const ratio = parseFloat(ratioText);
        const badgeClass = ratio >= 70 ? 'success' : ratio >= 40 ? 'warning' : 'error';
        html += '<div class="metric-item">';
        html += '<div class="metric-label">';
        html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/></svg>';
        html += 'Assert Ratio';
        html += '</div>';
        html += '<div class="metric-badge ' + badgeClass + '">' + escapeHtml(ratioText) + '</div>';
        html += '</div>';
      }

      if (groupData.hint_label) {
        html += '<div class="metric-item">';
        html += '<div class="metric-label">';
        html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.09 9a3 3 0 115.82 1c0 2-3 3-3 3"/><path d="M12 17h.01"/><circle cx="12" cy="12" r="10"/></svg>';
        html += 'Hint';
        html += '</div>';
        html += '<div class="metric-badge warning">' + escapeHtml(groupData.hint_label) + '</div>';
        html += '</div>';
      }

      if (groupData.hint_confidence) {
        html += '<div class="metric-item">';
        html += '<div class="metric-label">';
        html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>';
        html += 'Confidence';
        html += '</div>';
        html += '<div class="metric-badge info">' + escapeHtml(groupData.hint_confidence) + '</div>';
        html += '</div>';
      }

      if (groupData.merged_regions) {
        html += '<div class="metric-item">';
        html += '<div class="metric-label">';
        html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>';
        html += 'Merged Regions';
        html += '</div>';
        html += '<div class="metric-badge warning">' + escapeHtml(groupData.merged_regions) + '</div>';
        html += '</div>';
      }

      html += '</div></div>';
    }

    // Section: Assert statistics
    if (groupData.consecutive_asserts || groupData.boilerplate_asserts) {
      html += '<div class="metrics-section">';
      html += '<div class="metrics-section-title">Assert Statistics</div>';
      html += '<div class="metrics-grid">';

      if (groupData.consecutive_asserts) {
        html += '<div class="metric-item">';
        html += '<div class="metric-label">';
        html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/></svg>';
        html += 'Consecutive Asserts';
        html += '</div>';
        html += '<div class="metric-value">' + escapeHtml(groupData.consecutive_asserts) + '</div>';
        html += '</div>';
      }

      if (groupData.boilerplate_asserts) {
        html += '<div class="metric-item">';
        html += '<div class="metric-label">';
        html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>';
        html += 'Boilerplate Asserts';
        html += '</div>';
        html += '<div class="metric-badge info">' + escapeHtml(groupData.boilerplate_asserts) + '</div>';
        html += '</div>';
      }

      html += '</div></div>';
    }

    body.innerHTML = html;
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeMetricsModal() {
    const modal = $$('#metrics-modal');
    if (!modal) return;

    modal.classList.remove('active');
    if (!state.helpModalOpen && !state.findingWhyModalOpen) {
      document.body.style.overflow = '';
    }
    state.currentMetrics = null;
  }

  function openHelpModal() {
    const modal = $$('#help-modal');
    if (!modal) return;
    modal.classList.add('active');
    state.helpModalOpen = true;
    document.body.style.overflow = 'hidden';
  }

  function closeHelpModal() {
    const modal = $$('#help-modal');
    if (!modal) return;
    modal.classList.remove('active');
    state.helpModalOpen = false;
    if (!state.currentMetrics && !state.findingWhyModalOpen) {
      document.body.style.overflow = '';
    }
  }

  function openFindingWhyModal(templateId) {
    const modal = $$('#finding-why-modal');
    const body = $$('#finding-why-body');
    const template = document.getElementById(templateId);
    if (!modal || !body || !template) return;

    if (state.currentMetrics) closeMetricsModal();
    if (state.helpModalOpen) closeHelpModal();

    body.innerHTML = template.innerHTML;
    modal.classList.add('active');
    state.findingWhyModalOpen = true;
    document.body.style.overflow = 'hidden';
  }

  function closeFindingWhyModal() {
    const modal = $$('#finding-why-modal');
    const body = $$('#finding-why-body');
    if (!modal || !body) return;

    modal.classList.remove('active');
    body.innerHTML = '';
    state.findingWhyModalOpen = false;
    if (!state.helpModalOpen && !state.currentMetrics) {
      document.body.style.overflow = '';
    }
  }

  function scrollToSection(sectionId) {
    if (typeof window.activateReportTab === 'function') {
      window.activateReportTab('clones');
    }
    const section = document.getElementById(sectionId);
    if (!section) {
      showToast('Section not found: ' + sectionId, 'warning');
      return;
    }
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function toggleMetaPanel(forceOpen) {
    const toggle = $$('.meta-toggle');
    const content = $$('.meta-content');
    if (!toggle || !content) return;

    const isCollapsed = toggle.classList.contains('collapsed');
    const open = typeof forceOpen === 'boolean' ? forceOpen : isCollapsed;
    toggle.classList.toggle('collapsed', !open);
    content.classList.toggle('collapsed', !open);
  }

  // ========== Command Palette ==========
  const commands = [
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>',
      title: 'Toggle Theme',
      desc: 'Switch between dark and light mode',
      shortcut: 'T',
      action: toggleTheme
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 115.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/></svg>',
      title: 'Open Help',
      desc: 'Open shortcuts and support links',
      shortcut: modKey + 'I',
      action: openHelpModal
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4m14-7l-5-5m0 0L7 8m5-5v12"/></svg>',
      title: 'Export Report',
      desc: 'Download report as JSON',
      shortcut: modKey + 'E',
      action: () => exportReport('json')
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4m14-7l-5-5m0 0L7 8m5-5v12"/></svg>',
      title: 'Export as PDF',
      desc: 'Open print dialog for PDF export',
      shortcut: null,
      action: () => exportReport('pdf')
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>',
      title: 'Toggle Statistics',
      desc: 'Show or hide stats dashboard',
      shortcut: null,
      action: showStats
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg>',
      title: 'Toggle Charts',
      desc: 'Show or hide clone distribution chart',
      shortcut: null,
      action: showCharts
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>',
      title: 'Expand All',
      desc: 'Expand all clone groups',
      action: expandAll
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>',
      title: 'Collapse All',
      desc: 'Collapse all clone groups',
      action: collapseAll
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 15l7-7 7 7"/></svg>',
      title: 'Scroll to Top',
      desc: 'Jump to the top of report',
      action: () => window.scrollTo(0, 0)
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 9l-7 7-7-7"/></svg>',
      title: 'Scroll to Bottom',
      desc: 'Jump to the bottom of report',
      action: () => window.scrollTo(0, document.body.scrollHeight)
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>',
      title: 'Focus Search',
      desc: 'Focus primary search input',
      shortcut: '/',
      action: () => {
        const search = getPrimarySearchInput();
        if (search) {
          search.focus();
          if (typeof search.select === 'function') search.select();
        }
      }
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4v5h.58M20 20v-5h-.58"/><path d="M5.64 19.36A9 9 0 1020 15"/></svg>',
      title: 'Refresh View',
      desc: 'Reload the report page',
      shortcut: null,
      action: () => location.reload()
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 4h18M3 12h18M3 20h18"/></svg>',
      title: 'Toggle Provenance',
      desc: 'Expand or collapse report provenance',
      action: () => toggleMetaPanel()
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h18v18H3z"/></svg>',
      title: 'Go to Function clones',
      desc: 'Scroll to function clone groups section',
      action: () => scrollToSection('functions')
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z"/><path d="M4 10h16M10 4v16"/></svg>',
      title: 'Go to Block clones',
      desc: 'Scroll to block clone groups section',
      action: () => scrollToSection('blocks')
    },
    {
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z"/><path d="M4 10h16M10 4v16"/><circle cx="16.5" cy="16.5" r="1.5"/></svg>',
      title: 'Go to Segment clones',
      desc: 'Scroll to segment clone groups section',
      action: () => scrollToSection('segments')
    }
  ];

  function initCommandPalette() {
    const palette = $$('#cmd-palette');
    const search = $$('#cmd-search');
    const list = $$('#cmd-list');
    const btn = $$('#cmd-btn');
    if (!palette || !search || !list) return;

    let filtered = commands;
    let selectedIndex = -1;

    function getItems() {
      return Array.from(list.querySelectorAll('.cmd-item'));
    }

    function setSelected(index) {
      const items = getItems();
      if (!items.length) {
        selectedIndex = -1;
        return;
      }
      selectedIndex = (index + items.length) % items.length;
      items.forEach((item, idx) => {
        const selected = idx === selectedIndex;
        item.classList.toggle('selected', selected);
        item.setAttribute('aria-selected', selected ? 'true' : 'false');
      });
      items[selectedIndex].scrollIntoView({ block: 'nearest' });
    }

    function renderCommands(filter = '') {
      const f = filter.toLowerCase();
      filtered = commands.filter(
        (c) =>
          c.title.toLowerCase().includes(f) ||
          (c.desc && c.desc.toLowerCase().includes(f))
      );

      if (!filtered.length) {
        list.innerHTML = '<div class="cmd-empty">No matching commands</div>';
        selectedIndex = -1;
        return;
      }

      list.innerHTML = filtered
        .map((c, i) => {
          const safeTitle = escapeHtml(c.title || '');
          const safeDesc = c.desc ? escapeHtml(c.desc) : '';
          const safeShortcut = c.shortcut ? escapeHtml(c.shortcut) : '';
          return (
            '<button type="button" class="cmd-item" role="option" aria-selected="false" data-cmd-index="' +
            i +
            '">' +
            '<div class="cmd-item-icon">' +
            c.icon +
            '</div>' +
            '<div class="cmd-item-text">' +
            '<div class="cmd-item-title">' +
            safeTitle +
            '</div>' +
            (safeDesc ? '<div class="cmd-item-desc">' + safeDesc + '</div>' : '') +
            '</div>' +
            (safeShortcut
              ? '<div class="cmd-item-shortcut">' + safeShortcut + '</div>'
              : '') +
            '</button>'
          );
        })
        .join('');

      getItems().forEach((el) => {
        el.addEventListener('click', () => {
          const idx = Number(el.getAttribute('data-cmd-index') || '0');
          const cmd = filtered[idx];
          if (cmd && typeof cmd.action === 'function') {
            cmd.action();
            closeCommandPalette();
          }
        });
      });

      setSelected(0);
    }

    function openCommandPalette() {
      state.commandPaletteOpen = true;
      palette.classList.add('active');
      search.value = '';
      renderCommands();
      search.focus();
    }

    function closeCommandPalette() {
      state.commandPaletteOpen = false;
      palette.classList.remove('active');
    }

    window.openCommandPalette = openCommandPalette;
    window.closeCommandPalette = closeCommandPalette;

    $$('#help-btn')?.addEventListener('click', () => {
      openHelpModal();
    });

    btn?.addEventListener('click', () => {
      if (state.commandPaletteOpen) {
        closeCommandPalette();
      } else {
        openCommandPalette();
      }
    });

    palette.addEventListener('click', (e) => {
      if (e.target === palette) closeCommandPalette();
    });

    search.addEventListener('input', (e) => {
      renderCommands(e.target.value || '');
    });

    search.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeCommandPalette();
        return;
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelected(selectedIndex + 1);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelected(selectedIndex - 1);
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        const items = getItems();
        if (!items.length || selectedIndex < 0) return;
        const selected = items[selectedIndex];
        selected.click();
      }
    });

    renderCommands();
  }

  function getPrimarySearchInput() {
    return $$('#search-blocks') || $$('#search-functions') || $$('#search-segments');
  }

  // ========== Stats ==========
  function calculateStats() {
    const groups = $$$$('.group');
    const items = $$$$('.item');

    const total = groups.length;
    const clones = items.length;
    const avgClones = total > 0 ? (clones / total).toFixed(1) : '0';
    let largest = 0;
    groups.forEach((g) => {
      const count = g.querySelectorAll('.item').length;
      if (count > largest) largest = count;
    });

    state.stats = {
      total_groups: total,
      total_clones: clones,
      avg_clones: avgClones,
      largest_group: largest
    };
  }

  function showStats() {
    const dashboard = $$('#stats-dashboard');
    if (!dashboard) return;

    const isVisible = dashboard.style.display !== 'none';
    if (isVisible) {
      dashboard.style.display = 'none';
      showToast('Statistics hidden', 'info');
      return;
    }

    calculateStats();
    dashboard.innerHTML =
      '<div class="stat-card"><div class="stat-value">' +
      state.stats.total_groups +
      '</div><div class="stat-label">Clone Groups</div></div>' +
      '<div class="stat-card"><div class="stat-value">' +
      state.stats.total_clones +
      '</div><div class="stat-label">Total Clones</div></div>' +
      '<div class="stat-card"><div class="stat-value">' +
      state.stats.avg_clones +
      '</div><div class="stat-label">Avg Group Size</div></div>' +
      '<div class="stat-card"><div class="stat-value">' +
      state.stats.largest_group +
      '</div><div class="stat-label">Largest Group</div></div>';
    dashboard.style.display = 'grid';
    showToast('Statistics displayed', 'success');
  }

  function renderComplexityChart() {
    const canvas = $$('#complexity-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;

    const labels = ['Function', 'Block', 'Segment'];
    const values = [
      $$$$('.group[data-group="functions"]').length,
      $$$$('.group[data-group="blocks"]').length,
      $$$$('.group[data-group="segments"]').length
    ];
    const max = Math.max(...values, 1);

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#9CA3AF';
    ctx.font = '12px Inter, sans-serif';

    const left = 50;
    const chartHeight = height - 50;
    const barCount = labels.length;
    const totalBarArea = width - left - 40;
    const barWidth = Math.min(90, totalBarArea / barCount * 0.6);
    const gap = totalBarArea / barCount;
    const startX = left + (gap - barWidth) / 2;

    ctx.strokeStyle = '#374151';
    ctx.beginPath();
    ctx.moveTo(left, 20);
    ctx.lineTo(left, chartHeight + 20);
    ctx.lineTo(width - 20, chartHeight + 20);
    ctx.stroke();

    const colors = ['#3B82F6', '#10B981', '#F59E0B'];
    values.forEach((val, i) => {
      const h = Math.round((val / max) * (chartHeight - 20));
      const x = startX + i * gap;
      const y = chartHeight + 20 - h;
      ctx.fillStyle = colors[i];
      ctx.fillRect(x, y, barWidth, h);
      ctx.fillStyle = '#D1D5DB';
      ctx.textAlign = 'center';
      ctx.fillText(String(val), x + barWidth / 2, y - 8);
      ctx.fillText(labels[i], x + barWidth / 2, chartHeight + 40);
    });
    ctx.textAlign = 'start';
  }

  function showCharts() {
    const chart = $$('#complexity-chart');
    if (!chart) return;
    const isVisible = chart.style.display !== 'none';
    if (isVisible) {
      chart.style.display = 'none';
      state.chartVisible = false;
      showToast('Charts hidden', 'info');
      return;
    }
    chart.style.display = 'block';
    state.chartVisible = true;
    renderComplexityChart();
    showToast('Charts displayed', 'success');
  }

  function readReportMetaFromDom() {
    const meta = {};
    $$$$('.meta-item').forEach((item) => {
      const label = item.querySelector('.meta-label')?.textContent?.trim();
      const value = item.querySelector('.meta-value')?.textContent?.trim();
      if (label && value) {
        meta[label] = value;
      }
    });
    return meta;
  }

  // ========== Export ==========
  function exportReport(format) {
    if (format === 'json') {
      const groups = Array.from($$$$('.group')).map((g) => ({
        id: g.getAttribute('data-group-id') || '',
        name: g.querySelector('.group-name')?.textContent?.trim() || '',
        items: Array.from(g.querySelectorAll('.item')).map((itemEl) => ({
          qualname: itemEl.getAttribute('data-qualname') || '',
          filepath: itemEl.getAttribute('data-filepath') || '',
          start_line: Number(itemEl.getAttribute('data-start-line') || '0'),
          end_line: Number(itemEl.getAttribute('data-end-line') || '0')
        }))
      }));
      const data = {
        generated: new Date().toISOString(),
        source: 'CodeClone HTML report',
        meta: readReportMetaFromDom(),
        stats: state.stats,
        groups
      };

      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json'
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'codeclone-report-' + Date.now() + '.json';
      a.click();
      URL.revokeObjectURL(url);

      showToast('Report exported as JSON', 'success');
      return;
    }

    if (format === 'pdf') {
      showToast('Opening print dialog for PDF export', 'info');
      window.print();
      return;
    }

    showToast('Unsupported export format: ' + format, 'warning');
  }

  // ========== Group Controls ==========
  function expandAll() {
    $$$$('.items').forEach(b => b.style.display = '');
    $$$$('[data-toggle-group]').forEach(c => c.style.transform = 'rotate(0deg)');
    showToast('All groups expanded', 'info');
  }

  function collapseAll() {
    $$$$('.items').forEach(b => b.style.display = 'none');
    $$$$('[data-toggle-group]').forEach(c => c.style.transform = 'rotate(-90deg)');
    showToast('All groups collapsed', 'info');
  }

  // ========== Keyboard Shortcuts ==========
  document.addEventListener('keydown', (e) => {
    const key = String(e.key || '').toLowerCase();

    // Command Palette: ⌘K or Ctrl+K
    if ((e.metaKey || e.ctrlKey) && key === 'k') {
      e.preventDefault();
      if (state.commandPaletteOpen) {
        window.closeCommandPalette?.();
      } else {
        window.openCommandPalette?.();
      }
      return;
    }

    // Help: ⌘I or Ctrl+I
    if ((e.metaKey || e.ctrlKey) && key === 'i') {
      e.preventDefault();
      if (state.helpModalOpen) {
        closeHelpModal();
      } else {
        openHelpModal();
      }
      return;
    }

    if (state.commandPaletteOpen) {
      if (key === 'escape') {
        e.preventDefault();
        window.closeCommandPalette?.();
      }
      return;
    }

    // Don't trigger if typing in input
    const target = e.target;
    if (
      target &&
      typeof target.matches === 'function' &&
      target.matches('input, textarea, [contenteditable="true"]')
    ) {
      return;
    }

    // / - Focus search
    if (key === '/') {
      e.preventDefault();
      const search = getPrimarySearchInput();
      search?.focus();
      if (search && typeof search.select === 'function') search.select();
    }

    // T - Toggle theme
    if (key === 't') {
      e.preventDefault();
      toggleTheme();
    }

    // E - Export
    if ((e.metaKey || e.ctrlKey) && key === 'e') {
      e.preventDefault();
      exportReport('json');
    }

    // Escape - Close modals
    if (key === 'escape') {
      if (state.helpModalOpen) {
        closeHelpModal();
      } else if (state.findingWhyModalOpen) {
        closeFindingWhyModal();
      } else if (state.currentMetrics) {
        closeMetricsModal();
      } else {
        const search = getPrimarySearchInput();
        if (search && search.value) {
          search.value = '';
          search.dispatchEvent(new Event('input', { bubbles: true }));
        }
      }
    }
  });

  // ========== Group Toggle ==========
  $$$$('.group-head').forEach((head) => {
    head.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      const btn = head.querySelector('[data-toggle-group]');
      if (btn) btn.click();
    });
  });

  $$$$('[data-toggle-group]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-toggle-group');
      const body = $$('#group-body-' + id);
      if (!body) return;

      const isHidden = body.style.display === 'none';
      body.style.display = isHidden ? '' : 'none';
      btn.style.transform = isHidden ? 'rotate(0deg)' : 'rotate(-90deg)';
    });
  });

  // ========== Metrics Button Handler ==========
  $$$$('[data-metrics-btn]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const groupId = btn.getAttribute('data-metrics-btn');
      const groupEl = $$('.group[data-group-id="' + groupId + '"]');
      if (!groupEl) return;

      // Collect all group data-* attributes
      const groupData = {
        id: groupId,
        clone_size: groupEl.getAttribute('data-clone-size'),
        items_count: groupEl.getAttribute('data-items-count'),
        matchRule: groupEl.getAttribute('data-match-rule'),
        signature_kind: groupEl.getAttribute('data-signature-kind'),
        pattern: groupEl.getAttribute('data-pattern'),
        pattern_label: groupEl.getAttribute('data-pattern-label'),
        hint_label: groupEl.getAttribute('data-hint-label'),
        assert_ratio: groupEl.getAttribute('data-assert-ratio'),
        hint_confidence: groupEl.getAttribute('data-hint-confidence'),
        merged_regions: groupEl.getAttribute('data-merged-regions'),
        consecutive_asserts: groupEl.getAttribute('data-consecutive-asserts'),
        boilerplate_asserts: groupEl.getAttribute('data-boilerplate-asserts')
      };

      openMetricsModal(groupData);
    });
  });

  // ========== Metrics Modal Close Handler ==========
  $$('#metrics-close')?.addEventListener('click', closeMetricsModal);
  $$('#metrics-modal')?.addEventListener('click', (e) => {
    if (e.target.id === 'metrics-modal') {
      closeMetricsModal();
    }
  });
  $$$$('[data-finding-why-btn]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const templateId = btn.getAttribute('data-finding-why-btn');
      if (!templateId) return;
      openFindingWhyModal(templateId);
    });
  });
  $$('#finding-why-close')?.addEventListener('click', closeFindingWhyModal);
  $$('#finding-why-modal')?.addEventListener('click', (e) => {
    if (e.target.id === 'finding-why-modal') {
      closeFindingWhyModal();
    }
  });
  $$('#help-close')?.addEventListener('click', closeHelpModal);
  $$('#help-modal')?.addEventListener('click', (e) => {
    if (e.target.id === 'help-modal') {
      closeHelpModal();
    }
  });

  function initGlobalNovelty() {
    const panel = $$('#global-novelty-controls');
    if (!panel) {
      state.globalNovelty = 'all';
      updateCloneScopeCounters();
      return;
    }

    const buttons = Array.from(panel.querySelectorAll('[data-global-novelty]'));
    if (!buttons.length) {
      state.globalNovelty = 'all';
      updateCloneScopeCounters();
      return;
    }

    const defaultNovelty = panel.getAttribute('data-default-novelty') || 'new';
    state.globalNovelty = defaultNovelty;

    function applyGlobalNoveltyButtons() {
      buttons.forEach((btn) => {
        const value = btn.getAttribute('data-global-novelty') || '';
        btn.classList.toggle('is-active', value === state.globalNovelty);
      });
      updateCloneScopeCounters();
    }

    buttons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const value = btn.getAttribute('data-global-novelty') || 'new';
        state.globalNovelty = value;
        applyGlobalNoveltyButtons();
        sectionRefreshers.forEach((refresh) => refresh());
      });
    });

    applyGlobalNoveltyButtons();
  }

  function updateCloneScopeCounters() {
    const sectionIds = ['functions', 'blocks', 'segments'];
    const isScoped = state.globalNovelty !== 'all';
    let scopedTotal = 0;
    let fullTotal = 0;

    sectionIds.forEach((sectionId) => {
      const totalRaw = state.cloneTotalCounts[sectionId];
      const scopedRaw = state.cloneScopeCounts[sectionId];
      const total = Number.isFinite(totalRaw) ? Math.max(0, totalRaw) : 0;
      const scopedBase = Number.isFinite(scopedRaw) ? scopedRaw : total;
      const scoped = Math.max(0, scopedBase);
      fullTotal += total;
      scopedTotal += scoped;

      const badge = $$('[data-clone-tab-count="' + sectionId + '"]');
      if (!badge) return;
      badge.textContent = isScoped ? scoped + ' / ' + total : String(total);
    });

    const mainBadge = $$('[data-main-clones-count]');
    if (!mainBadge) return;
    mainBadge.textContent = isScoped
      ? scopedTotal + ' / ' + fullTotal
      : String(fullTotal);
  }

  // ========== Section Management ==========
  function initSection(sectionId) {
    const section = $$('section[data-section="' + sectionId + '"]');
    if (!section) return;

    const groups = Array.from($$$$('.group[data-group="' + sectionId + '"]'));
    const searchInput = $$('#search-' + sectionId);
    const btnPrev = $$('[data-prev="' + sectionId + '"]');
    const btnNext = $$('[data-next="' + sectionId + '"]');
    const meta = $$('[data-page-meta="' + sectionId + '"]');
    const selPageSize = $$('[data-pagesize="' + sectionId + '"]');
    const btnClear = $$('[data-clear="' + sectionId + '"]');
    const btnCollapseAll = $$('[data-collapse-all="' + sectionId + '"]');
    const btnExpandAll = $$('[data-expand-all="' + sectionId + '"]');
    const sourceKindSelect = $$('[data-source-kind-filter="' + sectionId + '"]');
    const cloneTypeSelect = $$('[data-clone-type-filter="' + sectionId + '"]');
    const spreadSelect = $$('[data-spread-filter="' + sectionId + '"]');
    const minOccurrencesCheckbox = $$('[data-min-occurrences-filter="' + sectionId + '"]');
    const pill = $$('[data-count-pill="' + sectionId + '"]');
    const hasNoveltyFilter = section.getAttribute('data-has-novelty-filter') === 'true';

    const defaultNovelty = section.getAttribute('data-default-novelty') || 'all';
    const sectionState = {
      q: '',
      page: 1,
      pageSize: parseInt(selPageSize?.value || '10', 10),
      novelty: hasNoveltyFilter ? defaultNovelty : 'all',
      sourceKind: sourceKindSelect?.value || 'all',
      cloneType: cloneTypeSelect?.value || 'all',
      spread: spreadSelect?.value || 'all',
      minOccurrences: Boolean(minOccurrencesCheckbox?.checked),
      totalGroups: groups.length,
      scopeCount: groups.length,
      filtered: groups
    };

    function setGroupVisible(el, yes) {
      el.style.display = yes ? '' : 'none';
    }

    function render() {
      const total = sectionState.filtered.length;
      const pageSize = Math.max(1, sectionState.pageSize);
      const pages = Math.max(1, Math.ceil(total / pageSize));
      sectionState.page = Math.min(Math.max(1, sectionState.page), pages);

      const start = (sectionState.page - 1) * pageSize;
      const end = Math.min(total, start + pageSize);

      groups.forEach(g => setGroupVisible(g, false));
      sectionState.filtered.slice(start, end).forEach(g => setGroupVisible(g, true));

      if (meta) {
        const scoped = hasNoveltyFilter && sectionState.novelty !== 'all';
        const groupsLabel = scoped
          ? total + ' / ' + sectionState.totalGroups + ' groups'
          : total + ' groups';
        meta.textContent =
          'Page ' +
          sectionState.page +
          ' / ' +
          pages +
          ' • ' +
          groupsLabel;
      }
      if (pill) {
        const scoped = hasNoveltyFilter && sectionState.novelty !== 'all';
        pill.textContent = scoped
          ? total + ' / ' + sectionState.totalGroups + ' groups'
          : total + ' groups';
      }

      state.cloneTotalCounts[sectionId] = sectionState.totalGroups;
      state.cloneScopeCounts[sectionId] = sectionState.scopeCount;
      updateCloneScopeCounters();

      if (btnPrev) btnPrev.disabled = sectionState.page <= 1;
      if (btnNext) btnNext.disabled = sectionState.page >= pages;
    }

    function applyFilter() {
      const q = (sectionState.q || '').trim().toLowerCase();
      sectionState.novelty = hasNoveltyFilter ? state.globalNovelty : 'all';
      let noveltyFilteredGroups = groups;
      if (sectionState.novelty !== 'all') {
        noveltyFilteredGroups = noveltyFilteredGroups.filter(g => {
          const novelty = g.getAttribute('data-novelty') || '';
          return novelty === sectionState.novelty;
        });
      }
      sectionState.scopeCount = noveltyFilteredGroups.length;

      let filteredGroups = noveltyFilteredGroups;
      if (sectionState.sourceKind !== 'all') {
        filteredGroups = filteredGroups.filter(g => {
          return (g.getAttribute('data-source-kind') || '') === sectionState.sourceKind;
        });
      }
      if (sectionState.cloneType !== 'all') {
        filteredGroups = filteredGroups.filter(g => {
          return (g.getAttribute('data-clone-type') || '') === sectionState.cloneType;
        });
      }
      if (sectionState.spread !== 'all') {
        filteredGroups = filteredGroups.filter(g => {
          return (g.getAttribute('data-spread-bucket') || 'low') === sectionState.spread;
        });
      }
      if (sectionState.minOccurrences) {
        filteredGroups = filteredGroups.filter(g => {
          const count = parseInt(g.getAttribute('data-group-arity') || '0', 10);
          return Number.isFinite(count) && count >= 4;
        });
      }
      if (q) {
        filteredGroups = filteredGroups.filter(g => {
          const blob = g.getAttribute('data-search') || '';
          return blob.indexOf(q) !== -1;
        });
      }
      sectionState.filtered = filteredGroups;
      sectionState.page = 1;
      render();
    }

    searchInput?.addEventListener('input', (e) => {
      sectionState.q = e.target.value || '';
      applyFilter();
    });

    btnClear?.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      sectionState.q = '';
      applyFilter();
    });
    sourceKindSelect?.addEventListener('change', () => {
      sectionState.sourceKind = sourceKindSelect.value || 'all';
      applyFilter();
    });
    cloneTypeSelect?.addEventListener('change', () => {
      sectionState.cloneType = cloneTypeSelect.value || 'all';
      applyFilter();
    });
    spreadSelect?.addEventListener('change', () => {
      sectionState.spread = spreadSelect.value || 'all';
      applyFilter();
    });
    minOccurrencesCheckbox?.addEventListener('change', () => {
      sectionState.minOccurrences = Boolean(minOccurrencesCheckbox.checked);
      applyFilter();
    });

    selPageSize?.addEventListener('change', () => {
      sectionState.pageSize = parseInt(selPageSize.value || '10', 10);
      sectionState.page = 1;
      render();
    });

    btnPrev?.addEventListener('click', () => {
      sectionState.page -= 1;
      render();
    });

    btnNext?.addEventListener('click', () => {
      sectionState.page += 1;
      render();
    });

    btnCollapseAll?.addEventListener('click', () => {
      section.querySelectorAll('.items').forEach(b => {
        b.style.display = 'none';
      });
      section.querySelectorAll('[data-toggle-group]').forEach(c => {
        c.style.transform = 'rotate(-90deg)';
      });
    });

    btnExpandAll?.addEventListener('click', () => {
      section.querySelectorAll('.items').forEach(b => {
        b.style.display = '';
      });
      section.querySelectorAll('[data-toggle-group]').forEach(c => {
        c.style.transform = 'rotate(0deg)';
      });
    });

    sectionRefreshers.push(() => applyFilter());
    applyFilter();
  }

  // ========== Event Listeners ==========
  $$('#theme-toggle')?.addEventListener('click', toggleTheme);
  $$('#export-btn')?.addEventListener('click', () => exportReport('json'));

  // ========== Meta Panel Toggle ==========
  function initMetaPanel() {
    const header = $$('.meta-header');
    const toggle = $$('.meta-toggle');
    if (!header || !toggle) return;

    // Start collapsed by default to save space
    toggleMetaPanel(false);

    header.addEventListener('click', (e) => {
      e.preventDefault();
      toggleMetaPanel();
    });
  }

  function initTabs() {
    const tabButtons = Array.from(document.querySelectorAll('[data-tab]'));
    const tabPanels = Array.from(document.querySelectorAll('.tab-panel'));
    if (!tabButtons.length || !tabPanels.length) return;

    const activate = (tabId, updateHash = true) => {
      tabButtons.forEach((button) => {
        const isActive = button.getAttribute('data-tab') === tabId;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
      tabPanels.forEach((panel) => {
        const isActive = panel.getAttribute('data-tab-panel') === tabId;
        panel.classList.toggle('active', isActive);
      });
      if (updateHash) {
        history.replaceState(null, '', '#' + tabId);
      }
    };
    window.activateReportTab = activate;

    const hashTab = (window.location.hash || '').replace('#', '').trim();
    const hasHashTab = tabButtons.some(
      (button) => button.getAttribute('data-tab') === hashTab
    );
    activate(hasHashTab ? hashTab : 'overview', false);

    tabButtons.forEach((button) => {
      button.addEventListener('click', () => {
        const tabId = button.getAttribute('data-tab') || 'overview';
        activate(tabId);
      });
    });
  }

  function initCloneSubTabs() {
    const navBtns = Array.from($$$$('[data-clone-tab]'));
    const panels = Array.from($$$$('[data-clone-panel]'));
    if (!navBtns.length) return;

    navBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        const tabId = btn.getAttribute('data-clone-tab');
        navBtns.forEach(function (b) {
          b.classList.toggle('active', b === btn);
        });
        panels.forEach(function (p) {
          p.classList.toggle(
            'active',
            p.getAttribute('data-clone-panel') === tabId
          );
        });
      });
    });
  }

  function initSuggestionsFilters() {
    const severitySelect = $$('[data-suggestions-severity]');
    const categorySelect = $$('[data-suggestions-category]');
    const familySelect = $$('[data-suggestions-family]');
    const sourceKindSelect = $$('[data-suggestions-source-kind]');
    const spreadSelect = $$('[data-suggestions-spread]');
    const actionableCheckbox = $$('[data-suggestions-actionable]');
    const body = $$('[data-suggestions-body]');
    const count = $$('[data-suggestions-count]');
    if (!severitySelect || !categorySelect || !body) return;

    const cards = Array.from(body.querySelectorAll('[data-suggestion-card]'));
    if (!cards.length) return;

    let minCount = 0;

    window.applySuggestionQuickView = function(view) {
      minCount = 0;
      if (view === 'actionable' && actionableCheckbox) {
        actionableCheckbox.checked = true;
      }
      if (view === 'production' && sourceKindSelect) {
        sourceKindSelect.value = 'production';
      }
      if (view === 'structural') {
        if (familySelect) familySelect.value = 'structural';
        if (window.activateReportTab) window.activateReportTab('suggestions');
      }
      if (view === 'dead-code') {
        if (categorySelect) categorySelect.value = 'dead_code';
        if (window.activateReportTab) window.activateReportTab('suggestions');
      }
      if (view === 'clone-4plus') {
        if (categorySelect) categorySelect.value = 'clone';
        if (window.activateReportTab) window.activateReportTab('suggestions');
        minCount = 4;
      }
      apply();
    };

    function apply() {
      const severity = severitySelect.value || 'all';
      const category = categorySelect.value || 'all';
      const family = familySelect?.value || 'all';
      const sourceKind = sourceKindSelect?.value || 'all';
      const spread = spreadSelect?.value || 'all';
      const actionableOnly = Boolean(actionableCheckbox?.checked);
      let visibleCount = 0;

      cards.forEach((card) => {
        const rowSeverity = card.getAttribute('data-severity') || '';
        const rowCategory = card.getAttribute('data-category') || '';
        const rowFamily = card.getAttribute('data-family') || '';
        const rowSourceKind = card.getAttribute('data-source-kind') || '';
        const rowSpread = card.getAttribute('data-spread-bucket') || 'low';
        const actionable = card.getAttribute('data-actionable') === 'true';
        const rowCount = parseInt(card.getAttribute('data-count') || '0', 10);
        const severityMatch = severity === 'all' || rowSeverity === severity;
        const categoryMatch = category === 'all' || rowCategory === category;
        const familyMatch = family === 'all' || rowFamily === family;
        const sourceKindMatch = sourceKind === 'all' || rowSourceKind === sourceKind;
        const spreadMatch = spread === 'all' || rowSpread === spread;
        const actionableMatch = !actionableOnly || actionable;
        const countMatch = !minCount || (Number.isFinite(rowCount) && rowCount >= minCount);
        const visible =
          severityMatch &&
          categoryMatch &&
          familyMatch &&
          sourceKindMatch &&
          spreadMatch &&
          actionableMatch &&
          countMatch;
        card.style.display = visible ? '' : 'none';
        if (visible) visibleCount += 1;
      });

      if (count) {
        count.textContent = visibleCount + ' shown';
      }
    }

    severitySelect.addEventListener('change', apply);
    categorySelect.addEventListener('change', apply);
    familySelect?.addEventListener('change', apply);
    sourceKindSelect?.addEventListener('change', apply);
    spreadSelect?.addEventListener('change', apply);
    actionableCheckbox?.addEventListener('change', apply);
    apply();
  }

  function initStructuralFindingFilters() {
    const sourceKindSelect = $$('[data-sf-source-kind]');
    const spreadSelect = $$('[data-sf-spread]');
    const actionableCheckbox = $$('[data-sf-actionable]');
    const count = $$('[data-sf-count]');
    const groups = Array.from(document.querySelectorAll('[data-sf-group]'));
    if (!groups.length) return;

    const apply = () => {
      const sourceKind = sourceKindSelect?.value || 'all';
      const spread = spreadSelect?.value || 'all';
      const actionableOnly = Boolean(actionableCheckbox?.checked);
      let visibleCount = 0;
      groups.forEach((group) => {
        const rowSourceKind = group.getAttribute('data-source-kind') || '';
        const rowSpread = group.getAttribute('data-spread-bucket') || 'low';
        const actionable = group.getAttribute('data-actionable') === 'true';
        const visible =
          (sourceKind === 'all' || rowSourceKind === sourceKind) &&
          (spread === 'all' || rowSpread === spread) &&
          (!actionableOnly || actionable);
        group.style.display = visible ? '' : 'none';
        if (visible) visibleCount += 1;
      });
      if (count) count.textContent = visibleCount + ' shown';
    };

    sourceKindSelect?.addEventListener('change', apply);
    spreadSelect?.addEventListener('change', apply);
    actionableCheckbox?.addEventListener('change', apply);
    apply();
  }

  function initQuickViewButtons() {
    document.querySelectorAll('[data-quick-view]').forEach((button) => {
      button.addEventListener('click', () => {
        const view = button.getAttribute('data-quick-view') || '';
        if (view === 'structural') {
          if (window.activateReportTab) window.activateReportTab('structural-findings');
          return;
        }
        if (view === 'dead-code') {
          if (window.activateReportTab) window.activateReportTab('dead-code');
          return;
        }
        if (window.activateReportTab) window.activateReportTab('suggestions');
        if (window.applySuggestionQuickView) {
          window.applySuggestionQuickView(view);
        }
      });
    });
  }

  function initTableTooltips() {
    var floater = null;
    document.querySelectorAll('.table-wrap .kpi-help[data-tip]').forEach(function(el) {
      el.addEventListener('mouseenter', function() {
        var tip = el.getAttribute('data-tip');
        if (!tip) return;
        floater = document.createElement('div');
        floater.className = 'tip-float';
        floater.textContent = tip;
        document.body.appendChild(floater);
        var r = el.getBoundingClientRect();
        floater.style.left = (r.left + r.width / 2) + 'px';
        floater.style.top = (r.bottom + 8) + 'px';
      });
      el.addEventListener('mouseleave', function() {
        if (floater) { floater.remove(); floater = null; }
      });
    });
  }

  // ========== Initialize ==========
  initShortcutLabels();
  initTheme();
  initCommandPalette();
  initGlobalNovelty();
  initMetaPanel();
  initTabs();
  initCloneSubTabs();
  initSuggestionsFilters();
  initStructuralFindingFilters();
  initQuickViewButtons();
  initTableTooltips();
  initSection('functions');
  initSection('blocks');
  initSection('segments');
  calculateStats();

})();
</script>
</body>
</html>
"""
)

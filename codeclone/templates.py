"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""
# ruff: noqa: E501,RUF001,W293

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

  /* Refined Accent - Blue */
  --accent-primary: #3B82F6;
  --accent-secondary: #60A5FA;
  --accent-subtle: rgba(59, 130, 246, 0.1);
  --accent-muted: rgba(59, 130, 246, 0.05);

  /* Semantic Colors - Muted & Professional */
  --success: #10B981;
  --success-subtle: rgba(16, 185, 129, 0.1);
  --warning: #F59E0B;
  --warning-subtle: rgba(245, 158, 11, 0.1);
  --error: #EF4444;
  --error-subtle: rgba(239, 68, 68, 0.1);
  --info: #3B82F6;
  --info-subtle: rgba(59, 130, 246, 0.1);

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
  --control-radius: 10px;
  --badge-height: 22px;
  --badge-pad-x: 10px;
  --badge-font-size: 0.72rem;
  --badge-radius: 999px;

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

  --accent-primary: #2563EB;
  --accent-secondary: #3B82F6;
  --accent-subtle: rgba(37, 99, 235, 0.1);
  --accent-muted: rgba(37, 99, 235, 0.05);

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
  background:
    radial-gradient(1200px 520px at 20% -10%, rgba(59, 130, 246, 0.12), transparent 50%),
    radial-gradient(900px 420px at 110% 0%, rgba(16, 185, 129, 0.08), transparent 50%),
    var(--surface-0);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: 1.58;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

::selection {
  background: var(--accent-subtle);
  color: var(--text-primary);
}

/* Layout */
.container {
  max-width: 1520px;
  margin: 0 auto;
  padding: 26px 24px 84px;
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
  gap: 12px;
}

.brand h1 {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.brand .sub {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  background: var(--surface-2);
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
  border: 1px solid var(--border-subtle);
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
  padding: 0 32px 0 12px;
  height: var(--control-height);
  border-radius: var(--control-radius);
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-base);
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
  border-radius: 14px;
  overflow: hidden;
  box-shadow: var(--elevation-1);
}

.meta-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
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
  gap: 10px;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

.meta-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  transition: transform var(--transition-base);
  color: var(--text-tertiary);
}

.meta-toggle.collapsed {
  transform: rotate(-90deg);
}

.meta-content {
  max-height: 500px;
  opacity: 1;
  overflow: hidden;
  transition: max-height var(--transition-slow), opacity var(--transition-base);
}

.meta-content.collapsed {
  max-height: 0;
  opacity: 0;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 12px;
  padding: 10px 16px 16px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 7px;
  grid-column: span 3;
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
  border-radius: 999px;
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

.section-title h2 {
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
  border-radius: 14px;
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
  transition: all var(--transition-base);
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
  transition: all var(--transition-base);
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
  border-radius: 14px;
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

/* Единственный основной бейдж - количество клонов */
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
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(190px, auto);
  gap: 8px;
  align-items: start;
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--border-subtle);
  background: color-mix(in oklab, var(--surface-1) 82%, var(--surface-0) 18%);
  margin-bottom: 0;
}

.item-title,
.item-loc {
  min-width: 0;
}

.item-title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono);
  line-height: 1.36;
  overflow-wrap: anywhere;
}

.item-loc {
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  line-height: 1.4;
  white-space: normal;
  text-align: right;
  justify-self: end;
  overflow-wrap: anywhere;
  word-break: break-word;
  max-width: 42ch;
  opacity: 0.95;
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
  padding: 0 12px 10px;
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
  margin-top: 2px;
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
  padding: 8px 12px 10px;
  border-bottom: 1px solid var(--border-subtle);
  background: color-mix(in oklab, var(--surface-1) 75%, var(--surface-0) 25%);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  line-height: 1.45;
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
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.5;
}

.codebox code {
  display: block;
  min-width: max-content;
}

.codebox .line,
.codebox .hitline {
  white-space: pre;
}

.codebox .hitline {
  background: var(--accent-muted);
}

/* Modal для метрик - НОВОЕ */
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
  max-width: 600px;
  width: 100%;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: var(--elevation-4);
  animation: slideUp var(--transition-slow);
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
  transition: all var(--transition-base);
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
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
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
  overflow-wrap: anywhere;
}

.metric-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: var(--text-xs);
  font-weight: 500;
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
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: 16px;
  box-shadow: var(--elevation-4);
  overflow: hidden;
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
  background: var(--surface-1);
}

.cmd-item {
  width: 100%;
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
}

.cmd-item-desc {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin-top: 2px;
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
  margin-top: 24px;
  padding-top: 12px;
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

/* Pygments token styles */
${pyg_dark}
${pyg_light}

@media (max-width: 1280px) {
  .meta-item {
    grid-column: span 4;
  }
}

@media (max-width: 980px) {
  .meta-item {
    grid-column: span 6;
  }

  .items {
    grid-template-columns: 1fr;
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

  .section-title h2 {
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

  .item-header {
    grid-template-columns: 1fr;
    gap: 6px;
  }

  .item-loc {
    text-align: left;
    justify-self: start;
    max-width: 100%;
  }

  .cmd-search {
    font-size: 1.35rem;
  }
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
      <h1>CodeClone Report</h1>
      <span class="sub">v${version}</span>
    </div>
    <div class="top-actions">
      <button class="btn ghost" id="theme-toggle" aria-label="Toggle theme">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="5"/>
          <path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
        </svg>
      </button>
      <button class="btn hotkey" id="cmd-btn">
        <span>⌘K</span>
      </button>
      <button class="btn primary" id="export-btn">
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
  <div class="stats-grid" id="stats-dashboard" style="display: none;"></div>
  <div class="chart-container" id="complexity-chart" style="display: none;">
    <h3 class="chart-title">Clone Group Distribution</h3>
    <canvas id="complexity-canvas" width="1200" height="260"></canvas>
  </div>
  ${func_section}
  ${block_section}
  ${segment_section}
  ${empty_state_html}
  <footer class="report-footer" aria-label="Report footer">
    <span>Generated by CodeClone v${version}</span>
    <span class="footer-sep">•</span>
    <span>search</span>
    <span class="footer-kbd">/</span>
    <span class="footer-sep">•</span>
    <span>commands</span>
    <span class="footer-kbd">⌘K</span>
    <span class="footer-sep">•</span>
    <span>theme</span>
    <span class="footer-kbd">T</span>
  </footer>
</div>

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

<!-- Metrics Modal Template - НОВОЕ -->
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
      <!-- Динамически заполняется JavaScript -->
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
    currentMetrics: null
  };

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

  // ========== Metrics Modal - НОВОЕ ==========
  function openMetricsModal(groupData) {
    const modal = $$('#metrics-modal');
    const body = $$('#metrics-body');
    if (!modal || !body) return;

    state.currentMetrics = groupData;

    // Формируем HTML с метриками
    let html = '';

    function formatPercent(value) {
      const raw = String(value || '').trim();
      if (!raw) return '';
      return raw.endsWith('%') ? raw : raw + '%';
    }

    // Секция: Общая информация
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

    // Секция: Технические метрики
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

    if (groupData.pattern) {
      html += '<div class="metric-item">';
      html += '<div class="metric-label">';
      html += '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>';
      html += 'Pattern';
      html += '</div>';
      html += '<div class="metric-value metric-value-compact">' + escapeHtml(groupData.pattern) + '</div>';
      html += '</div>';
    }

    html += '</div></div>';

    // Секция: Качественные метрики
    if (groupData.assert_ratio || groupData.hint_confidence || groupData.merged_regions) {
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

    // Секция: Статистика assert'ов
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
    document.body.style.overflow = '';
    state.currentMetrics = null;
  }

  function scrollToSection(sectionId) {
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
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4m14-7l-5-5m0 0L7 8m5-5v12"/></svg>',
      title: 'Export Report',
      desc: 'Download report as JSON',
      shortcut: '⌘E',
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
      shortcut: '⌘S',
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
      shortcut: '⌘R',
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
        .map(
          (c, i) =>
            '<button type="button" class="cmd-item" role="option" aria-selected="false" data-cmd-index="' +
            i +
            '">' +
            '<div class="cmd-item-icon">' +
            c.icon +
            '</div>' +
            '<div class="cmd-item-text">' +
            '<div class="cmd-item-title">' +
            c.title +
            '</div>' +
            (c.desc ? '<div class="cmd-item-desc">' + c.desc + '</div>' : '') +
            '</div>' +
            (c.shortcut
              ? '<div class="cmd-item-shortcut">' + c.shortcut + '</div>'
              : '') +
            '</button>'
        )
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

    const labels = ['Function', 'Block', 'Segment'];
    const values = [
      $$$$('.group[data-group="functions"]').length,
      $$$$('.group[data-group="blocks"]').length,
      $$$$('.group[data-group="segments"]').length
    ];
    const max = Math.max(...values, 1);

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#9CA3AF';
    ctx.font = '12px Inter, sans-serif';

    const left = 50;
    const bottom = 30;
    const chartHeight = height - 50;
    const barWidth = 90;
    const gap = 140;
    const startX = left + 40;

    ctx.strokeStyle = '#374151';
    ctx.beginPath();
    ctx.moveTo(left, 20);
    ctx.lineTo(left, chartHeight + 20);
    ctx.lineTo(width - 20, chartHeight + 20);
    ctx.stroke();

    const colors = ['#60A5FA', '#10B981', '#F59E0B'];
    values.forEach((val, i) => {
      const h = Math.round((val / max) * (chartHeight - 20));
      const x = startX + i * gap;
      const y = chartHeight + 20 - h;
      ctx.fillStyle = colors[i];
      ctx.fillRect(x, y, barWidth, h);
      ctx.fillStyle = '#D1D5DB';
      ctx.fillText(String(val), x + barWidth / 2 - 5, y - 8);
      ctx.fillText(labels[i], x + 12, chartHeight + 40);
    });
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

    // S - Show stats
    if ((e.metaKey || e.ctrlKey) && key === 's') {
      e.preventDefault();
      showStats();
    }

    // E - Export
    if ((e.metaKey || e.ctrlKey) && key === 'e') {
      e.preventDefault();
      exportReport('json');
    }

    // R - Refresh view
    if ((e.metaKey || e.ctrlKey) && key === 'r') {
      e.preventDefault();
      location.reload();
    }

    // Escape - Close modals
    if (key === 'escape') {
      if (state.currentMetrics) {
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

  // ========== Metrics Button Handler - НОВОЕ ==========
  $$$$('[data-metrics-btn]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const groupId = btn.getAttribute('data-metrics-btn');
      const groupEl = $$('.group[data-group-id="' + groupId + '"]');
      if (!groupEl) return;

      // Собираем все data-атрибуты группы
      const groupData = {
        id: groupId,
        clone_size: groupEl.getAttribute('data-clone-size'),
        items_count: groupEl.getAttribute('data-items-count'),
        matchRule: groupEl.getAttribute('data-match-rule'),
        signature_kind: groupEl.getAttribute('data-signature-kind'),
        pattern: groupEl.getAttribute('data-pattern'),
        assert_ratio: groupEl.getAttribute('data-assert-ratio'),
        hint_confidence: groupEl.getAttribute('data-hint-confidence'),
        merged_regions: groupEl.getAttribute('data-merged-regions'),
        consecutive_asserts: groupEl.getAttribute('data-consecutive-asserts'),
        boilerplate_asserts: groupEl.getAttribute('data-boilerplate-asserts')
      };

      openMetricsModal(groupData);
    });
  });

  // ========== Metrics Modal Close Handler - НОВОЕ ==========
  $$('#metrics-close')?.addEventListener('click', closeMetricsModal);
  $$('#metrics-modal')?.addEventListener('click', (e) => {
    if (e.target.id === 'metrics-modal') {
      closeMetricsModal();
    }
  });

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
    const pill = $$('[data-count-pill="' + sectionId + '"]');

    const sectionState = {
      q: '',
      page: 1,
      pageSize: parseInt(selPageSize?.value || '10', 10),
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
        meta.textContent =
          'Page ' +
          sectionState.page +
          ' / ' +
          pages +
          ' • ' +
          total +
          ' groups';
      }
      if (pill) pill.textContent = total + ' groups';

      if (btnPrev) btnPrev.disabled = sectionState.page <= 1;
      if (btnNext) btnNext.disabled = sectionState.page >= pages;
    }

    function applyFilter() {
      const q = (sectionState.q || '').trim().toLowerCase();
      if (!q) {
        sectionState.filtered = groups;
      } else {
        sectionState.filtered = groups.filter(g => {
          const blob = g.getAttribute('data-search') || '';
          return blob.indexOf(q) !== -1;
        });
      }
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

    render();
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

  // ========== Initialize ==========
  initTheme();
  initCommandPalette();
  initMetaPanel();
  initSection('functions');
  initSection('blocks');
  initSection('segments');
  calculateStats();

  // Welcome message
  setTimeout(() => {
    const groupCount = $$$$('.group').length;
    if (groupCount > 0) {
      showToast(groupCount + ' clone groups loaded', 'success');
    }
  }, 500);
})();
</script>
</body>
</html>
"""
)

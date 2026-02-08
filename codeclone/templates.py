"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

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
  background: var(--surface-0);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

::selection {
  background: var(--accent-subtle);
  color: var(--text-primary);
}

/* Layout */
.container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 20px 80px;
}

/* Topbar */
.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(14, 17, 23, 0.95);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-subtle);
  box-shadow: var(--elevation-1);
}

html[data-theme="light"] .topbar {
  background: rgba(255, 255, 255, 0.95);
}

.topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 24px;
  max-width: 1400px;
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
  gap: 8px;
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: var(--radius);
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 500;
  font-family: var(--font-sans);
  transition: all var(--transition-base);
  white-space: nowrap;
  user-select: none;
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
  background: transparent;
  border-color: transparent;
  padding: 6px;
}

.btn.ghost:hover {
  background: var(--surface-2);
}

.btn.primary {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
  color: white;
}

.btn.primary:hover {
  background: var(--accent-secondary);
  border-color: var(--accent-secondary);
}

.btn.seg {
  border: none;
  background: transparent;
  height: 30px;
  padding: 6px 12px;
}

.btn.seg:hover {
  background: var(--surface-0);
}

/* Form Elements */
.select {
  padding: 8px 32px 8px 12px;
  height: 36px;
  border-radius: var(--radius);
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
  margin-top: 40px;
}

/* Meta Panel - Collapsible Pro Design 2025 */
.meta-panel {
  margin-top: 22px;
  margin-bottom: 20px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: all var(--transition-base);
}

.meta-panel:hover {
  border-color: var(--border-default);
}

.meta-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  cursor: pointer;
  user-select: none;
  transition: background var(--transition-fast);
}

.meta-header:hover {
  background: var(--surface-2);
}

.meta-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.meta-toggle {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform var(--transition-base);
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.meta-toggle.collapsed {
  transform: rotate(-90deg);
}

.meta-title {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.meta-badge {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary);
  background: var(--surface-2);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

.meta-content {
  overflow: hidden;
  transition: max-height var(--transition-slow), opacity var(--transition-base);
  max-height: 2000px;
  opacity: 1;
}

.meta-content.collapsed {
  max-height: 0;
  opacity: 0;
}

.meta-body {
  padding: 14px 16px 16px;
  border-top: 1px solid var(--border-subtle);
}

.meta-grid {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
  row-gap: 10px;
}

.meta-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: var(--surface-0);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  transition: all var(--transition-fast);
  margin: 0;
  min-width: 0;
}

.meta-row:hover {
  background: var(--surface-2);
  border-color: var(--border-default);
}

.meta-row-wide {
  grid-column: 1 / -1;
}

.meta-row dt {
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  display: flex;
  align-items: center;
  gap: 6px;
}

.meta-row dd {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.4;
  position: relative;
  overflow: hidden;
}

/* Path truncation with hover tooltip */
.meta-path {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  cursor: help;
  position: relative;
  padding: 2px 0;
}

.meta-path:hover {
  color: var(--accent-primary);
}

.meta-path-tooltip {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  background: var(--surface-3);
  color: var(--text-primary);
  padding: 8px 12px;
  border-radius: var(--radius);
  font-size: var(--text-xs);
  white-space: normal;
  word-break: break-all;
  border: 1px solid var(--border-default);
  box-shadow: var(--elevation-3);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--transition-fast);
  z-index: 1000;
  max-width: 600px;
  min-width: 200px;
}

.meta-path:hover .meta-path-tooltip {
  opacity: 1;
}

/* Boolean value badges */
.meta-bool {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
  font-family: var(--font-sans);
}

.meta-bool-true {
  background: var(--success-subtle);
  color: var(--success);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.meta-bool-false {
  background: var(--surface-2);
  color: var(--text-muted);
  border: 1px solid var(--border-default);
}

.meta-bool-na {
  background: var(--surface-2);
  color: var(--text-tertiary);
  border: 1px solid var(--border-subtle);
  font-style: italic;
}

.section-head {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.section-head h2 {
  font-size: var(--text-2xl);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 12px;
  letter-spacing: -0.01em;
}

/* Toolbar */
.section-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

@media (max-width: 768px) {
  .section-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-left,
  .toolbar-right {
    width: 100%;
    justify-content: space-between;
  }

  .search-wrap {
    min-width: 0;
    flex: 1;
  }
}

/* Search */
.search-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--border-default);
  background: var(--surface-0);
  min-width: 280px;
  transition: all var(--transition-base);
}

.search-wrap:focus-within {
  border-color: var(--accent-primary);
  background: var(--surface-1);
}

.search-ico {
  color: var(--text-muted);
  display: flex;
  flex-shrink: 0;
}

.search {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
}

.search::placeholder {
  color: var(--text-muted);
}

.segmented {
  display: inline-flex;
  background: var(--surface-2);
  padding: 2px;
  border-radius: var(--radius);
}

.pager {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm);
}

.page-meta {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  white-space: nowrap;
  min-width: 120px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* Pills */
.pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 1;
}

.pill.small {
  padding: 2px 8px;
  font-size: 11px;
}

.pill-func {
  color: var(--accent-primary);
  background: var(--accent-subtle);
  border: 1px solid var(--accent-primary);
  opacity: 0.9;
}

.pill-block {
  color: var(--success);
  background: var(--success-subtle);
  border: 1px solid var(--success);
  opacity: 0.9;
}

.pill-segment {
  color: var(--warning);
  background: var(--warning-subtle);
  border: 1px solid var(--warning);
  opacity: 0.9;
}

/* Groups */
.group {
  margin-bottom: 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-1);
  box-shadow: var(--elevation-1);
  overflow: hidden;
  transition: all var(--transition-base);
}

.group:hover {
  box-shadow: var(--elevation-2);
  border-color: var(--border-default);
}

.group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: background var(--transition-fast);
  min-width: 0;
}

.group:hover .group-head {
  background: var(--surface-3);
}

.group-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.group-title {
  font-weight: 600;
  font-size: var(--text-base);
  color: var(--text-primary);
}

.group-right {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
  justify-content: flex-end;
}

.group-basis {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 3px 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(44vw, 560px);
}

.group-explain {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.group-explain-item {
  display: inline-block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
  white-space: nowrap;
}

.group-explain-note {
  margin: 4px 0 0;
  width: 100%;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.group-explain-warn {
  color: var(--warning);
  border-color: var(--warning);
  background: var(--warning-subtle);
}

.group-explain-muted {
  color: var(--text-tertiary);
}

.gkey {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--surface-0);
  padding: 3px 6px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(52vw, 700px);
}

@media (max-width: 900px) {
  .group-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .group-right {
    width: 100%;
    justify-content: flex-start;
  }

  .gkey {
    max-width: 100%;
  }

  .group-basis {
    max-width: 100%;
  }

  .group-explain {
    justify-content: flex-start;
  }

  .group-explain-item {
    white-space: normal;
  }
}

.chev {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-muted);
  padding: 0;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.chev:hover {
  color: var(--text-primary);
  border-color: var(--accent-primary);
}

.chev svg {
  transition: transform var(--transition-base);
}

/* Items */
.items {
  padding: 16px;
  background: var(--surface-0);
}

.item-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
  min-width: 0;
}

.item-pair:last-child {
  margin-bottom: 0;
}

@media (max-width: 1200px) {
  .item-pair {
    grid-template-columns: 1fr;
  }
}

.item {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--surface-1);
}

.item:hover {
  border-color: var(--border-default);
}

.item-head {
  padding: 10px 14px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--accent-primary);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-file {
  padding: 8px 14px;
  background: var(--surface-3);
  border-bottom: 1px solid var(--border-subtle);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Code Display */
.codebox {
  position: relative;
  margin: 0;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.5;
  overflow-x: auto;
  overflow-y: auto;
  background: var(--surface-0);
  flex: 1;
  max-width: 100%;
  max-height: 600px;
}

.codebox pre {
  margin: 0;
  padding: 14px;
  white-space: pre;
  word-wrap: normal;
  overflow-wrap: normal;
  min-width: max-content;
}

.codebox code {
  display: block;
  white-space: pre;
  word-wrap: normal;
  overflow-wrap: normal;
  font-family: inherit;
  font-size: inherit;
  color: var(--text-secondary);
}

/* Empty State */
.empty {
  padding: 60px 20px;
  display: flex;
  justify-content: center;
  align-items: center;
}

.empty-card {
  text-align: center;
  padding: 40px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  max-width: 500px;
}

.empty-icon {
  color: var(--success);
  margin-bottom: 16px;
  display: flex;
  justify-content: center;
  font-size: 48px;
}

.empty-card h2 {
  font-size: var(--text-xl);
  margin-bottom: 10px;
  color: var(--text-primary);
}

.empty-card p {
  color: var(--text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: 6px;
}

.empty-card .muted {
  color: var(--text-muted);
  font-size: var(--text-sm);
}

/* Footer */
.footer {
  margin-top: 60px;
  text-align: center;
  color: var(--text-muted);
  font-size: var(--text-sm);
  border-top: 1px solid var(--border-subtle);
  padding-top: 24px;
}

.kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 6px;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-tertiary);
  box-shadow: 0 1px 0 var(--border-subtle);
}

/* Toast Notifications */
.toast-container {
  position: fixed;
  top: 80px;
  right: 20px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevation-3);
  min-width: 280px;
  max-width: 400px;
  transform: translateX(450px);
  opacity: 0;
  transition: all var(--transition-slow);
  pointer-events: auto;
}

.toast.toast-show {
  transform: translateX(0);
  opacity: 1;
}

.toast-icon {
  font-size: var(--text-lg);
  flex-shrink: 0;
}

.toast-message {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--text-primary);
}

.toast-close {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--text-lg);
  padding: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color var(--transition-fast);
}

.toast-close:hover {
  color: var(--text-primary);
}

.toast-info { border-left: 3px solid var(--info); }
.toast-success { border-left: 3px solid var(--success); }
.toast-warning { border-left: 3px solid var(--warning); }
.toast-error { border-left: 3px solid var(--error); }

/* Command Palette */
.command-palette {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: none;
}

.command-palette.show {
  display: block;
}

.command-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: fadeIn 0.2s ease-out;
}

.command-dialog {
  position: absolute;
  top: 15%;
  left: 50%;
  transform: translateX(-50%);
  width: min(90vw, 600px);
  max-height: 70vh;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevation-4);
  display: flex;
  flex-direction: column;
  animation: slideDown 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateX(-50%) translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
}

.command-input-wrap {
  padding: 16px;
  border-bottom: 1px solid var(--border-subtle);
}

.command-input {
  width: 100%;
  padding: 10px 12px;
  background: var(--surface-0);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: var(--text-base);
  font-family: var(--font-sans);
}

.command-input:focus {
  outline: 2px solid var(--accent-primary);
  outline-offset: 2px;
}

.command-input::placeholder {
  color: var(--text-muted);
}

.command-results {
  overflow-y: auto;
  max-height: calc(70vh - 80px);
  padding: 8px;
}

.command-section {
  margin-bottom: 12px;
}

.command-section-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 6px 12px;
  margin-bottom: 4px;
}

.command-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 10px 12px;
  background: transparent;
  border: none;
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.command-item:hover,
.command-item.selected,
.command-item[aria-selected='true'] {
  background: var(--accent-muted);
}

.command-item-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}

.command-icon {
  font-size: var(--text-lg);
  width: 20px;
  text-align: center;
}

.command-shortcut {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: var(--font-mono);
  background: var(--surface-2);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

.command-empty {
  color: var(--text-muted);
  font-size: var(--text-sm);
  padding: 12px;
}

/* Stats Dashboard */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin: 24px 0;
}

.stat-card {
  padding: 16px 18px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  text-align: left;
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto;
  gap: 2px 12px;
  align-items: center;
}

.stat-icon {
  grid-column: 1;
  grid-row: 1 / span 2;
  width: 38px;
  height: 38px;
  color: var(--text-tertiary);
  opacity: 0.92;
}

.stat-icon .icon {
  width: 100%;
  height: 100%;
}

.stat-value {
  grid-column: 2;
  grid-row: 1;
  font-size: var(--text-2xl);
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.1;
}

.stat-label {
  grid-column: 2;
  grid-row: 2;
  font-size: var(--text-sm);
  color: var(--text-muted);
  margin: 0;
}

.stat-trend {
  font-size: var(--text-sm);
  font-weight: 600;
}

.stat-trend.up {
  color: var(--success);
}

.stat-trend.down {
  color: var(--error);
}

.stat-trend.neutral {
  color: var(--text-muted);
}

/* Chart Container */
.chart-container {
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 20px;
  margin: 24px 0;
}

.chart-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.chart-canvas {
  width: 100%;
  height: 300px;
}

@media print {
  .topbar,
  .section-toolbar,
  .toast-container,
  .command-palette,
  .footer,
  #command-btn,
  #theme-toggle,
  #export-btn {
    display: none !important;
  }

  body {
    background: #fff;
    color: #111;
  }

  .container {
    max-width: none;
    padding: 0;
  }

  .group,
  .item {
    break-inside: avoid;
  }

  .codebox {
    max-height: none;
  }
}

/* Accessibility */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}

:focus-visible {
  outline: 2px solid var(--accent-primary);
  outline-offset: 2px;
}

/* Scrollbar */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--surface-1);
}

::-webkit-scrollbar-thumb {
  background: var(--surface-3);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--surface-4);
}

/* Syntax Highlighting */
${pyg_dark}
${pyg_light}
</style>
</head>

<body>
<!-- Toast Container -->
<div class="toast-container"></div>

<!-- Command Palette -->
<div class="command-palette" id="command-palette" aria-hidden="true">
  <div class="command-backdrop"></div>
  <div
    class="command-dialog"
    role="dialog"
    aria-modal="true"
    aria-label="Command palette"
  >
    <div class="command-input-wrap">
      <input
        type="text"
        class="command-input"
        id="command-input"
        placeholder="Type a command or search..."
        aria-label="Command search"
        autocomplete="off"
      />
    </div>
    <div
      class="command-results"
      id="command-results"
      role="listbox"
      aria-label="Command results"
    >
      <!-- Populated dynamically -->
    </div>
  </div>
</div>

<!-- Topbar -->
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <h1>${title}</h1>
      <div class="sub">v${version}</div>
    </div>
    <div class="top-actions">
      <button class="btn" type="button" id="command-btn" title="Command Palette (⌘K)">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14"></path>
        </svg>
        <span>⌘K</span>
      </button>
      <button class="btn" type="button" id="theme-toggle" title="Toggle theme (T)">
        ${icon_theme}
      </button>
      <button class="btn primary" type="button" id="export-btn" title="Export report">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="7 10 12 15 17 10"></polyline>
          <line x1="12" y1="15" x2="12" y2="3"></line>
        </svg>
        Export
      </button>
    </div>
  </div>
</div>

<!-- Main Content -->
<div class="container">

${report_meta_html}

<!-- Stats Dashboard -->
<div class="stats-grid" id="stats-dashboard" style="display: none;">
  <!-- Populated dynamically -->
</div>

<!-- Charts -->
<div class="chart-container" id="chart-container" style="display: none;">
  <div class="chart-title">Clone Group Distribution</div>
  <canvas id="complexity-chart" class="chart-canvas"></canvas>
</div>

${empty_state_html}

${func_section}
${block_section}
${segment_section}

<div class="footer">
  Generated by CodeClone v${version} •
  <kbd class="kbd">/</kbd> search •
  <kbd class="kbd">⌘K</kbd> commands •
  <kbd class="kbd">T</kbd> theme
</div>
</div>

<script>
(function() {
  'use strict';

  // ========== Utilities ==========
  const $$ = (sel) => document.querySelector(sel);
  const $$$$ = (sel) => document.querySelectorAll(sel);
  const svg = (parts) => parts.join('');
  const ICONS = {
    info: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<circle cx="12" cy="12" r="10" fill="none" stroke="currentColor"',
      ' stroke-width="2"></circle>',
      '<path d="M12 10v7" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<circle cx="12" cy="7" r="1.25" fill="currentColor"></circle>',
      '</svg>'
    ]),
    success: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<circle cx="12" cy="12" r="10" fill="none" stroke="currentColor"',
      ' stroke-width="2"></circle>',
      '<path d="M7 12l3 3 7-7" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    warning: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M12 3l10 18H2L12 3z" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M12 9v5" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<circle cx="12" cy="17" r="1.25" fill="currentColor"></circle>',
      '</svg>'
    ]),
    error: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<circle cx="12" cy="12" r="10" fill="none" stroke="currentColor"',
      ' stroke-width="2"></circle>',
      '<path d="M8 8l8 8M16 8l-8 8" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    exportJson: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M12 3v12" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M7 10l5 5 5-5" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M5 21h14" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    exportPdf: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M6 2h9l5 5v15H6z" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M15 2v5h5" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    stats: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M4 20V10M10 20V4M16 20v-8M22 20V7" fill="none"',
      ' stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ]),
    charts: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M4 20h16" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M6 16l4-4 4 3 4-6" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    refresh: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M20 6v6h-6" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M4 18v-6h6" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M20 12a8 8 0 0 0-14-5" fill="none"',
      ' stroke="currentColor" stroke-width="2"></path>',
      '<path d="M4 12a8 8 0 0 0 14 5" fill="none"',
      ' stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ]),
    search: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor"',
      ' stroke-width="2"></circle>',
      '<path d="M20 20l-3.5-3.5" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    scrollTop: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M12 19V5" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M5 12l7-7 7 7" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    scrollBottom: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M12 5v14" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '<path d="M5 12l7 7 7-7" fill="none" stroke="currentColor"',
      ' stroke-width="2"></path>',
      '</svg>'
    ]),
    theme: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M21 12a9 9 0 1 1-9-9 7 7 0 0 0 9 9z"',
      ' fill="none" stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ]),
    expand: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M8 3H3v5M21 8V3h-5M3 16v5h5M21 21v-5h-5"',
      ' fill="none" stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ]),
    collapse: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M8 3v5H3M21 8h-5V3M3 16h5v5M16 21v-5h5"',
      ' fill="none" stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ]),
    cloneGroups: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<rect x="3" y="4" width="8" height="8" fill="none"',
      ' stroke="currentColor" stroke-width="2"></rect>',
      '<rect x="13" y="4" width="8" height="8" fill="none"',
      ' stroke="currentColor" stroke-width="2"></rect>',
      '<rect x="3" y="14" width="8" height="8" fill="none"',
      ' stroke="currentColor" stroke-width="2"></rect>',
      '</svg>'
    ]),
    totalClones: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<rect x="4" y="3" width="16" height="18" rx="2" fill="none"',
      ' stroke="currentColor" stroke-width="2"></rect>',
      '<path d="M8 7h8M8 11h8M8 15h5" fill="none"',
      ' stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ]),
    avgGroup: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M4 18h16M6 15l3-4 4 3 5-7" fill="none"',
      ' stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ]),
    largestGroup: svg([
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">',
      '<path d="M12 3l3 6 6 1-4 4 1 6-6-3-6 3 1-6-4-4',
      ' 6-1 3-6z" fill="none" stroke="currentColor" stroke-width="2"></path>',
      '</svg>'
    ])
  };

  // ========== State Management ==========
  const state = {
    theme: 'dark',
    commandPaletteOpen: false,
    chartVisible: false,
    stats: {
      totalGroups: 0,
      totalItems: 0,
      avgGroupSize: 0,
      largestGroup: 0
    }
  };

  function getPrimarySearchInput() {
    const inputs = Array.from($$$$('.search'));
    for (const input of inputs) {
      if (input.offsetParent !== null) return input;
    }
    return inputs[0] || null;
  }

  // ========== Theme Management ==========
  function initTheme() {
    const stored = localStorage.getItem('codeclone_theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const hour = new Date().getHours();
    const isNight = hour < 7 || hour > 19;

    state.theme = stored || (prefersDark || isNight ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', state.theme);
  }

  function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', state.theme);
    localStorage.setItem('codeclone_theme', state.theme);
    if (state.chartVisible) renderComplexityChart();
    showToast('Theme switched to ' + state.theme, 'info');
  }

  // ========== Toast Notifications ==========
  function showToast(message, type = 'info') {
    const icons = {
      info: ICONS.info,
      success: ICONS.success,
      warning: ICONS.warning,
      error: ICONS.error
    };

    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.innerHTML =
      '<span class="toast-icon">' + icons[type] + '</span>' +
      '<span class="toast-message">' + message + '</span>' +
      '<button class="toast-close" aria-label="Close">x</button>';

    const container = $$('.toast-container');
    container.appendChild(toast);

    setTimeout(() => toast.classList.add('toast-show'), 10);

    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.classList.remove('toast-show');
      setTimeout(() => toast.remove(), 300);
    });

    setTimeout(() => {
      toast.classList.remove('toast-show');
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  window.showToast = showToast;

  // ========== Command Palette ==========
  function initCommandPalette() {
    const palette = $$('#command-palette');
    const input = $$('#command-input');
    const results = $$('#command-results');
    if (!palette || !input || !results) return;
    let selectedIndex = -1;

    const commands = [
      {
        section: 'Actions',
        items: [
          {
            icon: ICONS.exportJson,
            label: 'Export as JSON',
            shortcut: '⌘E',
            action: () => exportReport('json')
          },
          {
            icon: ICONS.exportPdf,
            label: 'Export as PDF',
            shortcut: null,
            action: () => exportReport('pdf')
          },
          {
            icon: ICONS.stats,
            label: 'Toggle Statistics',
            shortcut: '⌘S',
            action: () => showStats()
          },
          {
            icon: ICONS.charts,
            label: 'Toggle Charts',
            shortcut: null,
            action: () => showCharts()
          },
          {
            icon: ICONS.refresh,
            label: 'Refresh View',
            shortcut: '⌘R',
            action: () => location.reload()
          }
        ]
      },
      {
        section: 'Navigation',
        items: [
          {
            icon: ICONS.search,
            label: 'Focus Search',
            shortcut: '/',
            action: () => {
              const search = getPrimarySearchInput();
              if (!search) {
                showToast('Search is not available in this report', 'warning');
                return;
              }
              search.focus();
              if (typeof search.select === 'function') search.select();
            }
          },
          {
            icon: ICONS.scrollTop,
            label: 'Scroll to Top',
            shortcut: null,
            action: () => window.scrollTo(0, 0)
          },
          {
            icon: ICONS.scrollBottom,
            label: 'Scroll to Bottom',
            shortcut: null,
            action: () => window.scrollTo(0, document.body.scrollHeight)
          }
        ]
      },
      {
        section: 'View',
        items: [
          {
            icon: ICONS.theme,
            label: 'Toggle Theme',
            shortcut: 'T',
            action: () => toggleTheme()
          },
          {
            icon: ICONS.expand,
            label: 'Expand All',
            shortcut: null,
            action: () => expandAll()
          },
          {
            icon: ICONS.collapse,
            label: 'Collapse All',
            shortcut: null,
            action: () => collapseAll()
          }
        ]
      }
    ];

    function getVisibleCommandItems() {
      return Array.from(results.querySelectorAll('.command-item'));
    }

    function setSelected(index) {
      const items = getVisibleCommandItems();
      if (!items.length) {
        selectedIndex = -1;
        return;
      }
      selectedIndex = (index + items.length) % items.length;
      items.forEach((item, idx) => {
        const isSelected = idx === selectedIndex;
        item.classList.toggle('selected', isSelected);
        item.setAttribute('aria-selected', isSelected ? 'true' : 'false');
      });
      items[selectedIndex].scrollIntoView({ block: 'nearest' });
    }

    function renderCommands(filter = '') {
      const f = filter.toLowerCase();
      results.innerHTML = '';
      let rendered = 0;

      commands.forEach(section => {
        const filtered = section.items.filter(item =>
          !f || item.label.toLowerCase().includes(f)
        );

        if (filtered.length === 0) return;

        const sectionEl = document.createElement('div');
        sectionEl.className = 'command-section';
        sectionEl.innerHTML =
          '<div class="command-section-title">' +
          section.section +
          '</div>';

        filtered.forEach((item) => {
          const btn = document.createElement('button');
          btn.className = 'command-item';
          btn.type = 'button';
          btn.setAttribute('role', 'option');
          btn.setAttribute('aria-selected', 'false');
          btn.innerHTML =
            '<div class="command-item-left">' +
            '<span class="command-icon">' + item.icon + '</span>' +
            '<span>' + item.label + '</span>' +
            '</div>' +
            (item.shortcut
              ? '<kbd class="command-shortcut">' + item.shortcut + '</kbd>'
              : '');
          btn.addEventListener('click', () => {
            item.action();
            closeCommandPalette();
          });
          btn.addEventListener('mouseenter', () => {
            const items = getVisibleCommandItems();
            const hoverIndex = items.indexOf(btn);
            if (hoverIndex >= 0) setSelected(hoverIndex);
          });
          sectionEl.appendChild(btn);
          rendered += 1;
        });

        results.appendChild(sectionEl);
      });

      if (rendered === 0) {
        const empty = document.createElement('div');
        empty.className = 'command-empty';
        empty.textContent = 'No matching commands';
        results.appendChild(empty);
      }
      setSelected(0);
    }

    function openCommandPalette() {
      state.commandPaletteOpen = true;
      palette.classList.add('show');
      palette.setAttribute('aria-hidden', 'false');
      input.value = '';
      renderCommands();
      input.focus();
    }

    function closeCommandPalette() {
      state.commandPaletteOpen = false;
      palette.classList.remove('show');
      palette.setAttribute('aria-hidden', 'true');
      input.value = '';
    }

    $$('#command-btn')?.addEventListener('click', openCommandPalette);
    $$('.command-backdrop')?.addEventListener('click', closeCommandPalette);

    input?.addEventListener('input', (e) => {
      renderCommands(e.target.value);
    });

    input?.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeCommandPalette();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelected(selectedIndex + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelected(selectedIndex - 1);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const selected = $$('.command-item.selected');
        if (selected) selected.click();
      }
    });

    window.openCommandPalette = openCommandPalette;
    window.closeCommandPalette = closeCommandPalette;
  }

  // ========== Statistics ==========
  function calculateStats() {
    const groups = $$$$('.group');
    const items = $$$$('.item');

    state.stats.totalGroups = groups.length;
    state.stats.totalItems = items.length;
    state.stats.avgGroupSize = groups.length > 0
      ? Math.round(items.length / groups.length)
      : 0;

    let largest = 0;
    groups.forEach(g => {
      const count = g.querySelectorAll('.item').length;
      if (count > largest) largest = count;
    });
    state.stats.largestGroup = largest;
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

    const stats = [
      {
        icon: ICONS.cloneGroups,
        value: state.stats.totalGroups,
        label: 'Clone Groups',
        trend: null
      },
      {
        icon: ICONS.totalClones,
        value: state.stats.totalItems,
        label: 'Total Clones',
        trend: null
      },
      {
        icon: ICONS.avgGroup,
        value: state.stats.avgGroupSize,
        label: 'Avg Group Size',
        trend: null
      },
      {
        icon: ICONS.largestGroup,
        value: state.stats.largestGroup,
        label: 'Largest Group',
        trend: null
      }
    ];

    dashboard.innerHTML = stats.map(s => {
      const trend = s.trend
        ? '<div class="stat-trend ' + s.trend.type + '">' + s.trend.text + '</div>'
        : '';
      return (
        '<div class="stat-card">' +
        '<div class="stat-icon">' + s.icon + '</div>' +
        '<div class="stat-value">' + s.value + '</div>' +
        '<div class="stat-label">' + s.label + '</div>' +
        trend +
        '</div>'
      );
    }).join('');

    dashboard.style.display = 'grid';
    showToast('Statistics displayed', 'success');
  }

  function collectSectionMetrics() {
    const sections = [
      { id: 'functions', label: 'Function', colorVar: '--accent-primary' },
      { id: 'blocks', label: 'Block', colorVar: '--success' },
      { id: 'segments', label: 'Segment', colorVar: '--warning' }
    ];
    return sections.map((section) => {
      const groups = Array.from($$$$('.group[data-group="' + section.id + '"]'));
      return {
        label: section.label,
        colorVar: section.colorVar,
        value: groups.length
      };
    });
  }

  function renderComplexityChart() {
    const canvas = $$('#complexity-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const rect = canvas.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width || 320));
    const height = Math.max(220, Math.floor(rect.height || 300));
    const ratio = Math.max(1, window.devicePixelRatio || 1);

    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const styles = getComputedStyle(document.documentElement);
    const textPrimary = styles.getPropertyValue('--text-primary').trim() || '#d1d5db';
    const textMuted = styles.getPropertyValue('--text-muted').trim() || '#9ca3af';
    const gridColor = styles.getPropertyValue('--border-subtle').trim() || '#334155';
    const sansFont =
      'ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';

    const metrics = collectSectionMetrics();
    const maxValue = Math.max(1, ...metrics.map((m) => m.value));
    const yMax = Math.max(4, Math.ceil(maxValue / 4) * 4);
    const left = 52;
    const right = 18;
    const top = 16;
    const bottom = 40;
    const chartWidth = width - left - right;
    const chartHeight = height - top - bottom;

    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    for (let step = 0; step <= 4; step += 1) {
      const y = top + (chartHeight * step) / 4;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(left + chartWidth, y);
      ctx.stroke();

      const value = Math.round(yMax - (yMax * step) / 4);
      ctx.fillStyle = textMuted;
      ctx.font = '12px ' + sansFont;
      ctx.textAlign = 'right';
      ctx.fillText(String(value), left - 8, y + 4);
    }

    const slot = chartWidth / metrics.length;
    const barWidth = Math.max(40, Math.min(90, slot * 0.56));
    metrics.forEach((metric, idx) => {
      const x = left + slot * idx + (slot - barWidth) / 2;
      const barHeight = (metric.value / yMax) * chartHeight;
      const y = top + chartHeight - barHeight;
      const color = styles.getPropertyValue(metric.colorVar).trim() || '#4f46e5';

      ctx.fillStyle = color;
      ctx.fillRect(x, y, barWidth, barHeight);

      ctx.fillStyle = textPrimary;
      ctx.font = '600 12px ' + sansFont;
      ctx.textAlign = 'center';
      ctx.fillText(String(metric.value), x + barWidth / 2, y - 6);

      ctx.fillStyle = textMuted;
      ctx.font = '12px ' + sansFont;
      ctx.fillText(metric.label, x + barWidth / 2, top + chartHeight + 18);
    });

    if (metrics.every((metric) => metric.value === 0)) {
      ctx.fillStyle = textMuted;
      ctx.font = '14px ' + sansFont;
      ctx.textAlign = 'center';
      ctx.fillText(
        'No clone groups to visualize',
        left + chartWidth / 2,
        top + chartHeight / 2
      );
    }
  }

  // ========== Charts ==========
  function showCharts() {
    const container = $$('#chart-container');
    if (!container) return;
    const visible = container.style.display !== 'none';
    if (visible) {
      container.style.display = 'none';
      state.chartVisible = false;
      showToast('Charts hidden', 'info');
      return;
    }
    container.style.display = 'block';
    state.chartVisible = true;
    renderComplexityChart();
    showToast('Charts displayed', 'success');
  }

  function readReportMetaFromDom() {
    const metaEl = $$('#report-meta');
    if (!metaEl) return {};

    const boolAttr = (name) => {
      const value = (metaEl.getAttribute(name) || '').toLowerCase();
      if (value === 'true') return true;
      if (value === 'false') return false;
      return null;
    };
    const textAttr = (name) => {
      const value = (metaEl.getAttribute(name) || '').trim();
      return value || null;
    };
    const intAttr = (name) => {
      const value = textAttr(name);
      if (value === null) return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    };

    return {
      codeclone_version: textAttr('data-codeclone-version'),
      python_version: textAttr('data-python-version'),
      baseline_file: textAttr('data-baseline-file'),
      baseline_path: textAttr('data-baseline-path'),
      baseline_fingerprint_version: textAttr('data-baseline-fingerprint-version'),
      baseline_schema_version: textAttr('data-baseline-schema-version'),
      baseline_python_tag: textAttr('data-baseline-python-tag'),
      baseline_generator_version: textAttr('data-baseline-generator-version'),
      baseline_loaded: boolAttr('data-baseline-loaded'),
      baseline_status: textAttr('data-baseline-status'),
      cache_path: textAttr('data-cache-path'),
      cache_used: boolAttr('data-cache-used')
    };
  }

  // ========== Export ==========
  function exportReport(format) {
    calculateStats();
    if (format === 'json') {
      const groups = Array.from($$$$('.group')).map((groupEl) => ({
        section: groupEl.getAttribute('data-group') || '',
        group_index: Number(groupEl.getAttribute('data-group-index') || '0'),
        group_key: groupEl.getAttribute('data-group-key') || '',
        items: Array.from(groupEl.querySelectorAll('.item')).map((itemEl) => ({
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
      const search = getPrimarySearchInput();
      if (search && search.value) {
        search.value = '';
        search.dispatchEvent(new Event('input', { bubbles: true }));
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
  window.addEventListener('resize', () => {
    if (state.chartVisible) renderComplexityChart();
  });

  // ========== Meta Panel Toggle ==========
  function initMetaPanel() {
    const header = $$('.meta-header');
    const toggle = $$('.meta-toggle');
    const content = $$('.meta-content');

    if (!header || !toggle || !content) return;

    // Start collapsed by default to save space
    const startCollapsed = true;
    if (startCollapsed) {
      toggle.classList.add('collapsed');
      content.classList.add('collapsed');
    }

    header.addEventListener('click', (e) => {
      const isCollapsed = toggle.classList.contains('collapsed');

      if (isCollapsed) {
        toggle.classList.remove('collapsed');
        content.classList.remove('collapsed');
      } else {
        toggle.classList.add('collapsed');
        content.classList.add('collapsed');
      }
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

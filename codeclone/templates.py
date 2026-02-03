"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from string import Template

REPORT_TEMPLATE = Template(r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>

<!-- Fonts -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

<style>
/* ============================
   CodeClone UI/UX
   ============================ */

/* ========== Design Tokens ========== */
:root {
  /* Brand Colors - Purple/Cyan Identity */
  --brand-purple: #8B5CF6;
  --brand-cyan: #06B6D4;
  --brand-pink: #EC4899;
  --brand-amber: #F59E0B;
  
  /* Surface Hierarchy */
  --surface-0: #0A0A0F;
  --surface-1: #141419;
  --surface-2: #1E1E24;
  --surface-3: #28282F;
  --surface-4: #32323A;
  
  /* Text */
  --text-primary: #F9FAFB;
  --text-secondary: #D1D5DB;
  --text-tertiary: #9CA3AF;
  --text-muted: #6B7280;
  
  /* Borders */
  --border-subtle: #2D2D35;
  --border-default: #3F3F46;
  --border-strong: #52525B;
  
  /* Semantic */
  --success: #10B981;
  --warning: #F59E0B;
  --error: #EF4444;
  --info: #3B82F6;
  
  /* Gradients */
  --gradient-primary: linear-gradient(135deg, var(--brand-purple) 0%, var(--brand-cyan) 100%);
  --gradient-accent: linear-gradient(135deg, var(--brand-pink) 0%, var(--brand-amber) 100%);
  --gradient-subtle: linear-gradient(180deg, transparent 0%, rgba(139, 92, 246, 0.05) 100%);
  --gradient-mesh: 
    radial-gradient(at 0% 0%, rgba(139, 92, 246, 0.15) 0px, transparent 50%),
    radial-gradient(at 100% 100%, rgba(6, 182, 212, 0.15) 0px, transparent 50%);
  
  /* Elevation */
  --elevation-0: none;
  --elevation-1: 0 1px 3px rgba(0, 0, 0, 0.3), 0 1px 2px rgba(0, 0, 0, 0.4);
  --elevation-2: 0 3px 6px rgba(0, 0, 0, 0.35), 0 2px 4px rgba(0, 0, 0, 0.3);
  --elevation-3: 0 10px 20px rgba(0, 0, 0, 0.4), 0 3px 6px rgba(0, 0, 0, 0.3);
  --elevation-4: 0 15px 25px rgba(0, 0, 0, 0.45), 0 5px 10px rgba(0, 0, 0, 0.25);
  --elevation-glow: 0 0 20px rgba(139, 92, 246, 0.3);
  
  /* Glassmorphism */
  --glass-bg: rgba(20, 20, 25, 0.7);
  --glass-border: rgba(255, 255, 255, 0.1);
  --glass-blur: blur(20px);
  
  /* Typography Scale (1.25 ratio) */
  --text-xs: 0.75rem;      /* 12px */
  --text-sm: 0.875rem;     /* 14px */
  --text-base: 1rem;       /* 16px */
  --text-lg: 1.125rem;     /* 18px */
  --text-xl: 1.25rem;      /* 20px */
  --text-2xl: 1.563rem;    /* 25px */
  --text-3xl: 1.953rem;    /* 31px */
  
  /* Font Families */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
  
  /* Line Heights */
  --leading-tight: 1.25;
  --leading-normal: 1.5;
  --leading-relaxed: 1.75;
  
  /* Border Radius */
  --radius-sm: 4px;
  --radius: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 9999px;
  
  /* Transitions */
  --transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-base: 300ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-slow: 500ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-spring: 600ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

html[data-theme="light"] {
  /* Surface Hierarchy */
  --surface-0: #FFFFFF;
  --surface-1: #F9FAFB;
  --surface-2: #F3F4F6;
  --surface-3: #E5E7EB;
  --surface-4: #D1D5DB;
  
  /* Text */
  --text-primary: #111827;
  --text-secondary: #374151;
  --text-tertiary: #6B7280;
  --text-muted: #9CA3AF;
  
  /* Borders */
  --border-subtle: #E5E7EB;
  --border-default: #D1D5DB;
  --border-strong: #9CA3AF;
  
  /* Elevation */
  --elevation-1: 0 1px 3px rgba(0, 0, 0, 0.1), 0 1px 2px rgba(0, 0, 0, 0.06);
  --elevation-2: 0 4px 6px rgba(0, 0, 0, 0.1), 0 2px 4px rgba(0, 0, 0, 0.06);
  --elevation-3: 0 10px 15px rgba(0, 0, 0, 0.1), 0 4px 6px rgba(0, 0, 0, 0.05);
  --elevation-4: 0 20px 25px rgba(0, 0, 0, 0.1), 0 10px 10px rgba(0, 0, 0, 0.04);
  --elevation-glow: 0 0 20px rgba(139, 92, 246, 0.2);
  
  /* Glassmorphism */
  --glass-bg: rgba(249, 250, 251, 0.8);
  --glass-border: rgba(0, 0, 0, 0.1);
}

/* ========== Global Styles ========== */
* { 
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html {
  scroll-behavior: smooth;
}

body {
  background: var(--surface-0);
  background-image: var(--gradient-mesh);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow-x: hidden;
}

::selection {
  background: rgba(139, 92, 246, 0.3);
  color: var(--text-primary);
}

/* ========== Layout ========== */
.container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 20px 80px;
}

/* ========== Topbar ========== */
.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border-bottom: 1px solid var(--glass-border);
  box-shadow: var(--elevation-2);
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
  background: var(--gradient-primary);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.02em;
}

.brand .sub {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  background: var(--surface-2);
  padding: 3px 10px;
  border-radius: var(--radius-full);
  font-weight: 600;
  border: 1px solid var(--border-subtle);
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ========== Buttons ========== */
.btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  color: var(--text-primary);
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 500;
  font-family: var(--font-sans);
  transition: all var(--transition-base);
  overflow: hidden;
  white-space: nowrap;
  user-select: none;
}

.btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
  transform: translateX(-100%);
  transition: transform var(--transition-slow);
}

.btn:hover {
  transform: translateY(-2px);
  box-shadow: var(--elevation-2);
  border-color: var(--border-strong);
  background: var(--surface-3);
}

.btn:hover::before {
  transform: translateX(100%);
}

.btn:active {
  transform: translateY(0);
  box-shadow: var(--elevation-1);
}

.btn:focus-visible {
  outline: 2px solid var(--brand-purple);
  outline-offset: 2px;
}

.btn.ghost {
  background: transparent;
  border-color: transparent;
  padding: 8px;
}

.btn.ghost:hover {
  background: var(--surface-2);
  transform: scale(1.05);
}

.btn.primary {
  background: var(--gradient-primary);
  border-color: transparent;
  color: white;
  font-weight: 600;
}

.btn.primary:hover {
  box-shadow: var(--elevation-glow);
}

/* ========== Form Elements ========== */
.select {
  padding: 8px 32px 8px 12px;
  height: 36px;
  border-radius: var(--radius);
  border: 1px solid var(--border-default);
  background: var(--surface-2);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--transition-base);
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%239CA3AF' d='M6 8L2 4h8z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
}

.select:hover {
  border-color: var(--border-strong);
  background-color: var(--surface-3);
}

.select:focus {
  outline: 2px solid var(--brand-purple);
  outline-offset: 2px;
}

/* ========== Section ========== */
.section {
  margin-top: 48px;
  animation: fadeInUp 0.6s var(--transition-spring);
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.section-head {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 24px;
}

.section-head h2 {
  font-size: var(--text-2xl);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 12px;
  letter-spacing: -0.02em;
}

/* ========== Toolbar ========== */
.section-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--elevation-1);
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

/* ========== Search ========== */
.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--border-default);
  background: var(--surface-0);
  min-width: 300px;
  transition: all var(--transition-base);
}

.search-wrap:focus-within {
  border-color: var(--brand-purple);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.1);
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
  padding: 3px;
  border-radius: var(--radius);
  border: 1px solid var(--border-subtle);
}

.btn.seg {
  border: none;
  background: transparent;
  height: 32px;
  font-size: var(--text-sm);
  border-radius: calc(var(--radius) - 3px);
}

.btn.seg:hover {
  background: var(--surface-0);
  box-shadow: var(--elevation-1);
}

/* ========== Pager ========== */
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

/* ========== Pills/Badges ========== */
.pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.pill.small {
  padding: 2px 8px;
  font-size: 10px;
}

.pill-func {
  color: var(--brand-purple);
  background: rgba(139, 92, 246, 0.15);
  border: 1px solid rgba(139, 92, 246, 0.3);
}

.pill-block {
  color: var(--success);
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
}

/* ========== Groups/Cards ========== */
.group {
  margin-bottom: 20px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-1);
  box-shadow: var(--elevation-1);
  overflow: hidden;
  transition: all var(--transition-base);
}

.group:hover {
  transform: translateY(-2px);
  box-shadow: var(--elevation-3);
  border-color: var(--brand-purple);
}

.group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.group:hover .group-head {
  background: var(--gradient-subtle);
}

.group-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.group-title {
  font-weight: 600;
  font-size: var(--text-base);
  color: var(--text-primary);
}

.group-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.gkey {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--surface-0);
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

/* ========== Chevron Button ========== */
.chev {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius);
  border: 1px solid var(--border-default);
  background: var(--surface-1);
  color: var(--text-muted);
  padding: 0;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.chev:hover {
  color: var(--text-primary);
  border-color: var(--brand-purple);
  background: var(--surface-2);
  transform: scale(1.1);
}

.chev svg {
  transition: transform var(--transition-base);
}

/* ========== Items Container ========== */
.items {
  padding: 20px;
  background: var(--surface-0);
}

.item-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
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

/* ========== Item Card ========== */
.item {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--surface-1);
  transition: all var(--transition-base);
}

.item:hover {
  border-color: var(--brand-cyan);
  box-shadow: var(--elevation-2);
}

.item-head {
  padding: 12px 16px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border-subtle);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--brand-purple);
  font-family: var(--font-mono);
}

.item-file {
  padding: 8px 16px;
  background: var(--surface-3);
  border-bottom: 1px solid var(--border-subtle);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* ========== Code Display ========== */
.codebox {
  position: relative;
  margin: 0;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  overflow-x: auto;
  overflow-y: auto;
  background: var(--surface-0);
  flex: 1;
  max-width: 100%;
  max-height: 600px;
}

.codebox pre {
  margin: 0;
  padding: 16px;
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

/* Copy button for code blocks */
.copy-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  opacity: 0;
  transition: all var(--transition-base);
  z-index: 10;
}

.codebox:hover .copy-btn {
  opacity: 1;
}

.copy-btn:hover {
  background: var(--surface-3);
  border-color: var(--brand-purple);
  color: var(--text-primary);
}

.copy-btn.copied {
  background: var(--success);
  border-color: var(--success);
  color: white;
}

/* ========== Empty State ========== */
.empty {
  padding: 80px 20px;
  display: flex;
  justify-content: center;
  align-items: center;
}

.empty-card {
  text-align: center;
  padding: 48px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  max-width: 500px;
  box-shadow: var(--elevation-2);
}

.empty-icon {
  color: var(--success);
  margin-bottom: 20px;
  display: flex;
  justify-content: center;
  font-size: 48px;
}

.empty-card h2 {
  font-size: var(--text-xl);
  margin-bottom: 12px;
  color: var(--text-primary);
}

.empty-card p {
  color: var(--text-secondary);
  line-height: var(--leading-relaxed);
  margin-bottom: 8px;
}

.empty-card .muted {
  color: var(--text-muted);
  font-size: var(--text-sm);
}

/* ========== Footer ========== */
.footer {
  margin-top: 80px;
  text-align: center;
  color: var(--text-muted);
  font-size: var(--text-sm);
  border-top: 1px solid var(--border-subtle);
  padding-top: 32px;
}

/* ========== Toast Notifications ========== */
.toast-container {
  position: fixed;
  top: 80px;
  right: 20px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius);
  box-shadow: var(--elevation-3);
  min-width: 300px;
  transform: translateX(400px);
  opacity: 0;
  transition: all var(--transition-spring);
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
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
}

.toast-close:hover {
  background: var(--surface-2);
  color: var(--text-primary);
}

.toast-info { border-left: 3px solid var(--info); }
.toast-success { border-left: 3px solid var(--success); }
.toast-warning { border-left: 3px solid var(--warning); }
.toast-error { border-left: 3px solid var(--error); }

/* ========== Keyboard Shortcuts Hint ========== */
.kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 6px;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  box-shadow: 0 1px 0 var(--border-subtle);
}

/* ========== Accessibility ========== */
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
  outline: 2px solid var(--brand-purple);
  outline-offset: 2px;
}

/* ========== Scrollbar ========== */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-track {
  background: var(--surface-1);
}

::-webkit-scrollbar-thumb {
  background: var(--surface-3);
  border-radius: var(--radius);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--surface-4);
}

/* ========== Syntax Highlighting (Pygments Override) ========== */
${pyg_dark}
${pyg_light}

/* Custom syntax highlighting enhancements */
html[data-theme="dark"] .codebox .k,
html[data-theme="dark"] .codebox .kd,
html[data-theme="dark"] .codebox .kn { color: #C792EA; } /* Keywords */
html[data-theme="dark"] .codebox .s,
html[data-theme="dark"] .codebox .s1,
html[data-theme="dark"] .codebox .s2 { color: #C3E88D; } /* Strings */
html[data-theme="dark"] .codebox .nf { color: #82AAFF; } /* Functions */
html[data-theme="dark"] .codebox .nb { color: #FFCB6B; } /* Builtins */
html[data-theme="dark"] .codebox .c,
html[data-theme="dark"] .codebox .c1 { color: #546E7A; font-style: italic; } /* Comments */

</style>
</head>

<body>
<!-- Toast Container -->
<div class="toast-container"></div>

<!-- Topbar -->
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <h1>${title}</h1>
      <div class="sub">v${version}</div>
    </div>
    <div class="top-actions">
      <button class="btn" type="button" id="theme-toggle" title="Toggle theme (T)">
        ${icon_theme} Theme
      </button>
      <button class="btn primary" type="button" id="export-btn" title="Export report">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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
${empty_state_html}

${func_section}
${block_section}

<div class="footer">
  Generated by CodeClone v${version} • Press <kbd class="kbd">/</kbd> to search • <kbd class="kbd">T</kbd> to toggle theme
</div>
</div>

<script>
(() => {
  'use strict';
  
  // ========== Theme Management ==========
  const htmlEl = document.documentElement;
  const btnTheme = document.getElementById('theme-toggle');
  
  function initTheme() {
    const stored = localStorage.getItem('codeclone_theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const hour = new Date().getHours();
    const isNight = hour < 7 || hour > 19;
    
    const theme = stored || (prefersDark || isNight ? 'dark' : 'light');
    htmlEl.setAttribute('data-theme', theme);
  }
  
  function toggleTheme() {
    const cur = htmlEl.getAttribute('data-theme') || 'dark';
    const next = cur === 'dark' ? 'light' : 'dark';
    htmlEl.setAttribute('data-theme', next);
    localStorage.setItem('codeclone_theme', next);
    showToast(`Switched to $${next} theme`, 'info');
  }
  
  initTheme();
  btnTheme?.addEventListener('click', toggleTheme);
  
  // ========== Toast Notifications ==========
  function showToast(message, type = 'info') {
    const icons = {
      info: 'ℹ️',
      success: '✅',
      warning: '⚠️',
      error: '❌'
    };
    
    const toast = document.createElement('div');
    toast.className = `toast toast-$${type}`;
    toast.innerHTML = `
      <span class="toast-icon">$${icons[type]}</span>
      <span class="toast-message">$${message}</span>
      <button class="toast-close" aria-label="Close">×</button>
    `;
    
    const container = document.querySelector('.toast-container');
    container.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => toast.classList.add('toast-show'), 10);
    
    // Close button
    toast.querySelector('.toast-close').addEventListener('click', () => {
      toast.classList.remove('toast-show');
      setTimeout(() => toast.remove(), 300);
    });
    
    // Auto-remove
    setTimeout(() => {
      toast.classList.remove('toast-show');
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }
  
  // Make showToast global for use in other scripts
  window.showToast = showToast;
  
  // ========== Keyboard Shortcuts ==========
  document.addEventListener('keydown', (e) => {
    // / - Focus search
    if (e.key === '/' && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      const search = document.querySelector('.search');
      if (search) {
        search.focus();
        search.select();
      }
    }
    
    // T - Toggle theme
    if (e.key === 't' || e.key === 'T') {
      if (!e.target.matches('input, textarea')) {
        e.preventDefault();
        toggleTheme();
      }
    }
    
    // Escape - Clear search / close modals
    if (e.key === 'Escape') {
      const search = document.querySelector('.search');
      if (search && search.value) {
        search.value = '';
        search.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
  });
  
  // ========== Group Toggle ==========
  document.querySelectorAll('.group-head').forEach((head) => {
    head.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      const btn = head.querySelector('[data-toggle-group]');
      if (btn) btn.click();
    });
  });
  
  document.querySelectorAll('[data-toggle-group]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.getAttribute('data-toggle-group');
      const body = document.getElementById('group-body-' + id);
      if (!body) return;
      
      const isHidden = body.style.display === 'none';
      body.style.display = isHidden ? '' : 'none';
      btn.style.transform = isHidden ? 'rotate(0deg)' : 'rotate(-90deg)';
    });
  });
  
  // ========== Section Management ==========
  function initSection(sectionId) {
    const section = document.querySelector(`section[data-section='$${sectionId}']`);
    if (!section) return;
    
    const groups = Array.from(section.querySelectorAll(`.group[data-group='$${sectionId}']`));
    const searchInput = document.getElementById(`search-$${sectionId}`);
    const btnPrev = section.querySelector(`[data-prev='$${sectionId}']`);
    const btnNext = section.querySelector(`[data-next='$${sectionId}']`);
    const meta = section.querySelector(`[data-page-meta='$${sectionId}']`);
    const selPageSize = section.querySelector(`[data-pagesize='$${sectionId}']`);
    const btnClear = section.querySelector(`[data-clear='$${sectionId}']`);
    const btnCollapseAll = section.querySelector(`[data-collapse-all='$${sectionId}']`);
    const btnExpandAll = section.querySelector(`[data-expand-all='$${sectionId}']`);
    const pill = section.querySelector(`[data-count-pill='$${sectionId}']`);
    
    const state = {
      q: '',
      page: 1,
      pageSize: parseInt(selPageSize?.value || '10', 10),
      filtered: groups
    };
    
    function setGroupVisible(el, yes) {
      el.style.display = yes ? '' : 'none';
    }
    
    function render() {
      const total = state.filtered.length;
      const pageSize = Math.max(1, state.pageSize);
      const pages = Math.max(1, Math.ceil(total / pageSize));
      state.page = Math.min(Math.max(1, state.page), pages);
      
      const start = (state.page - 1) * pageSize;
      const end = Math.min(total, start + pageSize);
      
      groups.forEach(g => setGroupVisible(g, false));
      state.filtered.slice(start, end).forEach(g => setGroupVisible(g, true));
      
      if (meta) meta.textContent = `Page $${state.page} / $${pages} • $${total} groups`;
      if (pill) pill.textContent = `$${total} groups`;
      
      if (btnPrev) btnPrev.disabled = state.page <= 1;
      if (btnNext) btnNext.disabled = state.page >= pages;
    }
    
    function applyFilter() {
      const q = (state.q || '').trim().toLowerCase();
      if (!q) {
        state.filtered = groups;
      } else {
        state.filtered = groups.filter(g => {
          const blob = g.getAttribute('data-search') || '';
          return blob.indexOf(q) !== -1;
        });
      }
      state.page = 1;
      render();
    }
    
    searchInput?.addEventListener('input', (e) => {
      state.q = e.target.value || '';
      applyFilter();
    });
    
    btnClear?.addEventListener('click', () => {
      if (searchInput) searchInput.value = '';
      state.q = '';
      applyFilter();
    });
    
    selPageSize?.addEventListener('change', () => {
      state.pageSize = parseInt(selPageSize.value || '10', 10);
      state.page = 1;
      render();
    });
    
    btnPrev?.addEventListener('click', () => {
      state.page -= 1;
      render();
    });
    
    btnNext?.addEventListener('click', () => {
      state.page += 1;
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
  
  initSection('functions');
  initSection('blocks');
  
  // ========== Export Functionality ==========
  document.getElementById('export-btn')?.addEventListener('click', () => {
    showToast('Export functionality coming soon!', 'info');
  });
  
  // ========== Page Load Animation ==========
  document.querySelectorAll('.section').forEach((section, index) => {
    section.style.animationDelay = `$${index * 0.1}s`;
  });
  
  // Show welcome toast
  setTimeout(() => {
    const groupCount = document.querySelectorAll('.group').length;
    if (groupCount > 0) {
      showToast(`Found $${groupCount} clone groups`, 'success');
    }
  }, 500);
})();
</script>
</body>
</html>
""")

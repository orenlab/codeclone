# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CSS design system for the HTML report — tokens, components, layout."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

_TOKENS_DARK = """\
:root{
  --font-sans:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Oxygen,Ubuntu,sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;

  /* surface — slate scale */
  --bg-body:#0f1117;
  --bg-surface:#161822;
  --bg-raised:#1c1f2e;
  --bg-overlay:#232639;
  --bg-subtle:#2a2d42;

  /* border */
  --border:#2e3248;
  --border-strong:#3d4160;

  /* text */
  --text-primary:#e2e4ed;
  --text-secondary:#a0a3b8;
  --text-muted:#6b6f88;

  /* accent — indigo */
  --accent-primary:#6366f1;
  --accent-hover:#818cf8;
  --accent-muted:color-mix(in oklch,#6366f1 25%,transparent);

  /* semantic */
  --success:#34d399;
  --success-muted:color-mix(in oklch,#34d399 15%,transparent);
  --warning:#fbbf24;
  --warning-muted:color-mix(in oklch,#fbbf24 15%,transparent);
  --error:#f87171;
  --error-muted:color-mix(in oklch,#f87171 15%,transparent);
  --danger:#f87171;
  --info:#60a5fa;
  --info-muted:color-mix(in oklch,#60a5fa 15%,transparent);

  /* elevation */
  --shadow-sm:0 1px 2px rgba(0,0,0,.25);
  --shadow-md:0 2px 8px rgba(0,0,0,.3);
  --shadow-lg:0 4px 16px rgba(0,0,0,.35);
  --shadow-xl:0 8px 32px rgba(0,0,0,.4);

  /* radii */
  --radius-sm:4px;
  --radius-md:6px;
  --radius-lg:8px;
  --radius-xl:12px;

  /* spacing */
  --sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-5:20px;--sp-6:24px;--sp-8:32px;--sp-10:40px;

  /* transitions */
  --ease:cubic-bezier(.4,0,.2,1);
  --dur-fast:120ms;
  --dur-normal:200ms;
  --dur-slow:300ms;

  /* sizes */
  --topbar-h:72px;
  --container-max:1360px;

  color-scheme:dark;
}
"""

_TOKENS_LIGHT = """\
@media(prefers-color-scheme:light){
  :root:not([data-theme]){
    --bg-body:#f8f9fc;--bg-surface:#ffffff;--bg-raised:#f1f3f8;--bg-overlay:#e8eaf2;--bg-subtle:#dde0eb;
    --border:#d4d7e3;--border-strong:#b8bdd0;
    --text-primary:#1a1d2e;--text-secondary:#4b5068;--text-muted:#8589a0;
    --accent-primary:#4f46e5;--accent-hover:#6366f1;--accent-muted:color-mix(in oklch,#4f46e5 12%,transparent);
    --success:#059669;--success-muted:color-mix(in oklch,#059669 10%,transparent);
    --warning:#d97706;--warning-muted:color-mix(in oklch,#d97706 10%,transparent);
    --error:#dc2626;--error-muted:color-mix(in oklch,#dc2626 10%,transparent);
    --danger:#dc2626;--info:#2563eb;--info-muted:color-mix(in oklch,#2563eb 10%,transparent);
    --shadow-sm:0 1px 2px rgba(0,0,0,.06);--shadow-md:0 2px 8px rgba(0,0,0,.08);
    --shadow-lg:0 4px 16px rgba(0,0,0,.1);--shadow-xl:0 8px 32px rgba(0,0,0,.12);
    color-scheme:light;
  }
}
[data-theme="light"]{
  --bg-body:#f8f9fc;--bg-surface:#ffffff;--bg-raised:#f1f3f8;--bg-overlay:#e8eaf2;--bg-subtle:#dde0eb;
  --border:#d4d7e3;--border-strong:#b8bdd0;
  --text-primary:#1a1d2e;--text-secondary:#4b5068;--text-muted:#8589a0;
  --accent-primary:#4f46e5;--accent-hover:#6366f1;--accent-muted:color-mix(in oklch,#4f46e5 12%,transparent);
  --success:#059669;--success-muted:color-mix(in oklch,#059669 10%,transparent);
  --warning:#d97706;--warning-muted:color-mix(in oklch,#d97706 10%,transparent);
  --error:#dc2626;--error-muted:color-mix(in oklch,#dc2626 10%,transparent);
  --danger:#dc2626;--info:#2563eb;--info-muted:color-mix(in oklch,#2563eb 10%,transparent);
  --shadow-sm:0 1px 2px rgba(0,0,0,.06);--shadow-md:0 2px 8px rgba(0,0,0,.08);
  --shadow-lg:0 4px 16px rgba(0,0,0,.1);--shadow-xl:0 8px 32px rgba(0,0,0,.12);
  color-scheme:light;
}
"""

# ---------------------------------------------------------------------------
# Reset + base
# ---------------------------------------------------------------------------

_RESET = """\
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%;-webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;scroll-behavior:smooth;scrollbar-gutter:stable}
body{font-family:var(--font-sans);font-size:14px;line-height:1.6;color:var(--text-primary);
  background:var(--bg-body);overflow-x:hidden}
code,pre,kbd{font-family:var(--font-mono);font-size:13px}
a{color:var(--accent-primary);text-decoration:none}
a:hover{color:var(--accent-hover);text-decoration:underline}
h1,h2,h3,h4{font-weight:600;line-height:1.3;color:var(--text-primary)}
h1{font-size:1.5rem}h2{font-size:1.25rem}h3{font-size:1.1rem}
ul,ol{list-style:none}
button,input,select{font:inherit;color:inherit}
summary{cursor:pointer}
.muted{color:var(--text-muted);font-size:.85em}
"""

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

_LAYOUT = """\
.container{max-width:var(--container-max);margin:0 auto;padding:0 var(--sp-6)}

/* Topbar */
.topbar{position:sticky;top:0;z-index:100;background:var(--bg-surface);border-bottom:1px solid var(--border);
  box-shadow:var(--shadow-sm)}
.topbar-inner{display:flex;align-items:center;justify-content:space-between;
  height:72px;padding:0 var(--sp-6);max-width:var(--container-max);margin:0 auto}
.brand{display:flex;align-items:center;gap:var(--sp-3);min-width:0;flex:1}
.brand-logo{flex-shrink:0}
.brand-text{display:flex;flex-direction:column;gap:2px;min-width:0;flex:1}
.brand h1{display:flex;flex-wrap:wrap;align-items:baseline;gap:var(--sp-1);font-size:1.15rem;
  font-weight:700;color:var(--text-primary);line-height:1.3;min-width:0}
.brand-meta{font-size:.78rem;color:var(--text-muted);overflow-wrap:anywhere}
.brand-project{display:inline-flex;flex-wrap:wrap;align-items:baseline;gap:4px;
  font-weight:500;color:var(--text-secondary);min-width:0}
.brand-project-name{font-family:var(--font-mono);font-size:.85em;font-weight:500;padding:1px 5px;
  border-radius:var(--radius-sm);background:var(--bg-overlay);color:var(--accent-primary);
  max-width:100%;overflow-wrap:anywhere}
.topbar-actions{display:flex;align-items:center;gap:var(--sp-2);flex-shrink:0;flex-wrap:wrap}

/* Theme toggle */
.theme-toggle{display:inline-flex;align-items:center;gap:var(--sp-1);
  padding:var(--sp-1) var(--sp-3);background:none;border:1px solid var(--border);
  border-radius:var(--radius-md);cursor:pointer;color:var(--text-muted);font-size:.85rem;
  font-weight:500;font-family:inherit;transition:all var(--dur-fast) var(--ease)}
.theme-toggle:hover{color:var(--text-primary);background:var(--bg-raised);border-color:var(--border-strong)}
.theme-toggle svg{width:16px;height:16px}

/* Main tabs — full-width pill bar */
.main-tabs-wrap{position:sticky;top:var(--topbar-h);z-index:90;padding:var(--sp-3) 0 0;
  background:var(--bg-body)}
.main-tabs{display:flex;gap:var(--sp-1);padding:var(--sp-1);
  background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  overflow-x:auto;scrollbar-width:none;-webkit-overflow-scrolling:touch}
.main-tabs::-webkit-scrollbar{display:none}
.main-tab{position:relative;flex:1;text-align:center;padding:var(--sp-2) var(--sp-3);
  background:none;border:none;cursor:pointer;font-size:.85rem;font-weight:500;
  color:var(--text-muted);white-space:nowrap;border-radius:var(--radius-md);
  transition:all var(--dur-fast) var(--ease)}
.main-tab:hover{color:var(--text-primary);background:var(--bg-raised)}
.main-tab[aria-selected="true"]{color:var(--accent-primary);background:var(--accent-muted)}
.tab-count{display:inline-flex;align-items:center;justify-content:center;min-width:18px;
  height:18px;padding:0 5px;font-size:.7rem;font-weight:700;border-radius:9px;
  background:var(--bg-overlay);color:var(--text-muted);margin-left:var(--sp-1)}
.main-tab[aria-selected="true"] .tab-count{background:var(--accent-primary);
  color:#fff}

/* Tab panels */
.tab-panel{display:none;padding:var(--sp-6) 0;contain:layout style}
.tab-panel.active{display:block}
"""

# ---------------------------------------------------------------------------
# Components: buttons, inputs, selects
# ---------------------------------------------------------------------------

_CONTROLS = """\
/* Buttons */
.btn{display:inline-flex;align-items:center;gap:var(--sp-1);padding:var(--sp-1) var(--sp-3);
  font-size:.8rem;font-weight:500;border:1px solid var(--border);border-radius:var(--radius-md);
  background:var(--bg-raised);color:var(--text-secondary);cursor:pointer;white-space:nowrap;
  transition:all var(--dur-fast) var(--ease)}
.btn:hover{border-color:var(--border-strong);color:var(--text-primary);background:var(--bg-overlay)}
.btn-prov{position:relative}
.btn-prov .prov-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.btn-prov .prov-dot.dot-green{background:var(--success)}
.btn-prov .prov-dot.dot-amber{background:var(--warning)}
.btn-prov .prov-dot.dot-red{background:var(--error)}
.btn-prov .prov-dot.dot-neutral{background:var(--text-muted)}
.btn.ghost{background:none;border-color:transparent}
.btn.ghost:hover{background:var(--bg-raised);border-color:var(--border)}
.btn svg{width:14px;height:14px}

/* Inputs */
input[type="text"]{padding:var(--sp-1) var(--sp-3);font-size:.85rem;border:1px solid var(--border);
  border-radius:var(--radius-md);background:var(--bg-body);color:var(--text-primary);outline:none;
  transition:border-color var(--dur-fast) var(--ease)}
input[type="text"]:focus{border-color:var(--accent-primary);box-shadow:0 0 0 2px var(--accent-muted)}
input[type="text"]::placeholder{color:var(--text-muted)}

/* Selects */
.select{padding:var(--sp-1) var(--sp-3);padding-right:var(--sp-6);font-size:.8rem;
  border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-raised);
  color:var(--text-secondary);cursor:pointer;appearance:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='none' stroke='%236b6f88' stroke-width='2'%3E%3Cpath d='M3 4.5l3 3 3-3'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 8px center}
.select:focus{border-color:var(--accent-primary);outline:none}

/* Checkbox labels */
.inline-check{display:inline-flex;align-items:center;gap:var(--sp-1);font-size:.8rem;
  color:var(--text-muted);cursor:pointer;white-space:nowrap}
.inline-check input[type="checkbox"]{accent-color:var(--accent-primary);width:14px;height:14px}
"""

# ---------------------------------------------------------------------------
# Search box
# ---------------------------------------------------------------------------

_SEARCH = """\
.search-box{position:relative;display:flex;align-items:center}
.search-ico{position:absolute;left:var(--sp-2);color:var(--text-muted);pointer-events:none;
  display:flex;align-items:center}
.search-ico svg{width:14px;height:14px}
.search-box input[type="text"]{padding-left:28px;width:200px}
.clear-btn{position:absolute;right:var(--sp-1);background:none;border:none;cursor:pointer;
  color:var(--text-muted);padding:2px;display:flex;align-items:center;opacity:0;
  transition:opacity var(--dur-fast) var(--ease)}
.search-box input:not(:placeholder-shown)~.clear-btn{opacity:1}
.clear-btn:hover{color:var(--text-primary)}
.clear-btn svg{width:14px;height:14px}
"""

# ---------------------------------------------------------------------------
# Toolbar + pagination
# ---------------------------------------------------------------------------

_TOOLBAR = """\
.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:var(--sp-2);
  padding:var(--sp-3) var(--sp-4);background:var(--bg-raised);border:1px solid var(--border);
  border-radius:var(--radius-lg);margin-bottom:var(--sp-4)}
.toolbar-left{display:flex;flex-wrap:wrap;align-items:center;gap:var(--sp-2);flex:1}
.toolbar-right{display:flex;align-items:center;gap:var(--sp-2)}

.pagination{display:flex;align-items:center;gap:var(--sp-1)}
.page-meta{font-size:.8rem;color:var(--text-muted);white-space:nowrap;min-width:100px;text-align:center}

/* Suggestions toolbar */
.suggestions-toolbar{flex-direction:column;align-items:stretch}
.suggestions-toolbar-row{display:flex;flex-wrap:wrap;align-items:center;gap:var(--sp-2)}
.suggestions-toolbar-row--secondary{padding-top:var(--sp-2);border-top:1px solid var(--border)}
.suggestions-count-label{margin-left:auto;font-size:.8rem;color:var(--text-muted);font-weight:500}
"""

# ---------------------------------------------------------------------------
# Insight banners
# ---------------------------------------------------------------------------

_INSIGHT = """\
.insight-banner{padding:var(--sp-3) var(--sp-4);border-radius:var(--radius-md);
  margin-bottom:var(--sp-4);border-left:3px solid var(--border);background:none}
.insight-question{font-size:.72rem;font-weight:500;color:var(--text-muted);
  text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}
.insight-answer{font-size:.82rem;color:var(--text-muted);line-height:1.5}

.insight-ok{border-left-color:var(--success);background:var(--success-muted)}
.insight-warn{border-left-color:var(--warning);background:var(--warning-muted)}
.insight-risk{border-left-color:var(--error);background:var(--error-muted)}
.insight-info{border-left-color:var(--info);background:var(--info-muted)}
"""

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

_TABLES = """\
.table-wrap{display:block;inline-size:100%;max-inline-size:100%;min-inline-size:0;overflow-x:auto;
  overflow-y:hidden;border:1px solid var(--border);border-radius:var(--radius-lg);margin-bottom:var(--sp-4);
  background:
    linear-gradient(to right,var(--bg-surface) 30%,transparent) left center / 40px 100% no-repeat local,
    linear-gradient(to left,var(--bg-surface) 30%,transparent) right center / 40px 100% no-repeat local,
    linear-gradient(to right,rgba(0,0,0,.15),transparent) left center / 14px 100% no-repeat scroll,
    linear-gradient(to left,rgba(0,0,0,.15),transparent) right center / 14px 100% no-repeat scroll}
.table{inline-size:max-content;min-inline-size:100%;border-collapse:collapse;font-size:.82rem;
  font-family:var(--font-mono)}
.table th{position:sticky;top:0;z-index:2;padding:var(--sp-2) var(--sp-3);text-align:left;font-family:var(--font-sans);
  font-weight:600;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;
  color:var(--text-muted);background:var(--bg-overlay);border-bottom:1px solid var(--border);
  white-space:nowrap;cursor:default;user-select:none}
.table th[data-sortable]{cursor:pointer}
.table th[data-sortable]:hover{color:var(--text-primary)}
.table th .sort-icon{display:inline-flex;margin-left:var(--sp-1);opacity:.4}
.table th[aria-sort] .sort-icon{opacity:1;color:var(--accent-primary)}
.table td{padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border);color:var(--text-secondary);
  vertical-align:top}
.table tr:last-child td{border-bottom:none}
.table tr:hover td{background:var(--bg-raised)}
.table .col-name{font-weight:500;color:var(--text-primary)}
.table .col-file,.table .col-path{color:var(--text-muted);max-width:240px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.table .col-number,.table .col-num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.table .col-risk,.table .col-badge,.table .col-cat{white-space:nowrap}
.table .col-steps{max-width:120px;word-break:break-word}
.table .col-wide{max-width:320px;word-break:break-all}
.table-empty{padding:var(--sp-8);text-align:center;color:var(--text-muted);font-size:.9rem}
"""

# ---------------------------------------------------------------------------
# Sub-tabs (clone-nav / split-tabs)
# ---------------------------------------------------------------------------

_SUB_TABS = """\
.clone-nav{display:flex;gap:2px;border-bottom:1px solid var(--border);margin-bottom:var(--sp-4);
  overflow-x:auto;scrollbar-width:none}
.clone-nav::-webkit-scrollbar{display:none}
.clone-nav-btn{position:relative;padding:var(--sp-2) var(--sp-4);background:none;border:none;
  cursor:pointer;font-size:.85rem;font-weight:500;color:var(--text-muted);white-space:nowrap;
  transition:color var(--dur-fast) var(--ease)}
.clone-nav-btn:hover{color:var(--text-primary)}
.clone-nav-btn.active{color:var(--accent-primary)}
.clone-nav-btn.active::after{content:"";position:absolute;bottom:-1px;left:0;right:0;
  height:2px;background:var(--accent-primary);border-radius:1px 1px 0 0}
.clone-panel{display:none}
.clone-panel.active{display:block}
"""

# ---------------------------------------------------------------------------
# Sections + groups
# ---------------------------------------------------------------------------

_SECTIONS = """\
.section{margin-bottom:var(--sp-6)}
.subsection-title{font-size:1rem;font-weight:600;color:var(--text-primary);
  margin-bottom:var(--sp-3);padding-bottom:var(--sp-2);border-bottom:1px solid var(--border)}
.section-body{display:flex;flex-direction:column;gap:var(--sp-3)}

/* Clone groups */
.group{border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--bg-surface);
  overflow:hidden;transition:box-shadow var(--dur-fast) var(--ease)}
.group:hover{box-shadow:var(--shadow-sm)}
.group-head{display:flex;align-items:center;justify-content:space-between;padding:var(--sp-3) var(--sp-4);
  gap:var(--sp-3);cursor:pointer}
.group-head-left{display:flex;align-items:center;gap:var(--sp-3);min-width:0;flex:1}
.group-head-right{display:flex;align-items:center;gap:var(--sp-2);flex-shrink:0}
.group-toggle{background:none;border:none;cursor:pointer;color:var(--text-muted);padding:var(--sp-1);
  display:flex;align-items:center;transition:transform var(--dur-normal) var(--ease);flex-shrink:0}
.group-toggle svg{width:16px;height:16px}
.group-toggle.expanded{transform:rotate(180deg)}
.group-info{min-width:0;flex:1}
.group-name{font-weight:600;font-size:.9rem;color:var(--text-primary);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;font-family:var(--font-mono)}
.group-summary{font-size:.8rem;color:var(--text-muted)}

/* Badges */
.clone-type-badge{font-size:.75rem;font-weight:500;padding:1px var(--sp-2);
  border-radius:var(--radius-sm);background:var(--accent-muted);color:var(--accent-primary)}
.clone-count-badge{font-size:.75rem;font-weight:600;padding:1px var(--sp-2);
  border-radius:var(--radius-sm);background:var(--bg-overlay);color:var(--text-secondary)}

/* Group body */
.group-body{border-top:1px solid var(--border);display:none}
.group-body.expanded{display:block}
.group-body.items.expanded{display:grid}
.group-compare-note{padding:var(--sp-2) var(--sp-4);font-size:.8rem;color:var(--text-muted);
  background:var(--bg-raised);border-bottom:1px solid var(--border);font-style:italic}

/* Group explain */
.group-explain{padding:var(--sp-2) var(--sp-4);display:flex;flex-wrap:wrap;gap:var(--sp-1);
  background:var(--bg-raised);border-bottom:1px solid var(--border)}
.group-explain-item{font-size:.75rem;padding:1px var(--sp-2);border-radius:var(--radius-sm);
  background:var(--bg-overlay);color:var(--text-muted);font-family:var(--font-mono);white-space:nowrap}
.group-explain-warn{color:var(--warning);background:var(--warning-muted)}
.group-explain-muted{opacity:.7}
.group-explain-note{font-size:.75rem;color:var(--text-muted);font-style:italic;width:100%;
  padding-top:var(--sp-1)}
"""

# ---------------------------------------------------------------------------
# Items (clone instances)
# ---------------------------------------------------------------------------

_ITEMS = """\
.items{grid-template-columns:repeat(2,1fr);gap:0}
.items .item{border-right:1px solid var(--border);border-bottom:1px solid var(--border)}
.items .item:nth-child(2n){border-right:none}
.items .item:nth-last-child(-n+2){border-bottom:none}
.items .item:last-child{border-bottom:none}
.item{padding:0;min-width:0;overflow:hidden}
.item-header{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-2) var(--sp-3);background:var(--bg-raised);gap:var(--sp-2)}
.item-title{font-weight:500;font-size:.8rem;color:var(--text-primary);font-family:var(--font-mono);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1}
.item-loc{font-size:.72rem;color:var(--text-muted);font-family:var(--font-mono);white-space:nowrap;flex-shrink:0}
.item-compare-meta{padding:var(--sp-1) var(--sp-3);font-size:.72rem;color:var(--text-muted);
  background:var(--bg-body);border-bottom:1px solid var(--border)}
"""

# ---------------------------------------------------------------------------
# Code blocks
# ---------------------------------------------------------------------------

_CODE = """\
/* _html_snippets renders .codebox>.hitline/.line */
.codebox{overflow-x:auto;font-size:12px;line-height:1.7;background:var(--bg-body);padding:var(--sp-2) 0;margin:0}
.codebox pre{margin:0;padding:0}
.codebox .line,.codebox .hitline{padding:0 var(--sp-4) 0 var(--sp-2);white-space:pre;display:block}
.codebox .line:hover{background:var(--bg-raised)}
.codebox .hitline{background:color-mix(in oklch,var(--accent-primary) 12%,transparent);
  border-left:3px solid var(--accent-primary);padding-left:calc(var(--sp-2) - 3px)}
.codebox .hitline:hover{background:color-mix(in oklch,var(--accent-primary) 20%,transparent)}
"""

# ---------------------------------------------------------------------------
# Risk / severity / source-kind badges
# ---------------------------------------------------------------------------

_BADGES = """\
.risk-badge,.severity-badge{display:inline-flex;align-items:center;font-size:.72rem;font-weight:600;
  padding:1px var(--sp-2);border-radius:var(--radius-sm);text-transform:uppercase;letter-spacing:.02em}
.risk-critical,.severity-critical{background:var(--error-muted);color:var(--error)}
.risk-high,.severity-high{background:var(--error-muted);color:var(--error)}
.risk-warning,.severity-warning{background:var(--warning-muted);color:var(--warning)}
.risk-medium,.severity-medium{background:var(--warning-muted);color:var(--warning)}
.risk-low,.severity-low{background:var(--success-muted);color:var(--success)}
.risk-info,.severity-info{background:var(--info-muted);color:var(--info)}

.source-kind-badge{display:inline-flex;align-items:center;font-size:.72rem;font-weight:500;
  padding:1px var(--sp-2);border-radius:var(--radius-sm);background:var(--bg-overlay);color:var(--text-muted)}
.source-kind-production{background:var(--error-muted);color:var(--error)}
.source-kind-test,.source-kind-test_util{background:var(--info-muted);color:var(--info)}
.source-kind-fixture,.source-kind-conftest{background:var(--warning-muted);color:var(--warning)}
.source-kind-import,.source-kind-cross_kind{background:var(--accent-muted);color:var(--accent-primary)}
.category-badge{display:inline-flex;align-items:center;gap:3px;font-size:.7rem;
  font-family:var(--font-mono);padding:1px var(--sp-2);border-radius:var(--radius-sm);
  background:var(--bg-overlay);color:var(--text-muted);white-space:nowrap}
.category-badge-key{font-weight:400;color:var(--text-muted)}
.category-badge-val{font-weight:600;color:var(--text-secondary)}
.finding-why-chips{display:flex;flex-wrap:wrap;gap:var(--sp-1);margin:var(--sp-1) 0}
.finding-why-chips .category-badge{font-size:.72rem}
"""

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

_OVERVIEW = """\
/* Dashboard */
/* KPI grid: health card on the left, KPI cards in two rows on the right */
.overview-kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:var(--sp-3);margin-bottom:var(--sp-6)}
.overview-kpi-grid--with-health{grid-template-columns:minmax(190px,210px) minmax(0,1fr);
  gap:var(--sp-3);align-items:stretch}
.overview-kpi-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:var(--sp-3);min-width:0}
.overview-kpi-grid--with-health .meta-item{min-width:0}
.overview-kpi-grid--with-health .meta-item{min-height:108px}
.overview-kpi-cards .meta-item{display:grid;grid-template-rows:auto 1fr auto;
  align-items:start;padding:var(--sp-3) var(--sp-4);gap:var(--sp-2);min-height:122px}
.overview-kpi-cards .meta-item .meta-label{font-size:.72rem;min-height:18px}
.overview-kpi-cards .meta-item .meta-value{display:flex;align-items:center;
  font-size:1.55rem;line-height:1;padding:var(--sp-1) 0}
.overview-kpi-cards .kpi-detail{margin-top:0;gap:4px;align-self:end}
.overview-kpi-cards .kpi-micro{padding:2px 6px;font-size:.65rem}
.overview-kpi-grid--with-health .overview-health-card{padding:var(--sp-2)}
.overview-kpi-grid--with-health .overview-health-inner{width:100%;height:100%}
.overview-kpi-grid--with-health .health-ring{width:140px;height:140px;margin:auto}
.overview-kpi-grid--with-health .overview-health-card .meta-value{font-size:1.2rem}
.overview-kpi-grid--with-health .overview-health-card .meta-label{font-size:.66rem}
@media(max-width:1380px){
  .overview-kpi-cards{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media(max-width:980px){
  .overview-kpi-grid--with-health{grid-template-columns:1fr}
  .overview-kpi-cards{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:520px){
  .overview-kpi-cards{grid-template-columns:1fr}
  .overview-kpi-cards .meta-item{grid-template-rows:auto auto auto;align-content:start;
    min-height:0}
  .overview-kpi-cards .meta-item .meta-label{min-height:0}
  .overview-kpi-cards .meta-item .meta-value{padding-top:0}
  .overview-kpi-cards .kpi-detail{align-self:start}
  .overview-kpi-cards .kpi-micro{max-width:100%;white-space:normal;overflow-wrap:anywhere}
}

/* Health gauge */
.overview-health-card{display:flex;align-items:center;justify-content:center;
  padding:var(--sp-3);background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-lg)}
.overview-health-inner{display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:var(--sp-1)}
.health-ring{position:relative;width:140px;height:140px}
.health-ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.health-ring-bg{fill:none;stroke:var(--border);stroke-width:6}
.health-ring-baseline{fill:none;stroke-width:6;stroke-linecap:round}
.health-ring-fg{fill:none;stroke-width:6;stroke-linecap:round;
  transition:stroke-dashoffset 1s var(--ease)}
.health-ring-label{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center}
.health-ring-score{font-size:1.75rem;font-weight:700;color:var(--text-primary);
  font-variant-numeric:tabular-nums;line-height:1}
.health-ring-grade{font-size:.72rem;font-weight:500;color:var(--text-muted);margin-top:3px}
.health-ring-delta{font-size:.65rem;font-weight:600;margin-top:3px}
.health-ring-delta--up{color:var(--success)}
.health-ring-delta--down{color:var(--error)}

/* Get Badge button (under health ring) */
.badge-btn{display:inline-flex;align-items:center;gap:4px;margin-top:var(--sp-2);
  padding:4px 10px;font-size:.65rem;font-weight:500;color:var(--text-muted);
  background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-sm);
  cursor:pointer;transition:all var(--dur-fast) var(--ease);white-space:nowrap}
.badge-btn:hover{color:var(--text-primary);border-color:var(--border-strong);
  background:var(--bg-alt)}

/* Badge modal */
.badge-modal{max-width:680px;width:92vw;max-height:85vh}
.badge-modal .modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--border)}
.badge-modal .modal-head h2{font-size:1rem;font-weight:700;margin:0}
.badge-modal .modal-body{padding:var(--sp-3) var(--sp-4) var(--sp-4);overflow-y:auto;flex:1 1 auto}

/* Badge tabs */
.badge-tabs{display:flex;gap:var(--sp-1);margin-bottom:var(--sp-3)}
.badge-tab{padding:5px 12px;font-size:.72rem;font-weight:500;color:var(--text-muted);
  background:transparent;border:1px solid var(--border);border-radius:var(--radius-sm);
  cursor:pointer;transition:all var(--dur-fast) var(--ease)}
.badge-tab:hover{color:var(--text-primary);border-color:var(--border-strong)}
.badge-tab--active{color:var(--text-primary);background:var(--bg-alt);
  border-color:var(--border-strong);font-weight:600}

/* Badge preview & disclaimer */
.badge-preview{text-align:center;padding:var(--sp-3) 0;margin-bottom:var(--sp-1);
  border-bottom:1px solid var(--border)}
.badge-preview img{height:24px}
.badge-disclaimer{font-size:.65rem;color:var(--text-muted);text-align:center;
  margin:var(--sp-1) 0 var(--sp-2);line-height:1.4}

/* Badge embed fields */
.badge-field-label{display:block;font-size:.68rem;font-weight:600;color:var(--text-muted);
  margin-bottom:var(--sp-1);margin-top:var(--sp-3);text-transform:uppercase;letter-spacing:.04em}
.badge-code-wrap{display:flex;align-items:stretch;border:1px solid var(--border);
  border-radius:var(--radius-sm);overflow:hidden;background:var(--bg-alt)}
.badge-code{flex:1;padding:var(--sp-2) var(--sp-3);font-size:.72rem;font-family:var(--font-mono);
  color:var(--text-primary);word-break:break-all;white-space:pre-wrap;line-height:1.5;
  user-select:all;-webkit-user-select:all}
.badge-copy-btn{min-width:64px;padding:var(--sp-2) var(--sp-3);font-size:.68rem;font-weight:500;
  color:var(--text-muted);background:transparent;border:none;border-left:1px solid var(--border);
  cursor:pointer;transition:all var(--dur-fast) var(--ease);white-space:nowrap}
.badge-copy-btn:hover{color:var(--text-primary)}
.badge-copy-btn--ok{color:var(--success)}

/* KPI stat card */
.meta-item{padding:var(--sp-2) var(--sp-3);background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-md);display:flex;flex-direction:column;gap:2px;
  transition:border-color var(--dur-fast) var(--ease);min-width:0}
.meta-item:hover{border-color:var(--border-strong)}
.meta-item .meta-label{font-size:.68rem;font-weight:500;color:var(--text-muted);
  display:flex;align-items:center;gap:var(--sp-1)}
.meta-item .meta-value{font-size:1.35rem;font-weight:700;color:var(--text-primary);
  font-variant-numeric:tabular-nums;line-height:1.2}
.meta-item .meta-value--good{color:var(--success)}
.meta-item .meta-value--bad{color:var(--error)}
.meta-item .meta-value--warn{color:var(--warning)}
.meta-item .meta-value--muted{color:var(--text-muted)}
.kpi-detail{display:flex;flex-wrap:wrap;gap:3px;margin-top:2px}
.kpi-micro{display:inline-flex;align-items:center;gap:2px;font-size:.62rem;
  padding:1px 5px;border-radius:var(--radius-sm);background:var(--bg-raised);
  white-space:nowrap;line-height:1.3}
.kpi-micro-val{font-weight:500;font-variant-numeric:tabular-nums;color:var(--text-muted)}
.kpi-micro-lbl{font-weight:400;color:var(--text-muted);text-transform:lowercase}
.kpi-micro--baselined{color:var(--success);font-weight:500;font-size:.6rem}
.kpi-delta{font-size:.58rem;font-weight:700;margin-left:auto;
  padding:1px 5px;border-radius:8px;white-space:nowrap}
.kpi-delta--good{color:var(--success);background:var(--success-muted)}
.kpi-delta--bad{color:var(--error);background:var(--error-muted)}
.kpi-delta--neutral{color:var(--text-muted);background:var(--bg-raised)}
.kpi-help{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;
  font-size:.6rem;font-weight:600;border-radius:50%;background:none;
  color:var(--text-muted);cursor:help;position:relative;border:1.5px solid var(--border);
  opacity:.5;transition:opacity var(--dur-fast) var(--ease)}
.kpi-help:hover{opacity:1}
.kpi-help:hover::after{content:attr(data-tip);position:absolute;top:calc(100% + 6px);left:50%;
  transform:translateX(-50%);background:var(--bg-overlay);color:var(--text-primary);
  padding:var(--sp-2) var(--sp-3);border-radius:var(--radius-md);font-size:.75rem;font-weight:400;
  white-space:normal;width:max-content;max-width:240px;line-height:1.4;
  box-shadow:var(--shadow-md);z-index:100;pointer-events:none;
  border:1px solid var(--border)}

/* Tone variants */
.meta-item.tone-ok{border-left:3px solid var(--success)}
.meta-item.tone-warn{border-left:3px solid var(--warning)}
.meta-item.tone-risk{border-left:3px solid var(--error)}

/* Clusters */
.overview-cluster{margin-bottom:var(--sp-4)}
.overview-cluster-header{margin-bottom:var(--sp-2)}
.overview-cluster-copy{font-size:.82rem;color:var(--text-muted);margin-top:2px}
.overview-cluster-empty{display:flex;flex-direction:column;align-items:center;gap:var(--sp-2);
  padding:var(--sp-5);text-align:center;color:var(--text-muted);font-size:.85rem}
.empty-icon{color:var(--success);opacity:.35;width:32px;height:32px;flex-shrink:0}
.overview-list{display:grid;grid-template-columns:repeat(2,1fr);gap:var(--sp-2)}

/* Overview rows */
.overview-row{display:flex;flex-direction:column;gap:var(--sp-1);
  padding:var(--sp-3) var(--sp-4);background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);transition:border-color var(--dur-fast) var(--ease)}
.overview-row:hover{border-color:var(--border-strong)}
.overview-row[data-severity="critical"]{border-left:3px solid var(--error)}
.overview-row[data-severity="warning"]{border-left:3px solid var(--warning)}
.overview-row[data-severity="info"]{border-left:3px solid var(--info)}
.overview-row-head{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
.overview-row-spread{font-size:.72rem;font-family:var(--font-mono);color:var(--text-muted);
  margin-left:auto;white-space:nowrap}
.overview-row-title{font-weight:600;font-size:.85rem;color:var(--text-primary)}
.overview-row-summary{font-size:.8rem;color:var(--text-secondary);line-height:1.5}

/* Summary grid */
.overview-summary-grid{display:grid;gap:var(--sp-3);margin-bottom:var(--sp-3)}
.overview-summary-grid--2col{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.overview-summary-item{background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);padding:var(--sp-4)}
.overview-summary-label{display:flex;align-items:center;gap:var(--sp-2);
  font-size:.72rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.06em;color:var(--text-muted);margin-bottom:var(--sp-3);
  padding-bottom:var(--sp-2);border-bottom:1px solid var(--border)}
.summary-icon{flex-shrink:0;opacity:.6}
.summary-icon--risk{color:var(--warning)}
.summary-icon--info{color:var(--accent-primary)}
.overview-summary-list{display:flex;flex-direction:column;gap:var(--sp-2)}
.overview-summary-list li{font-size:.82rem;color:var(--text-secondary);
  padding-left:var(--sp-3);position:relative;line-height:1.5}
.overview-summary-list li::before{content:"\\2022";position:absolute;left:0;color:var(--text-muted)}
.overview-summary-value{font-size:.85rem;color:var(--text-muted)}
/* Source breakdown bars */
.breakdown-list{display:flex;flex-direction:column;gap:var(--sp-2)}
.breakdown-row{display:grid;grid-template-columns:6.5rem 2rem 1fr;align-items:center;gap:var(--sp-2)}
.breakdown-row .source-kind-badge{justify-content:center;min-width:0;width:100%;text-align:center}
.breakdown-count{font-size:.8rem;font-weight:600;font-variant-numeric:tabular-nums;
  color:var(--text-primary);text-align:right}
.breakdown-bar-track{height:6px;border-radius:3px;background:var(--bg-raised);overflow:hidden}
.breakdown-bar-fill{display:block;height:100%;border-radius:3px;
  background:var(--accent-primary);transition:width .6s var(--ease)}
/* Health radar chart */
.health-radar{display:flex;justify-content:center;padding:var(--sp-3) 0}
.health-radar svg{width:100%;max-width:520px;height:auto;overflow:visible}
.health-radar text{font-size:9px;font-family:var(--font-sans);fill:var(--text-muted)}
.health-radar .radar-score{font-weight:600;font-variant-numeric:tabular-nums;fill:var(--text-secondary)}
.health-radar .radar-label--weak{fill:var(--error)}
.health-radar .radar-label--weak .radar-score{fill:var(--error)}
/* Findings by family bars */
.families-list{display:flex;flex-direction:column;gap:var(--sp-2)}
.families-row{display:grid;grid-template-columns:5.5rem 2rem 1fr auto;align-items:center;gap:var(--sp-2)}
.families-row--muted{opacity:.55}
.families-label{font-size:.75rem;font-weight:500;color:var(--text-secondary);text-align:right}
.families-count{font-size:.8rem;font-weight:600;font-variant-numeric:tabular-nums;
  color:var(--text-primary);text-align:right}
.breakdown-bar-track{display:flex}
.breakdown-bar-fill--baselined{opacity:.35}
.breakdown-bar-fill--new{border-radius:0 3px 3px 0}
.families-delta{font-size:.65rem;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.families-delta--ok{color:var(--success)}
.families-delta--new{color:var(--error)}
"""

# ---------------------------------------------------------------------------
# Dependencies (SVG graph)
# ---------------------------------------------------------------------------

_DEPENDENCIES = """\
.dep-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:var(--sp-2);margin-bottom:var(--sp-4)}
.dep-stats .meta-item{display:grid;grid-template-rows:auto 1fr auto;min-height:100px}
.dep-stats .meta-item .meta-label{font-size:.72rem;min-height:18px}
.dep-stats .meta-item .meta-value{display:flex;align-items:center}
.dep-stats .kpi-detail{margin-top:0;align-self:end}
.dep-graph-wrap{overflow:hidden;margin-bottom:var(--sp-4);border:1px solid var(--border);
  border-radius:var(--radius-lg);background:var(--bg-surface);padding:var(--sp-4)}
.dep-graph-svg{width:100%;height:auto;max-height:520px}
.dep-graph-svg text{fill:var(--text-secondary);font-family:var(--font-mono)}
.dep-node{transition:fill-opacity var(--dur-fast) var(--ease)}
.dep-edge{transition:stroke-opacity var(--dur-fast) var(--ease)}
.dep-label{transition:fill var(--dur-fast) var(--ease)}

/* Hub bar */
.dep-hub-bar{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;
  margin-bottom:var(--sp-4);padding:var(--sp-2) var(--sp-4);background:var(--bg-raised);
  border-radius:var(--radius-lg);border:1px solid var(--border)}
.dep-hub-label{font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
  color:var(--text-muted)}
.dep-hub-pill{display:inline-flex;align-items:center;gap:var(--sp-1);padding:var(--sp-1) var(--sp-2);
  border-radius:var(--radius-sm);background:var(--bg-overlay);font-size:.8rem}
.dep-hub-name{color:var(--text-primary);font-family:var(--font-mono);font-size:.8rem}
.dep-hub-deg{font-size:.72rem;font-weight:600;color:var(--accent-primary);
  background:var(--accent-muted);padding:0 var(--sp-1);border-radius:var(--radius-sm)}

/* Legend */
.dep-legend{display:flex;gap:var(--sp-4);align-items:center;margin-bottom:var(--sp-4);
  padding:var(--sp-2) var(--sp-4);font-size:.8rem;color:var(--text-muted)}
.dep-legend-item{display:inline-flex;align-items:center;gap:var(--sp-1)}
.dep-legend-item svg{flex-shrink:0}

/* Chain flow */
.chain-flow{display:inline-flex;align-items:center;gap:var(--sp-1);flex-wrap:wrap}
.chain-node{font-family:var(--font-mono);font-size:.8rem;color:var(--text-primary);
  padding:0 var(--sp-1);background:var(--bg-overlay);border-radius:var(--radius-sm)}
.chain-arrow{color:var(--text-muted);font-size:.75rem}
"""

# ---------------------------------------------------------------------------
# Novelty controls
# ---------------------------------------------------------------------------

_NOVELTY = """\
.global-novelty{margin-bottom:var(--sp-4);padding:var(--sp-4) var(--sp-5);
  background:var(--bg-raised);border:1px solid var(--border);border-radius:var(--radius-lg)}
.global-novelty-head{display:flex;align-items:center;gap:var(--sp-4);flex-wrap:wrap}
.global-novelty-head h2{font-size:1rem;white-space:nowrap}
.novelty-tabs{display:flex;gap:var(--sp-2)}
.novelty-tab{transition:all var(--dur-fast) var(--ease)}
.novelty-tab.active{background:var(--accent-primary);color:white;border-color:var(--accent-primary)}
.novelty-tab[data-novelty-state="good"]{color:var(--success);border-color:var(--success);background:var(--success-muted)}
.novelty-tab[data-novelty-state="good"].active{background:var(--success);color:white;border-color:var(--success)}
.novelty-tab[data-novelty-state="bad"]{color:var(--error);border-color:var(--error);background:var(--error-muted)}
.novelty-tab[data-novelty-state="bad"].active{background:var(--error);color:white;border-color:var(--error)}
.novelty-count{font-size:.72rem;font-weight:600;background:rgba(255,255,255,.15);padding:0 var(--sp-1);
  border-radius:var(--radius-sm);margin-left:var(--sp-1)}
.novelty-note{font-size:.8rem;color:var(--text-muted);margin-top:var(--sp-2)}

/* Hidden by novelty filter */
.group[data-novelty-hidden="true"]{display:none}
"""

# ---------------------------------------------------------------------------
# Dead-code
# ---------------------------------------------------------------------------

_DEAD_CODE = """\
/* No custom overrides — uses shared table + tabs */
"""

# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

_SUGGESTIONS = """\
/* List layout */
.suggestions-list{display:flex;flex-direction:column;gap:var(--sp-2)}

/* Card — full-width row */
.suggestion-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  overflow:hidden;transition:border-color var(--dur-fast) var(--ease),box-shadow var(--dur-fast) var(--ease)}
.suggestion-card:hover{border-color:var(--border-strong);box-shadow:var(--shadow-sm)}
.suggestion-card[data-severity="critical"]{border-left:3px solid var(--error)}
.suggestion-card[data-severity="warning"]{border-left:3px solid var(--warning)}
.suggestion-card[data-severity="info"]{border-left:3px solid var(--info)}

/* Header row: severity pill · title · meta badges */
.suggestion-head{padding:var(--sp-3) var(--sp-4);display:flex;align-items:center;
  gap:var(--sp-2);flex-wrap:wrap}
.suggestion-sev{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
  padding:2px var(--sp-2);border-radius:var(--radius-sm);white-space:nowrap}
.suggestion-sev--critical{background:var(--error-muted);color:var(--error)}
.suggestion-sev--warning{background:var(--warning-muted);color:var(--warning)}
.suggestion-sev--info{background:var(--info-muted);color:var(--info)}
.suggestion-sev-inline{font-size:.72rem;font-weight:600;padding:1px var(--sp-1);
  border-radius:var(--radius-sm)}
.suggestion-title{font-weight:600;font-size:.85rem;color:var(--text-primary);flex:1;min-width:0}
.suggestion-meta{display:flex;align-items:center;gap:var(--sp-1);flex-shrink:0;flex-wrap:wrap}
.suggestion-meta-badge{font-size:.68rem;font-family:var(--font-mono);font-weight:500;
  padding:1px var(--sp-2);border-radius:var(--radius-sm);background:var(--bg-overlay);
  color:var(--text-muted);white-space:nowrap}
.suggestion-effort--easy{color:var(--success);background:var(--success-muted, rgba(34,197,94,.1))}
.suggestion-effort--moderate{color:var(--warning);background:var(--warning-muted)}
.suggestion-effort--hard{color:var(--error);background:var(--error-muted)}

/* Body — context + summary */
.suggestion-body{padding:0 var(--sp-4) var(--sp-3);display:flex;flex-direction:column;gap:var(--sp-1)}
.suggestion-context{display:flex;gap:var(--sp-1);flex-wrap:wrap}
.suggestion-chip{font-size:.65rem;font-weight:500;padding:1px 6px;border-radius:var(--radius-sm);
  background:var(--bg-overlay);color:var(--text-muted);white-space:nowrap}
.suggestion-summary{font-size:.8rem;font-family:var(--font-mono);color:var(--text-secondary);line-height:1.5}
.suggestion-action{display:flex;align-items:center;gap:var(--sp-1);
  font-size:.8rem;font-weight:500;color:var(--accent-primary);margin-top:var(--sp-1)}
.suggestion-action-icon{flex-shrink:0;color:var(--accent-primary)}

/* Expandable details */
.suggestion-details{border-top:1px solid var(--border)}
.suggestion-details summary{padding:var(--sp-2) var(--sp-4);font-size:.75rem;font-weight:500;
  color:var(--text-muted);cursor:pointer;display:flex;align-items:center;gap:var(--sp-2);
  background:none;user-select:none}
.suggestion-details summary:hover{color:var(--text-primary);background:var(--bg-raised)}
.suggestion-details[open] summary{border-bottom:1px solid var(--border)}
.suggestion-details-body{padding:var(--sp-3) var(--sp-4);display:flex;flex-direction:column;gap:var(--sp-3)}

/* Facts grid inside details */
.suggestion-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:var(--sp-3)}
.suggestion-fact-group{display:flex;flex-direction:column;gap:var(--sp-1)}
.suggestion-fact-group-title{font-size:.68rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;color:var(--text-muted);padding-bottom:var(--sp-1);border-bottom:1px solid var(--border)}
.suggestion-dl{display:flex;flex-direction:column;gap:2px}
.suggestion-dl div{display:flex;gap:var(--sp-2);align-items:baseline}
.suggestion-dl dt{font-size:.72rem;color:var(--text-muted);white-space:nowrap;min-width:60px}
.suggestion-dl dd{font-size:.78rem;font-family:var(--font-mono);color:var(--text-primary);word-break:break-word}

/* Locations & steps inside details */
.suggestion-locations{display:flex;flex-direction:column;gap:var(--sp-1)}
.suggestion-locations li{display:flex;gap:var(--sp-2);align-items:baseline;
  padding:2px 0;border-bottom:1px solid var(--border);line-height:1.4}
.suggestion-locations li:last-child{border-bottom:none}
.suggestion-loc-path{font-family:var(--font-mono);font-size:.75rem;color:var(--text-secondary)}
.suggestion-loc-lines{color:var(--text-muted)}
.suggestion-loc-name{font-family:var(--font-mono);font-size:.72rem;color:var(--text-muted);
  margin-left:auto}
.suggestion-steps{padding-left:var(--sp-4);display:flex;flex-direction:column;gap:var(--sp-1);list-style:decimal}
.suggestion-steps li{font-size:.78rem;color:var(--text-secondary)}
.suggestion-sub-title{font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
  color:var(--text-muted);margin-bottom:var(--sp-1)}

.suggestion-empty{padding:var(--sp-4);text-align:center;color:var(--text-muted);font-size:.85rem}

/* Hidden cards */
.suggestion-card[data-filter-hidden="true"]{display:none}
"""

# ---------------------------------------------------------------------------
# Structural findings
# ---------------------------------------------------------------------------

_STRUCTURAL = """\
/* Structural findings — list layout */
.sf-list{display:flex;flex-direction:column;gap:var(--sp-2)}
.sf-card{background:var(--bg-surface);border:1px solid var(--border);border-left:3px solid var(--info);
  border-radius:var(--radius-lg);
  overflow:hidden;transition:border-color var(--dur-fast) var(--ease),box-shadow var(--dur-fast) var(--ease)}
.sf-card:hover{border-color:var(--border-strong);box-shadow:var(--shadow-sm)}

/* Header row */
.sf-head{padding:var(--sp-3) var(--sp-4);display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
.sf-kind-badge{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
  padding:2px var(--sp-2);border-radius:var(--radius-sm);white-space:nowrap;
  background:var(--info-muted);color:var(--info)}
.sf-title{font-weight:600;font-size:.85rem;color:var(--text-primary);flex:1;min-width:0}
.sf-meta{display:flex;align-items:center;gap:var(--sp-1);flex-shrink:0;flex-wrap:wrap}
.sf-why-btn{font-size:.72rem;color:var(--accent-primary);font-weight:500}

/* Body */
.sf-body{padding:0 var(--sp-4) var(--sp-3);display:flex;flex-direction:column;gap:var(--sp-2)}
.sf-chips{display:flex;flex-wrap:wrap;gap:var(--sp-1)}
.sf-scope-text{font-size:.8rem;font-family:var(--font-mono);color:var(--text-secondary)}

/* Expandable occurrences */
.sf-details{border-top:1px solid var(--border)}
.sf-details summary{padding:var(--sp-2) var(--sp-4);font-size:.75rem;font-weight:500;
  color:var(--text-muted);cursor:pointer;display:flex;align-items:center;gap:var(--sp-2);
  background:none;user-select:none}
.sf-details summary:hover{color:var(--text-primary);background:var(--bg-raised)}
.sf-details[open] summary{border-bottom:1px solid var(--border)}
.sf-details-body{padding:0}
.sf-details-body .table-wrap{border:none;border-radius:0}
.sf-table .col-num{white-space:nowrap}
.sf-table{table-layout:fixed}

.sf-kind-meta{font-weight:normal;font-size:.8rem;color:var(--text-muted)}
.subsection-title{font-size:.95rem;margin:var(--sp-4) 0 var(--sp-2)}
.finding-occurrences-more summary{font-size:.8rem;color:var(--accent-primary);cursor:pointer;
  padding:var(--sp-1) var(--sp-3)}
.sf-card[data-filter-hidden="true"]{display:none}
/* Finding Why modal */
.finding-why-modal{max-width:720px;width:92vw;max-height:85vh}
.finding-why-modal .modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--border);flex-shrink:0}
.finding-why-modal .modal-head h2{font-size:1rem;font-weight:600}
.finding-why-modal .modal-body{padding:var(--sp-3) var(--sp-4);overflow-y:auto;flex:1 1 auto;min-height:0}
.metrics-section{margin-bottom:var(--sp-3)}
.metrics-section-title{font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
  color:var(--text-muted);margin-bottom:var(--sp-1);padding-bottom:3px;border-bottom:1px solid var(--border)}
.finding-why-text{font-size:.85rem;color:var(--text-secondary);line-height:1.5;margin:var(--sp-1) 0}
.finding-why-list{font-size:.82rem;color:var(--text-secondary);line-height:1.5;
  list-style:disc;padding-left:var(--sp-5);margin:var(--sp-1) 0}
.finding-why-list li{margin-bottom:2px}
.finding-why-note{font-size:.78rem;color:var(--text-muted);margin-bottom:var(--sp-2)}
.finding-why-examples{display:flex;flex-direction:column;gap:var(--sp-2)}
.finding-why-example{border:1px solid var(--border);border-radius:var(--radius-md);overflow:hidden}
.finding-why-example-head{display:flex;align-items:center;gap:var(--sp-2);padding:var(--sp-1) var(--sp-3);
  background:var(--bg-raised);font-size:.78rem;border-bottom:1px solid var(--border)}
.finding-why-example-label{font-weight:600;color:var(--text-primary)}
.finding-why-example-meta{color:var(--text-muted);font-family:var(--font-mono);font-size:.72rem}
.finding-why-example-loc{margin-left:auto;color:var(--text-muted);font-family:var(--font-mono);font-size:.72rem}
"""

# ---------------------------------------------------------------------------
# Report provenance / meta panel
# ---------------------------------------------------------------------------

_META_PANEL = """\
/* Provenance section cards */
.prov-section{margin-bottom:var(--sp-3);background:var(--bg-raised);
  border-radius:var(--radius-md);padding:var(--sp-3) var(--sp-3) var(--sp-2);
  border:1px solid color-mix(in srgb,var(--border) 50%,transparent)}
.prov-section:last-child{margin-bottom:0}
.prov-section-title{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  color:var(--text-muted);margin:0 0 var(--sp-2);padding:0;border:none;
  display:flex;align-items:center;gap:var(--sp-1)}
.prov-section-title svg{width:12px;height:12px;opacity:.5;flex-shrink:0}
.prov-table{width:100%;border-collapse:collapse;font-size:.8rem}
.prov-table tr:not(:last-child){border-bottom:1px solid color-mix(in srgb,var(--border) 30%,transparent)}
.prov-table tr:hover{background:color-mix(in srgb,var(--accent-primary) 4%,transparent)}
.prov-td-label{padding:5px 0;color:var(--text-muted);white-space:nowrap;width:40%;
  vertical-align:top;font-weight:500;font-size:.78rem}
.prov-td-value{padding:5px 0 5px var(--sp-2);color:var(--text-primary);word-break:break-all;
  font-family:var(--font-mono);font-size:.72rem}

/* Boolean check/cross badges */
.meta-bool{font-size:.7rem;font-weight:600;padding:1px 8px;border-radius:10px;
  display:inline-flex;align-items:center;gap:3px}
.meta-bool-true{background:var(--success-muted);color:var(--success)}
.meta-bool-false{background:var(--error-muted);color:var(--error)}

/* Provenance summary badges */
.prov-summary{display:flex;flex-wrap:wrap;align-items:center;gap:6px;
  padding:var(--sp-2) var(--sp-4);border-top:1px solid var(--border)}
.prov-badge{display:inline-flex;align-items:center;gap:4px;font-size:.66rem;
  padding:2px 8px;border-radius:var(--radius-sm);background:var(--bg-raised);
  white-space:nowrap;line-height:1.3;border:1px solid color-mix(in srgb,var(--border) 55%,transparent)}
.prov-badge-val{font-weight:600;font-variant-numeric:tabular-nums}
.prov-badge-lbl{font-weight:400;color:var(--text-muted);text-transform:lowercase}
.prov-badge--green{background:var(--success-muted);border-color:color-mix(in srgb,var(--success) 20%,transparent)}
.prov-badge--green .prov-badge-val{color:var(--success)}
.prov-badge--red{background:var(--error-muted);border-color:color-mix(in srgb,var(--error) 20%,transparent)}
.prov-badge--red .prov-badge-val{color:var(--error)}
.prov-badge--amber{background:var(--warning-muted);border-color:color-mix(in srgb,var(--warning) 20%,transparent)}
.prov-badge--amber .prov-badge-val{color:var(--warning)}
.prov-badge--neutral{background:var(--bg-overlay);border-color:color-mix(in srgb,var(--border) 75%,transparent)}
.prov-badge--neutral .prov-badge-val{color:var(--text-secondary)}
.prov-explain{font-size:.62rem;color:var(--text-muted);margin-left:auto;font-style:italic}
"""

# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------

_EMPTY = """\
.empty{display:flex;align-items:center;justify-content:center;padding:var(--sp-10)}
.empty-card{text-align:center;max-width:400px}
.empty-icon{margin-bottom:var(--sp-3);color:var(--success)}
.empty-icon svg{width:40px;height:40px}
.empty-card h2{margin-bottom:var(--sp-2)}
.empty-card p{color:var(--text-secondary);font-size:.9rem}
.tab-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:var(--sp-10);text-align:center}
.tab-empty-icon{color:var(--text-muted);opacity:.4;margin-bottom:var(--sp-3);width:48px;height:48px}
.tab-empty-title{font-size:1rem;font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-1)}
.tab-empty-desc{font-size:.85rem;color:var(--text-muted);max-width:320px}
"""

# ---------------------------------------------------------------------------
# Coupled details
# ---------------------------------------------------------------------------

_COUPLED = """\
.coupled-details{display:inline}
.coupled-summary{display:inline;cursor:pointer}
.coupled-summary:hover{color:var(--text-primary)}
.coupled-more{font-size:.75rem;color:var(--text-muted);margin-left:var(--sp-1)}
.coupled-expanded{margin-top:var(--sp-1)}
"""

# ---------------------------------------------------------------------------
# Modal (dialog)
# ---------------------------------------------------------------------------

_MODAL = """\
/* Generic dialog modal — Safari-compatible centering */
dialog{background:var(--bg-surface);color:var(--text-primary);border:1px solid var(--border);
  border-radius:var(--radius-xl);box-shadow:var(--shadow-xl);padding:0;max-width:600px;width:90vw;
  max-height:80vh;overflow:hidden}
dialog:not([open]){display:none}
dialog[open]{display:flex;flex-direction:column;
  position:fixed;inset:0;margin:auto;z-index:9999}
dialog::backdrop{background:rgba(0,0,0,.5);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
.modal-close{background:none;border:none;cursor:pointer;color:var(--text-muted);padding:var(--sp-1);
  font-size:1.25rem;line-height:1}
.modal-close:hover{color:var(--text-primary)}

/* Info modal (block metrics) */
#clone-info-modal{max-width:640px;width:92vw;max-height:85vh}
#clone-info-modal .modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--border)}
#clone-info-modal .modal-head h2{font-size:1rem}
#clone-info-modal .modal-body{padding:var(--sp-3) var(--sp-4);overflow-y:auto;flex:1 1 auto;min-height:0}
.info-dl{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:0}
.info-dl>div{display:flex;justify-content:space-between;gap:var(--sp-2);
  padding:var(--sp-2) var(--sp-3);border-bottom:1px solid var(--border)}
.info-dl>div:nth-last-child(-n+2){border-bottom:none}
.info-dl dt{font-size:.8rem;color:var(--text-muted);white-space:nowrap}
.info-dl dd{font-size:.8rem;font-weight:500;color:var(--text-primary);margin:0;text-align:right;
  font-family:var(--font-mono)}

/* Provenance modal */
dialog.prov-modal{max-width:660px;width:92vw;max-height:85vh}
.prov-modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-3) var(--sp-5);border-bottom:none;flex-shrink:0}
.prov-modal-head h2{font-size:1rem;font-weight:700;letter-spacing:-.01em}
.prov-modal-body{padding:0 var(--sp-4) var(--sp-4);overflow-y:auto;flex:1 1 auto}
.prov-modal .prov-summary{border-top:none;padding:0 var(--sp-5) var(--sp-3);
  border-bottom:1px solid var(--border);flex-shrink:0}

"""

# ---------------------------------------------------------------------------
# Command palette
# ---------------------------------------------------------------------------

_CMD_PALETTE = ""  # removed: command palette eliminated

# ---------------------------------------------------------------------------
# Toast notifications
# ---------------------------------------------------------------------------

_TOAST = """\
.toast-container{position:fixed;bottom:var(--sp-6);right:var(--sp-6);z-index:2000;
  display:flex;flex-direction:column;gap:var(--sp-2)}
.toast{padding:var(--sp-3) var(--sp-5);background:var(--bg-overlay);border:1px solid var(--border);
  border-radius:var(--radius-lg);box-shadow:var(--shadow-lg);font-size:.85rem;color:var(--text-primary);
  animation:toast-in var(--dur-slow) var(--ease)}
@keyframes toast-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
"""

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

_UTILITY = """\
/* Responsive */
@media(max-width:768px){
  .overview-kpi-grid{grid-template-columns:repeat(2,1fr)}
  .toolbar{flex-direction:column;align-items:stretch}
  .toolbar-left,.toolbar-right{justify-content:flex-start}
  .overview-list{grid-template-columns:1fr}
  .items{grid-template-columns:1fr}
  .items .item{border-right:none}
  .overview-row-head{flex-wrap:wrap}
  .overview-row-spread{margin-left:0;width:100%}
  .suggestion-head{flex-direction:column;align-items:flex-start}
  .suggestion-facts{grid-template-columns:1fr}
  .sf-head{flex-direction:column;align-items:flex-start}
  .sf-meta{width:100%}
  .container{padding:0 var(--sp-3)}
  .topbar{position:static}
  .topbar-inner{height:auto;padding:var(--sp-2) var(--sp-3);flex-direction:row;
    align-items:center;gap:var(--sp-2)}
  .brand{flex:1;min-width:0;align-items:center;gap:var(--sp-2)}
  .brand-logo{width:24px;height:24px}
  .brand-text{gap:0}
  .brand h1{font-size:.85rem;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .brand-project-name{font-size:.78em;padding:0 3px}
  .brand-meta{display:none}
  .topbar-actions{flex-shrink:0;gap:var(--sp-1)}
  .topbar-actions .btn-prov{font-size:0;gap:0;width:32px;height:32px;
    padding:0;align-items:center;justify-content:center}
  .topbar-actions .btn-prov .prov-dot{width:10px;height:10px}
  .theme-toggle{font-size:0;gap:0;width:32px;height:32px;
    padding:0;align-items:center;justify-content:center}
  .theme-toggle svg{width:16px;height:16px}
  .ide-picker-btn{font-size:0;gap:0;width:32px;height:32px;
    padding:0;align-items:center;justify-content:center}
  .ide-picker-btn svg{width:16px;height:16px}
  .ide-picker-label{display:none}
  .ide-menu{right:0;min-width:140px}
  .main-tabs-wrap{position:sticky;top:0;z-index:90;padding:var(--sp-2) 0 0}
  .main-tabs{padding:var(--sp-1);gap:2px;
    background:
      linear-gradient(to right,var(--bg-surface) 30%,transparent) left center / 28px 100% no-repeat local,
      linear-gradient(to left,var(--bg-surface) 30%,transparent) right center / 28px 100% no-repeat local,
      linear-gradient(to right,rgba(0,0,0,.12),transparent) left center / 10px 100% no-repeat scroll,
      linear-gradient(to left,rgba(0,0,0,.12),transparent) right center / 10px 100% no-repeat scroll,
      var(--bg-surface)}
  .main-tab{flex:none;padding:var(--sp-1) var(--sp-2);font-size:.78rem}
}
@media(max-width:480px){
  .overview-kpi-grid{grid-template-columns:1fr}
  .search-box input[type="text"]{width:140px}
  .brand-logo{width:28px;height:28px}
}

/* IDE link */
.ide-link{color:inherit;text-decoration:none;cursor:default}
[data-ide]:not([data-ide=""]) .ide-link{cursor:pointer;color:var(--accent-primary);
  text-decoration-line:underline;text-decoration-style:dotted;text-underline-offset:2px}
[data-ide]:not([data-ide=""]) .ide-link:hover{text-decoration-style:solid}

/* IDE picker dropdown */
.ide-picker{position:relative;display:inline-flex}
.ide-picker-btn{display:inline-flex;align-items:center;gap:var(--sp-1);
  padding:var(--sp-1) var(--sp-3);background:none;border:1px solid var(--border);
  border-radius:var(--radius-md);cursor:pointer;color:var(--text-muted);font-size:.85rem;
  font-weight:500;font-family:inherit;transition:all var(--dur-fast) var(--ease);
  white-space:nowrap}
.ide-picker-btn:hover{color:var(--text-primary);background:var(--bg-raised);border-color:var(--border-strong)}
.ide-picker-btn svg{width:16px;height:16px;flex-shrink:0}
.ide-picker-btn[aria-expanded="true"]{color:var(--accent-primary);border-color:var(--accent-primary)}
.ide-menu{display:none;position:absolute;top:100%;right:0;margin-top:var(--sp-1);
  min-width:160px;background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius);box-shadow:0 4px 12px rgba(0,0,0,.15);
  z-index:100;padding:var(--sp-1) 0;list-style:none}
.ide-menu[data-open]{display:block}
.ide-menu li{padding:0}
.ide-menu button{display:flex;align-items:center;gap:var(--sp-2);width:100%;
  padding:var(--sp-1) var(--sp-3);background:none;border:none;color:var(--text-primary);
  font-size:.8rem;font-family:var(--font-sans);cursor:pointer;text-align:left}
.ide-menu button:hover{background:var(--bg-alt)}
.ide-menu button[aria-checked="true"]{color:var(--accent-primary);font-weight:600}
.ide-menu button[aria-checked="true"]::before{content:'\\2713';font-size:.7rem;
  width:14px;text-align:center;flex-shrink:0}
.ide-menu button[aria-checked="false"]::before{content:'';width:14px;flex-shrink:0}

/* Print */
@media print{
  .topbar,.toolbar,.pagination,.theme-toggle,.toast-container,
  .novelty-tabs,.clear-btn,.btn,.ide-picker{display:none!important}
  .tab-panel{display:block!important;break-inside:avoid}
  .group-body{display:block!important}
  body{background:#fff;color:#000}
}
"""

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

_FOOTER = """\
.report-footer{margin-top:var(--sp-8);padding:var(--sp-4) 0;border-top:1px solid var(--border);
  text-align:center;font-size:.78rem;color:var(--text-muted)}
.report-footer a{color:var(--accent-primary)}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_ALL_SECTIONS = (
    _TOKENS_DARK,
    _TOKENS_LIGHT,
    _RESET,
    _LAYOUT,
    _CONTROLS,
    _SEARCH,
    _TOOLBAR,
    _INSIGHT,
    _TABLES,
    _SUB_TABS,
    _SECTIONS,
    _ITEMS,
    _CODE,
    _BADGES,
    _OVERVIEW,
    _DEPENDENCIES,
    _NOVELTY,
    _DEAD_CODE,
    _SUGGESTIONS,
    _STRUCTURAL,
    _META_PANEL,
    _EMPTY,
    _COUPLED,
    _MODAL,
    _CMD_PALETTE,
    _TOAST,
    _UTILITY,
    _FOOTER,
)


def build_css() -> str:
    """Return the complete CSS string for the HTML report."""
    return "\n".join(_ALL_SECTIONS)

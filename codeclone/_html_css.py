# SPDX-License-Identifier: MIT
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
  :root:not([data-theme="dark"]){
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
  -moz-osx-font-smoothing:grayscale;scroll-behavior:smooth}
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
.brand{display:flex;align-items:center;gap:var(--sp-3)}
.brand-logo{flex-shrink:0}
.brand-text{display:flex;flex-direction:column;gap:2px}
.brand h1{font-size:1.15rem;font-weight:700;color:var(--text-primary);line-height:1.3}
.brand-meta{font-size:.78rem;color:var(--text-muted)}
.brand-project{font-weight:500;color:var(--text-secondary)}
.brand-project-name{font-family:var(--font-mono);font-size:.85em;font-weight:500;padding:1px 5px;
  border-radius:var(--radius-sm);background:var(--bg-overlay);color:var(--accent-primary)}
.topbar-actions{display:flex;align-items:center;gap:var(--sp-2)}

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
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius-lg);
  margin-bottom:var(--sp-4)}
.table{width:100%;border-collapse:collapse;font-size:.82rem;font-family:var(--font-mono)}
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
.table .col-file{color:var(--text-muted);max-width:240px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.table .col-number{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.table .col-risk{white-space:nowrap}
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
.item{border-bottom:1px solid var(--border);padding:0}
.item:last-child{border-bottom:none}
.item-header{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-2) var(--sp-4);background:var(--bg-raised);gap:var(--sp-3)}
.item-title{font-weight:500;font-size:.85rem;color:var(--text-primary);font-family:var(--font-mono);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1}
.item-loc{font-size:.8rem;color:var(--text-muted);font-family:var(--font-mono);white-space:nowrap;flex-shrink:0}
.item-compare-meta{padding:var(--sp-1) var(--sp-4);font-size:.75rem;color:var(--text-muted);
  background:var(--bg-body);border-bottom:1px solid var(--border)}
"""

# ---------------------------------------------------------------------------
# Code blocks
# ---------------------------------------------------------------------------

_CODE = """\
.code-block{overflow-x:auto;font-size:12px;line-height:1.7;background:var(--bg-body);
  padding:var(--sp-2) 0;margin:0}
.code-block pre{margin:0;padding:0}
.code-block .linenos{user-select:none;text-align:right;padding-right:var(--sp-3);
  color:var(--text-muted);opacity:.5;min-width:3.5em;display:inline-block;font-size:11px}
.code-block .code-line{padding:0 var(--sp-4) 0 var(--sp-2);white-space:pre;display:block}
.code-block .code-line:hover{background:var(--bg-raised)}
.code-block .code-line.hl{background:var(--accent-muted)}
.code-block .code-line.hl:hover{background:color-mix(in oklch,var(--accent-primary) 20%,transparent)}
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
.category-badge{display:inline-flex;align-items:center;font-size:.7rem;font-weight:500;
  font-family:var(--font-mono);padding:1px var(--sp-2);border-radius:var(--radius-sm);
  background:var(--bg-overlay);color:var(--text-muted);white-space:nowrap}
.finding-why-chips{display:flex;flex-wrap:wrap;gap:var(--sp-1);margin:var(--sp-1) 0}
.finding-why-chips .category-badge{font-size:.72rem}
"""

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

_OVERVIEW = """\
/* Dashboard */
.overview-kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:var(--sp-3);align-items:stretch;margin-bottom:var(--sp-6)}
.overview-kpi-grid--with-health{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.overview-kpi-grid--with-health .meta-item{min-width:0}
@media(min-width:1440px){
  .overview-kpi-grid--with-health{grid-template-columns:repeat(7,minmax(0,1fr))}
}

/* Health gauge */
.overview-health-card{display:flex;align-items:center;justify-content:center;
  min-height:0;padding:var(--sp-3) var(--sp-2)}
.overview-health-inner{display:flex;align-items:center;justify-content:center;width:100%;height:100%}
.health-ring{position:relative;width:110px;height:110px}
.health-ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.health-ring-bg{fill:none;stroke:var(--border);stroke-width:6}
.health-ring-fg{fill:none;stroke-width:6;stroke-linecap:round;
  transition:stroke-dashoffset 1s var(--ease)}
.health-ring-label{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center}
.health-ring-score{font-size:1.5rem;font-weight:700;color:var(--text-primary);
  font-variant-numeric:tabular-nums;line-height:1}
.health-ring-grade{font-size:.7rem;font-weight:500;color:var(--text-muted);margin-top:2px}
.health-ring-delta{font-size:.65rem;font-weight:600;margin-top:2px}
.health-ring-delta--up{color:var(--success)}
.health-ring-delta--down{color:var(--error)}

/* KPI stat card */
.meta-item{padding:var(--sp-3) var(--sp-4);background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);display:flex;flex-direction:column;gap:var(--sp-1);
  transition:border-color var(--dur-fast) var(--ease)}
.meta-item:hover{border-color:var(--border-strong)}
.meta-item .meta-label{font-size:.75rem;font-weight:500;color:var(--text-muted);
  display:flex;align-items:center;gap:var(--sp-1)}
.meta-item .meta-value{font-size:1.25rem;font-weight:700;color:var(--text-primary);
  font-variant-numeric:tabular-nums}
.kpi-detail{font-size:.75rem;color:var(--text-muted);margin-top:var(--sp-1)}
.kpi-delta{font-size:.72rem;font-weight:600;margin-top:var(--sp-1)}
.kpi-delta--good{color:var(--success)}
.kpi-delta--bad{color:var(--error)}
.kpi-delta--neutral{color:var(--text-muted)}
.kpi-help{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;
  font-size:.65rem;font-weight:700;border-radius:50%;background:var(--bg-overlay);
  color:var(--text-muted);cursor:help;position:relative}
.kpi-help:hover::after{content:attr(data-tip);position:absolute;bottom:calc(100% + 6px);left:50%;
  transform:translateX(-50%);background:var(--bg-overlay);color:var(--text-primary);
  padding:var(--sp-2) var(--sp-3);border-radius:var(--radius-md);font-size:.75rem;font-weight:400;
  white-space:nowrap;box-shadow:var(--shadow-md);z-index:50;pointer-events:none;
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
.overview-list{display:flex;flex-direction:column;gap:var(--sp-2)}

/* Overview rows */
.overview-row{display:grid;grid-template-columns:1fr auto;gap:var(--sp-4);
  padding:var(--sp-3) var(--sp-4);background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);transition:border-color var(--dur-fast) var(--ease)}
.overview-row:hover{border-color:var(--border-strong)}
.overview-row-main{min-width:0}
.overview-row-title{font-weight:600;font-size:.9rem;color:var(--text-primary);margin-bottom:var(--sp-1)}
.overview-row-summary{font-size:.8rem;color:var(--text-secondary);line-height:1.5}
.overview-row-side{text-align:right;display:flex;flex-direction:column;gap:var(--sp-1);flex-shrink:0}
.overview-row-context{font-size:.72rem;color:var(--text-muted)}
.overview-row-meta{font-size:.75rem;color:var(--text-muted);font-family:var(--font-mono)}

/* Summary grid */
.overview-summary-grid{display:grid;gap:var(--sp-2);margin-bottom:var(--sp-3)}
.overview-summary-grid--2col{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.overview-summary-item{background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-lg);padding:var(--sp-3) var(--sp-4)}
.overview-summary-label{font-size:.75rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;color:var(--text-muted);margin-bottom:var(--sp-2)}
.overview-summary-list{display:flex;flex-direction:column;gap:var(--sp-1)}
.overview-summary-list li{font-size:.85rem;color:var(--text-secondary);
  padding-left:var(--sp-3);position:relative}
.overview-summary-list li::before{content:"\\2022";position:absolute;left:0;color:var(--text-muted)}
.overview-summary-value{font-size:.85rem;color:var(--text-muted)}
"""

# ---------------------------------------------------------------------------
# Dependencies (SVG graph)
# ---------------------------------------------------------------------------

_DEPENDENCIES = """\
.dep-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:var(--sp-3);margin-bottom:var(--sp-4)}
.dep-graph-wrap{overflow-x:auto;margin-bottom:var(--sp-4);border:1px solid var(--border);
  border-radius:var(--radius-lg);background:var(--bg-surface);padding:var(--sp-4)}
.dep-graph-svg{min-width:100%;width:max-content;height:auto;min-height:280px}
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
.novelty-tab[data-novelty-state="good"]{color:var(--success);border-color:var(--success)}
.novelty-tab[data-novelty-state="good"].active{background:var(--success);color:white;border-color:var(--success)}
.novelty-tab[data-novelty-state="bad"]{color:var(--error);border-color:var(--error)}
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
.suggestion-title{font-weight:600;font-size:.85rem;color:var(--text-primary);flex:1;min-width:0}
.suggestion-meta{display:flex;align-items:center;gap:var(--sp-1);flex-shrink:0;flex-wrap:wrap}
.suggestion-meta-badge{font-size:.68rem;font-family:var(--font-mono);font-weight:500;
  padding:1px var(--sp-2);border-radius:var(--radius-sm);background:var(--bg-overlay);
  color:var(--text-muted);white-space:nowrap}

/* Body — context + summary */
.suggestion-body{padding:0 var(--sp-4) var(--sp-3);display:flex;flex-direction:column;gap:var(--sp-1)}
.suggestion-context{font-size:.72rem;color:var(--text-muted)}
.suggestion-summary{font-size:.82rem;color:var(--text-secondary);line-height:1.5}
.suggestion-action{font-size:.8rem;color:var(--text-secondary);margin-top:var(--sp-1)}
.suggestion-action strong{font-weight:600;color:var(--text-primary);font-size:.72rem;
  text-transform:uppercase;letter-spacing:.04em;margin-right:var(--sp-1)}

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
.suggestion-locations li{display:flex;gap:var(--sp-3);align-items:baseline}
.suggestion-loc-path{font-family:var(--font-mono);font-size:.75rem;color:var(--text-secondary)}
.suggestion-loc-name{font-family:var(--font-mono);font-size:.72rem;color:var(--text-muted)}
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
.sf-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  overflow:hidden;transition:border-color var(--dur-fast) var(--ease),box-shadow var(--dur-fast) var(--ease)}
.sf-card:hover{border-color:var(--border-strong);box-shadow:var(--shadow-sm)}

/* Header row */
.sf-head{padding:var(--sp-3) var(--sp-4);display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap}
.sf-count-pill{font-size:.68rem;font-weight:600;padding:2px var(--sp-2);border-radius:var(--radius-sm);
  background:var(--bg-overlay);color:var(--text-primary);white-space:nowrap}
.sf-title{font-weight:600;font-size:.85rem;color:var(--text-primary);flex:1;min-width:0}
.sf-meta{display:flex;align-items:center;gap:var(--sp-1);flex-shrink:0;flex-wrap:wrap}

/* Body */
.sf-body{padding:0 var(--sp-4) var(--sp-3);display:flex;flex-direction:column;gap:var(--sp-1)}
.sf-scope{font-size:.72rem;color:var(--text-muted)}

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
"""

# ---------------------------------------------------------------------------
# Report provenance / meta panel
# ---------------------------------------------------------------------------

_META_PANEL = """\
/* Provenance table layout */
.prov-section{margin-bottom:var(--sp-3)}
.prov-section:last-child{margin-bottom:0}
.prov-section-title{font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  color:var(--text-muted);margin:0 0 var(--sp-1);padding-bottom:3px;
  border-bottom:1px solid var(--border)}
.prov-table{width:100%;border-collapse:collapse;font-size:.8rem}
.prov-table tr:not(:last-child){border-bottom:1px solid color-mix(in srgb,var(--border) 40%,transparent)}
.prov-td-label{padding:3px 0;color:var(--text-muted);white-space:nowrap;width:40%;
  vertical-align:top;font-weight:500}
.prov-td-value{padding:3px 0 3px var(--sp-2);color:var(--text-primary);word-break:break-all;
  font-family:var(--font-mono);font-size:.75rem}
.meta-bool{font-size:.7rem;font-weight:600;padding:0 var(--sp-1);border-radius:var(--radius-sm)}
.meta-bool-true{background:var(--success-muted);color:var(--success)}
.meta-bool-false{background:var(--error-muted);color:var(--error)}

/* Provenance summary badges */
.prov-summary{display:flex;flex-wrap:wrap;align-items:center;gap:4px;
  padding:var(--sp-2) var(--sp-4);border-top:1px solid var(--border)}
.prov-badge{font-size:.65rem;font-weight:600;padding:1px 6px;
  border-radius:var(--radius-sm);white-space:nowrap}
.prov-badge.green{background:var(--success-muted);color:var(--success)}
.prov-badge.red{background:var(--error-muted);color:var(--error)}
.prov-badge.amber{background:var(--warning-muted);color:var(--warning)}
.prov-badge.neutral{background:var(--bg-overlay);color:var(--text-muted)}
.prov-sep{color:var(--text-muted);font-size:.5rem;margin:0 1px}
.prov-explain{font-size:.65rem;color:var(--text-muted);margin-left:var(--sp-1)}
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
dialog.prov-modal{max-width:640px;width:92vw;max-height:85vh}
.prov-modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-4) var(--sp-5);border-bottom:1px solid var(--border);flex-shrink:0}
.prov-modal-head h2{font-size:1.1rem;font-weight:600}
.prov-modal-body{padding:var(--sp-3) var(--sp-5);overflow-y:auto;flex:1 1 auto}
.prov-modal .prov-summary{border-top:none;padding:var(--sp-2) var(--sp-5);
  border-bottom:1px solid var(--border);flex-shrink:0}

/* Help modal */
dialog.help-modal{max-width:560px;width:92vw;max-height:80vh}
dialog.help-modal .modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--border)}
dialog.help-modal .modal-head h2{font-size:1rem}
dialog.help-modal .modal-body{overflow-y:auto;flex:1 1 auto;min-height:0}
.help-section{padding:var(--sp-3) var(--sp-5)}
.help-section + .help-section{border-top:1px solid var(--border)}
.help-section h3{font-size:.78rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
  color:var(--text-muted);margin-bottom:var(--sp-2)}
.help-section p{font-size:.88rem;color:var(--text-secondary)}
.help-links,.help-shortcuts{display:flex;flex-direction:column;gap:var(--sp-2)}
.help-links a{color:var(--accent-primary)}
.help-shortcut-row{display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);
  font-size:.88rem;color:var(--text-secondary)}
.help-shortcut-row kbd{font-family:var(--font-mono);font-size:.74rem;padding:2px 8px;
  border-radius:var(--radius-sm);background:var(--bg-overlay);color:var(--text-primary)}
"""

# ---------------------------------------------------------------------------
# Command palette
# ---------------------------------------------------------------------------

_CMD_PALETTE = """\
.cmd-palette{position:fixed;inset:0;z-index:1000;display:none;align-items:flex-start;
  justify-content:center;padding-top:20vh;background:rgba(0,0,0,.5);backdrop-filter:blur(4px)}
.cmd-palette.open{display:flex}
.cmd-palette-box{width:90%;max-width:480px;background:var(--bg-surface);border:1px solid var(--border);
  border-radius:var(--radius-xl);box-shadow:var(--shadow-xl);overflow:hidden}
.cmd-palette-input{width:100%;padding:var(--sp-4) var(--sp-5);background:none;border:none;
  border-bottom:1px solid var(--border);font-size:.95rem;color:var(--text-primary);outline:none}
.cmd-palette-input::placeholder{color:var(--text-muted)}
.cmd-palette-list{max-height:300px;overflow-y:auto;padding:var(--sp-2)}
.cmd-palette-item{padding:var(--sp-2) var(--sp-4);border-radius:var(--radius-md);cursor:pointer;
  font-size:.85rem;color:var(--text-secondary);display:flex;align-items:center;gap:var(--sp-2)}
.cmd-palette-item:hover,.cmd-palette-item.active{background:var(--bg-raised);color:var(--text-primary)}
.cmd-palette-item kbd{font-size:.72rem;color:var(--text-muted);margin-left:auto;
  font-family:var(--font-mono)}
"""

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
  .overview-row{grid-template-columns:1fr}
  .overview-row-side{text-align:left}
  .suggestion-head{flex-direction:column;align-items:flex-start}
  .suggestion-facts{grid-template-columns:1fr}
  .container{padding:0 var(--sp-3)}
  .main-tabs{padding:0 var(--sp-3)}
}
@media(max-width:480px){
  .overview-kpi-grid{grid-template-columns:1fr}
  .search-box input[type="text"]{width:140px}
}

/* Print */
@media print{
  .topbar,.toolbar,.pagination,.cmd-palette,.theme-toggle,.toast-container,
  .novelty-tabs,.clear-btn,.btn{display:none!important}
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

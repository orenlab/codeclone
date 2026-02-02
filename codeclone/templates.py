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

<style>
/* ============================
   CodeClone UI/UX
   ============================ */

:root {
  --bg: #0d1117;
  --panel: #161b22;
  --panel2: #21262d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --border: #30363d;
  --border2: #6e7681;
  --accent: #58a6ff;
  --accent2: rgba(56, 139, 253, 0.15);
  --good: #3fb950;
  --shadow: 0 8px 24px rgba(0,0,0,0.5);
  --shadow2: 0 4px 12px rgba(0,0,0,0.2);
  --radius: 6px;
  --radius2: 8px;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
    "Liberation Mono", monospace;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial,
    sans-serif, "Apple Color Emoji", "Segoe UI Emoji";
}

html[data-theme="light"] {
  --bg: #ffffff;
  --panel: #f6f8fa;
  --panel2: #eaeef2;
  --text: #24292f;
  --muted: #57606a;
  --border: #d0d7de;
  --border2: #afb8c1;
  --accent: #0969da;
  --accent2: rgba(84, 174, 255, 0.2);
  --good: #1a7f37;
  --shadow: 0 8px 24px rgba(140,149,159,0.2);
  --shadow2: 0 4px 12px rgba(140,149,159,0.1);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  line-height: 1.5;
}

.container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 20px 80px;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  opacity: 0.98;
}

.topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 20px;
  max-width: 1400px;
  margin: 0 auto;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.brand .sub {
  color: var(--muted);
  font-size: 13px;
  background: var(--panel2);
  padding: 2px 8px;
  border-radius: 99px;
  font-weight: 500;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: 0.2s;
  height: 32px;
}

.btn:hover {
  border-color: var(--border2);
  background: var(--panel2);
}

.btn.ghost {
  background: transparent;
  border-color: transparent;
  padding: 4px;
  width: 28px;
  height: 28px;
}

.select {
  padding: 0 24px 0 8px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--text);
  font-size: 13px;
}

.section {
  margin-top: 32px;
}

.section-head {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 16px;
}

.section-head h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 12px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
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

.search-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  min-width: 300px;
  height: 32px;
}
.search-wrap:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent2);
}

.search-ico {
  color: var(--muted);
  display: flex;
}

.search {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 13px;
}

.segmented {
  display: inline-flex;
  background: var(--panel2);
  padding: 2px;
  border-radius: 6px;
}

.btn.seg {
  border: none;
  background: transparent;
  height: 28px;
  font-size: 12px;
}
.btn.seg:hover {
  background: var(--bg);
  box-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.pager {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.page-meta {
  color: var(--text);
  font-size: 13px;
  white-space: nowrap;
  min-width: 80px;
  text-align: center;
}

.pill {
  padding: 2px 10px;
  border-radius: 99px;
  background: var(--accent2);
  border: 1px solid rgba(56, 139, 253, 0.3);
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}
.pill.small {
  padding: 1px 8px;
  font-size: 11px;
}
.pill-func {
  color: var(--accent);
  background: var(--accent2);
}
.pill-block {
  color: var(--good);
  background: rgba(63, 185, 80, 0.15);
  border-color: rgba(63, 185, 80, 0.3);
}

.group {
  margin-bottom: 16px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  box-shadow: var(--shadow2);
}

.group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}

.group-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.group-title {
  font-weight: 600;
  font-size: 14px;
}

.gkey {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
  background: var(--panel2);
  padding: 2px 6px;
  border-radius: 4px;
}

.chev {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--muted);
  padding: 0;
}
.chev:hover {
  color: var(--text);
  border-color: var(--border2);
}

.items {
  padding: 16px;
}

.item-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
  min-width: 0; /* Allow grid items to shrink */
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
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0; /* Allow flex items to shrink below content size */
}

.item-head {
  padding: 8px 12px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
}

.item-file {
  padding: 6px 12px;
  background: var(--panel2);
  border-bottom: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}

.codebox {
  margin: 0;
  padding: 0;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  overflow-y: auto;
  background: var(--bg);
  flex: 1;
  max-width: 100%;
  max-height: 600px;
}

.codebox pre {
  margin: 0;
  padding: 12px;
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
}

.empty {
  padding: 60px 0;
  display: flex;
  justify-content: center;
}
.empty-card {
  text-align: center;
  padding: 40px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  max-width: 500px;
}
.empty-icon {
  color: var(--good);
  margin-bottom: 16px;
  display: flex;
  justify-content: center;
}

.footer {
  margin-top: 60px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  border-top: 1px solid var(--border);
  padding-top: 24px;
}

${pyg_dark}
${pyg_light}
</style>
</head>

<body>
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <h1>${title}</h1>
      <div class="sub">v${version}</div>
    </div>
    <div class="top-actions">
      <button class="btn" type="button" id="theme-toggle" title="Toggle theme">
        ${icon_theme} Theme
      </button>
    </div>
  </div>
</div>

<div class="container">
${empty_state_html}

${func_section}
${block_section}

<div class="footer">Generated by CodeClone v${version}</div>
</div>

<script>
(() => {
  const htmlEl = document.documentElement;
  const btnTheme = document.getElementById("theme-toggle");

  const stored = localStorage.getItem("codeclone_theme");
  if (stored === "light" || stored === "dark") {
    htmlEl.setAttribute("data-theme", stored);
  }

  btnTheme?.addEventListener("click", () => {
    const cur = htmlEl.getAttribute("data-theme") || "dark";
    const next = cur === "dark" ? "light" : "dark";
    htmlEl.setAttribute("data-theme", next);
    localStorage.setItem("codeclone_theme", next);
  });

  // Toggle group visibility via header click
  document.querySelectorAll(".group-head").forEach((head) => {
    head.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      const btn = head.querySelector("[data-toggle-group]");
      if (btn) btn.click();
    });
  });

  document.querySelectorAll("[data-toggle-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-toggle-group");
      const body = document.getElementById("group-body-" + id);
      if (!body) return;

      const isHidden = body.style.display === "none";
      body.style.display = isHidden ? "" : "none";
      btn.style.transform = isHidden ? "rotate(0deg)" : "rotate(-90deg)";
    });
  });

  function initSection(sectionId) {
    const section = document.querySelector(
      `section[data-section='$${sectionId}']`
    );
    if (!section) return;

    const groups = Array.from(
      section.querySelectorAll(`.group[data-group='$${sectionId}']`)
    );
    const searchInput = document.getElementById(`search-$${sectionId}`);
    const btnPrev = section.querySelector(`[data-prev='$${sectionId}']`);
    const btnNext = section.querySelector(`[data-next='$${sectionId}']`);
    const meta = section.querySelector(`[data-page-meta='$${sectionId}']`);
    const selPageSize = section.querySelector(`[data-pagesize='$${sectionId}']`);
    const btnClear = section.querySelector(`[data-clear='$${sectionId}']`);
    const btnCollapseAll = section.querySelector(
      `[data-collapse-all='$${sectionId}']`
    );
    const btnExpandAll = section.querySelector(
      `[data-expand-all='$${sectionId}']`
    );
    const pill = section.querySelector(`[data-count-pill='$${sectionId}']`);

    const state = {
      q: "",
      page: 1,
      pageSize: parseInt(selPageSize?.value || "10", 10),
      filtered: groups
    };

    function setGroupVisible(el, yes) {
      el.style.display = yes ? "" : "none";
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
      const q = (state.q || "").trim().toLowerCase();
      if (!q) {
        state.filtered = groups;
      } else {
        state.filtered = groups.filter(g => {
          const blob = g.getAttribute("data-search") || "";
          return blob.indexOf(q) !== -1;
        });
      }
      state.page = 1;
      render();
    }

    searchInput?.addEventListener("input", (e) => {
      state.q = e.target.value || "";
      applyFilter();
    });

    btnClear?.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      state.q = "";
      applyFilter();
    });

    selPageSize?.addEventListener("change", () => {
      state.pageSize = parseInt(selPageSize.value || "10", 10);
      state.page = 1;
      render();
    });

    btnPrev?.addEventListener("click", () => {
      state.page -= 1;
      render();
    });

    btnNext?.addEventListener("click", () => {
      state.page += 1;
      render();
    });

    btnCollapseAll?.addEventListener("click", () => {
      section.querySelectorAll(".items").forEach(b => {
        b.style.display = "none";
      });
      section.querySelectorAll("[data-toggle-group]").forEach(c => {
        c.style.transform = "rotate(-90deg)";
      });
    });

    btnExpandAll?.addEventListener("click", () => {
      section.querySelectorAll(".items").forEach(b => {
        b.style.display = "";
      });
      section.querySelectorAll("[data-toggle-group]").forEach(c => {
        c.style.transform = "rotate(0deg)";
      });
    });

    render();
  }

  initSection("functions");
  initSection("blocks");
})();
</script>
</body>
</html>
""")

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""JavaScript for the HTML report — modular IIFE with feature blocks."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

_CORE = """\
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
"""

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

_THEME = """\
(function initTheme(){
  const key='codeclone-theme';
  const root=document.documentElement;
  const saved=localStorage.getItem(key);
  if(saved)root.setAttribute('data-theme',saved);

  const btn=$('.theme-toggle');
  if(!btn)return;
  btn.addEventListener('click',()=>{
    const cur=root.getAttribute('data-theme');
    const next=cur==='light'?'dark':'light';
    root.setAttribute('data-theme',next);
    localStorage.setItem(key,next);
  });
})();
"""

# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------

_TABS = """\
(function initTabs(){
  const tabs=$$('.main-tab');
  const panels=$$('.tab-panel');
  if(!tabs.length)return;

  function activate(id){
    tabs.forEach(t=>{t.setAttribute('aria-selected',t.dataset.tab===id?'true':'false')});
    panels.forEach(p=>{p.classList.toggle('active',p.id==='panel-'+id)});
    history.replaceState(null,'','#'+id);
  }

  tabs.forEach(t=>t.addEventListener('click',()=>activate(t.dataset.tab)));

  // Keyboard: arrow left/right
  const tabList=$('[role="tablist"].main-tabs');
  if(tabList){
    tabList.addEventListener('keydown',e=>{
      const idx=tabs.indexOf(document.activeElement);
      if(idx<0)return;
      let next=-1;
      if(e.key==='ArrowRight')next=(idx+1)%tabs.length;
      else if(e.key==='ArrowLeft')next=(idx-1+tabs.length)%tabs.length;
      if(next>=0){e.preventDefault();tabs[next].focus();activate(tabs[next].dataset.tab)}
    });
  }

  // Hash deep-link
  const hash=location.hash.slice(1);
  const valid=tabs.map(t=>t.dataset.tab);
  activate(valid.includes(hash)?hash:valid[0]||'');
})();
"""

# ---------------------------------------------------------------------------
# Sub-tabs (clone-nav / split-tabs)
# ---------------------------------------------------------------------------

_SUB_TABS = """\
(function initSubTabs(){
  $$('.clone-nav-btn').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const group=btn.dataset.subtabGroup;
      if(!group)return;
      $$('.clone-nav-btn[data-subtab-group="'+group+'"]').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      $$('.clone-panel[data-subtab-group="'+group+'"]').forEach(p=>{
        p.classList.toggle('active',p.dataset.clonePanel===btn.dataset.cloneTab);
      });
    });
  });
})();
"""

# ---------------------------------------------------------------------------
# Sections: search, filter, pagination, collapse/expand
# ---------------------------------------------------------------------------

_SECTIONS = """\
(function initSections(){
  // Registry so novelty filter can call applyFilters directly (no debounce)
  window.__sectionFilters=window.__sectionFilters||{};

  $$('[data-section]').forEach(sec=>{
    const id=sec.dataset.section;
    const groups=[...sec.querySelectorAll('.group[data-group="'+id+'"]')];
    const searchInput=$('#search-'+id);
    const pageMeta=sec.querySelector('[data-page-meta="'+id+'"]');
    const pageSizeSelect=sec.querySelector('[data-pagesize="'+id+'"]');
    const sourceKindFilter=sec.querySelector('[data-source-kind-filter="'+id+'"]');
    const cloneTypeFilter=sec.querySelector('[data-clone-type-filter="'+id+'"]');
    const spreadFilter=sec.querySelector('[data-spread-filter="'+id+'"]');
    const minOccCheck=sec.querySelector('[data-min-occurrences-filter="'+id+'"]');

    let page=1;
    let pageSize=parseInt(pageSizeSelect?.value||'10',10);

    function isAll(v){return !v||v==='all'}

    function applyFilters(){
      const q=(searchInput?.value||'').toLowerCase().trim();
      const sk=sourceKindFilter?.value||'';
      const ct=cloneTypeFilter?.value||'';
      const sp=spreadFilter?.value||'';
      const minOcc=minOccCheck?.checked||false;

      groups.forEach(g=>{
        // Novelty-hidden groups are always hidden
        if(g.getAttribute('data-novelty-hidden')==='true'){g.style.display='none';return}
        let show=true;
        if(q&&!(g.dataset.search||'').includes(q))show=false;
        if(!isAll(sk)&&g.dataset.sourceKind!==sk)show=false;
        if(!isAll(ct)&&g.dataset.cloneType!==ct)show=false;
        if(!isAll(sp)&&g.dataset.spreadBucket!==sp)show=false;
        if(minOcc&&parseInt(g.dataset.groupArity||'0',10)<4)show=false;
        g.style.display=show?'':'none';
      });
      page=1;
      paginate();
    }

    function paginate(){
      // Collect groups that passed both novelty + search/filter
      const vis=groups.filter(g=>g.style.display!=='none');
      const totalPages=Math.max(1,Math.ceil(vis.length/pageSize));
      if(page>totalPages)page=totalPages;
      const start=(page-1)*pageSize;
      const end=start+pageSize;
      vis.forEach((g,i)=>{g.style.display=i>=start&&i<end?'':'none'});
      if(pageMeta)pageMeta.textContent='Page '+page+' / '+totalPages+' \\u2022 '+vis.length+' groups';
      // Also update any visible tab count
      const tabCount=$('[data-clone-tab-count="'+id+'"]');
      if(tabCount){tabCount.textContent=vis.length;tabCount.dataset.totalGroups=vis.length}
    }

    // Register so novelty can call directly
    window.__sectionFilters[id]=applyFilters;

    // Events
    if(searchInput){
      let timer;
      searchInput.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(applyFilters,200)});
    }
    [sourceKindFilter,cloneTypeFilter,spreadFilter].forEach(el=>{
      if(el)el.addEventListener('change',applyFilters);
    });
    if(minOccCheck)minOccCheck.addEventListener('change',applyFilters);
    if(pageSizeSelect)pageSizeSelect.addEventListener('change',()=>{
      pageSize=parseInt(pageSizeSelect.value,10);page=1;paginate()});

    // Clear search
    const clearBtn=sec.querySelector('[data-clear="'+id+'"]');
    if(clearBtn&&searchInput)clearBtn.addEventListener('click',()=>{searchInput.value='';applyFilters()});

    // Prev/Next
    const prevBtn=sec.querySelector('[data-prev="'+id+'"]');
    const nextBtn=sec.querySelector('[data-next="'+id+'"]');
    if(prevBtn)prevBtn.addEventListener('click',()=>{if(page>1){page--;paginate()}});
    if(nextBtn)nextBtn.addEventListener('click',()=>{
      const vis=visible();const tp=Math.max(1,Math.ceil(vis.length/pageSize));
      if(page<tp){page++;paginate()}});

    // Collapse/Expand all
    const colBtn=sec.querySelector('[data-collapse-all="'+id+'"]');
    const expBtn=sec.querySelector('[data-expand-all="'+id+'"]');
    if(colBtn)colBtn.addEventListener('click',()=>{
      groups.forEach(g=>{
        const body=g.querySelector('.group-body');if(body)body.classList.remove('expanded');
        const toggle=g.querySelector('.group-toggle');if(toggle)toggle.classList.remove('expanded');
      })});
    if(expBtn)expBtn.addEventListener('click',()=>{
      groups.filter(g=>g.style.display!=='none').forEach(g=>{
        const body=g.querySelector('.group-body');if(body)body.classList.add('expanded');
        const toggle=g.querySelector('.group-toggle');if(toggle)toggle.classList.add('expanded');
      })});

    // Initial
    applyFilters();
  });

  // Toggle individual groups
  document.addEventListener('click',e=>{
    const btn=e.target.closest('[data-toggle-group]');
    if(!btn)return;
    const groupId=btn.dataset.toggleGroup;
    const body=$('#group-body-'+groupId);
    if(!body)return;
    body.classList.toggle('expanded');
    btn.classList.toggle('expanded');
  });

  // Also toggle on group-head click (except buttons)
  document.addEventListener('click',e=>{
    const head=e.target.closest('.group-head');
    if(!head)return;
    if(e.target.closest('button'))return;
    const toggle=head.querySelector('.group-toggle');
    if(toggle)toggle.click();
  });
})();
"""

# ---------------------------------------------------------------------------
# Novelty filter (global new/known)
# ---------------------------------------------------------------------------

_NOVELTY = """\
(function initNovelty(){
  const ctrl=$('#global-novelty-controls');
  if(!ctrl)return;
  const defaultNovelty=ctrl.dataset.defaultNovelty||'new';
  const btns=$$('[data-global-novelty]');
  let activeNovelty='';

  function applyNovelty(val){
    activeNovelty=val;
    btns.forEach(b=>b.classList.toggle('active',b.dataset.globalNovelty===val));
    $$('.group[data-novelty]').forEach(g=>{
      const nov=g.dataset.novelty;
      if(nov==='all')g.setAttribute('data-novelty-hidden','false');
      else g.setAttribute('data-novelty-hidden',nov!==val?'true':'false');
    });
    // Re-run section filters directly (no debounce)
    const reg=window.__sectionFilters||{};
    Object.values(reg).forEach(fn=>fn());
  }

  btns.forEach(b=>b.addEventListener('click',()=>applyNovelty(b.dataset.globalNovelty)));
  applyNovelty(defaultNovelty);
})();
"""

# ---------------------------------------------------------------------------
# Modals (dialog-based for block metrics info)
# ---------------------------------------------------------------------------

_MODALS = """\
(function initModals(){
  let dlg=$('#clone-info-modal');
  if(!dlg){
    dlg=document.createElement('dialog');
    dlg.id='clone-info-modal';
    dlg.innerHTML='<div class="modal-head"><h2 id="modal-title">Info</h2>'
      +'<button class="modal-close" type="button" aria-label="Close">&times;</button></div>'
      +'<div class="modal-body" id="modal-body"></div>';
    document.body.appendChild(dlg);
    dlg.querySelector('.modal-close').addEventListener('click',()=>dlg.close());
    dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close()});
  }

  document.addEventListener('click',e=>{
    const btn=e.target.closest('[data-metrics-btn]');
    if(!btn)return;
    const groupId=btn.dataset.metricsBtn;
    const group=btn.closest('.group');
    if(!group)return;
    const d=group.dataset;
    const items=[];
    function add(label,val){if(val)items.push('<div><dt>'+label+'</dt><dd>'+val+'</dd></div>')}
    add('Match rule',d.matchRule);
    add('Block size',d.blockSize);
    add('Signature',d.signatureKind);
    add('Merged regions',d.mergedRegions);
    add('Pattern',d.patternLabel);
    add('Hint',d.hintLabel);
    add('Hint confidence',d.hintConfidence);
    add('Assert ratio',d.assertRatio);
    add('Consecutive asserts',d.consecutiveAsserts);
    add('Boilerplate asserts',d.boilerplateAsserts);
    add('Group arity',d.groupArity);
    add('Clone type',d.cloneType);
    add('Source kind',d.sourceKind);
    if(d.spreadFiles)add('Spread',d.spreadFunctions+' fn / '+d.spreadFiles+' files');
    dlg.querySelector('#modal-title').textContent='Group: '+groupId;
    dlg.querySelector('#modal-body').innerHTML=items.length
      ?'<dl class="info-dl">'+items.join('')+'</dl>'
      :'<p class="muted">No metadata available.</p>';
    dlg.showModal();
  });
})();
"""

# ---------------------------------------------------------------------------
# Suggestions filter
# ---------------------------------------------------------------------------

_SUGGESTIONS = """\
(function initSuggestions(){
  const body=$('[data-suggestions-body]');
  if(!body)return;
  const cards=[...body.querySelectorAll('[data-suggestion-card]')];
  const sevSel=$('[data-suggestions-severity]');
  const catSel=$('[data-suggestions-category]');
  const famSel=$('[data-suggestions-family]');
  const skSel=$('[data-suggestions-source-kind]');
  const spSel=$('[data-suggestions-spread]');
  const actCheck=$('[data-suggestions-actionable]');
  const countLabel=$('[data-suggestions-count]');

  function apply(){
    const sev=sevSel?.value||'';
    const cat=catSel?.value||'';
    const fam=famSel?.value||'';
    const sk=skSel?.value||'';
    const sp=spSel?.value||'';
    const act=actCheck?.checked||false;
    let shown=0;
    cards.forEach(c=>{
      let hide=false;
      if(sev&&c.dataset.severity!==sev)hide=true;
      if(cat&&c.dataset.category!==cat)hide=true;
      if(fam&&c.dataset.family!==fam)hide=true;
      if(sk&&c.dataset.sourceKind!==sk)hide=true;
      if(sp&&c.dataset.spreadBucket!==sp)hide=true;
      if(act&&c.dataset.actionable!=='true')hide=true;
      c.setAttribute('data-filter-hidden',hide?'true':'false');
      if(!hide)shown++;
    });
    if(countLabel)countLabel.textContent=shown+' shown';
  }

  [sevSel,catSel,famSel,skSel,spSel].forEach(el=>{if(el)el.addEventListener('change',apply)});
  if(actCheck)actCheck.addEventListener('change',apply);
})();
"""

# ---------------------------------------------------------------------------
# Dependency graph hover
# ---------------------------------------------------------------------------

_DEP_GRAPH = """\
(function initDepGraph(){
  const svg=$('.dep-graph-svg');
  if(!svg)return;
  const nodes=$$('.dep-node');
  const labels=$$('.dep-label');
  const edges=$$('.dep-edge');

  function highlight(name){
    nodes.forEach(n=>{n.style.fillOpacity=n.dataset.node===name?'1':'0.15'});
    labels.forEach(l=>{l.style.fill=l.dataset.node===name?'var(--text-primary)':'var(--text-muted)';
      l.style.fillOpacity=l.dataset.node===name?'1':'0.3'});
    edges.forEach(e=>{
      const connected=e.dataset.source===name||e.dataset.target===name;
      e.style.strokeOpacity=connected?'0.8':'0.05';
      e.style.strokeWidth=connected?'2':'1';
    });
  }

  function reset(){
    nodes.forEach(n=>{n.style.fillOpacity=''});
    labels.forEach(l=>{l.style.fill='';l.style.fillOpacity=''});
    edges.forEach(e=>{e.style.strokeOpacity='';e.style.strokeWidth=''});
  }

  [...nodes,...labels].forEach(el=>{
    el.addEventListener('mouseenter',()=>highlight(el.dataset.node));
    el.addEventListener('mouseleave',reset);
    el.style.cursor='pointer';
  });
})();
"""

# ---------------------------------------------------------------------------
# Meta panel toggle
# ---------------------------------------------------------------------------

_META_PANEL = """\
(function initProvModal(){
  const dlg=$('#prov-modal');
  if(!dlg)return;
  const openBtn=$('[data-prov-open]');
  const closeBtn=dlg.querySelector('[data-prov-close]');
  if(openBtn)openBtn.addEventListener('click',()=>dlg.showModal());
  if(closeBtn)closeBtn.addEventListener('click',()=>dlg.close());
  dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close()});
})();
(function initHelpModal(){
  const dlg=$('#help-modal');
  if(!dlg)return;
  const closeBtn=dlg.querySelector('[data-help-close]');
  const open=()=>dlg.showModal();
  if(closeBtn)closeBtn.addEventListener('click',()=>dlg.close());
  dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close()});
  document.addEventListener('keydown',e=>{
    if((e.metaKey||e.ctrlKey) && e.key === 'i'){
      e.preventDefault();
      open();
    }
  });
})();
(function initFindingWhy(){
  var dlg=$('#finding-why-modal');
  if(!dlg)return;
  var body=dlg.querySelector('.modal-body');
  var closeBtn=dlg.querySelector('[data-finding-why-close]');
  closeBtn.addEventListener('click',function(){dlg.close()});
  dlg.addEventListener('click',function(e){if(e.target===dlg)dlg.close()});
  document.addEventListener('click',function(e){
    var btn=e.target.closest('[data-finding-why-btn]');
    if(!btn)return;
    var tplId=btn.getAttribute('data-finding-why-btn');
    var tpl=document.getElementById(tplId);
    if(!tpl)return;
    body.innerHTML=tpl.innerHTML;
    dlg.showModal();
  });
})();
"""

# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

_EXPORT = """\
(function initExport(){
  const btn=$('[data-export-json]');
  if(!btn)return;
  btn.addEventListener('click',()=>{
    const meta=$('#report-meta');
    if(!meta)return;
    const d=meta.dataset;
    const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download='codeclone-report-meta.json';
    a.click();
    URL.revokeObjectURL(a.href);
    toast('Report metadata exported');
  });
})();
"""

# ---------------------------------------------------------------------------
# Command Palette (Cmd/Ctrl+K)
# ---------------------------------------------------------------------------

_CMD_PALETTE = """\
(function initCmdPalette(){
  const palette=$('.cmd-palette');
  if(!palette)return;
  const input=palette.querySelector('.cmd-palette-input');
  const list=palette.querySelector('.cmd-palette-list');
  const tabs=$$('.main-tab');

  const commands=tabs.map(t=>({
    label:t.textContent.trim(),
    action:()=>t.click(),
    key:t.dataset.tab,
    shortcut:''
  }));
  commands.push({
    label:'Toggle Theme',
    action:()=>{const b=$('.theme-toggle');if(b)b.click()},
    key:'theme',
    shortcut:''
  });
  commands.push({
    label:'Open Help',
    action:()=>{
      const dlg=$('#help-modal');
      if(dlg)dlg.showModal();
    },
    key:'help',
    shortcut:'mod+I'
  });
  commands.push({
    label:'Export Report',
    action:()=>{window.print();},
    key:'print',
    shortcut:''
  });
  commands.push({
    label:'Export JSON',
    action:()=>{const b=$('[data-export-json]');if(b)b.click()},
    key:'export',
    shortcut:''
  });
  commands.push({
    label:'Collapse All',
    action:()=>{$$('[data-collapse-all]').forEach(b=>b.click())},
    key:'collapse',
    shortcut:''
  });
  commands.push({
    label:'Expand All',
    action:()=>{$$('[data-expand-all]').forEach(b=>b.click())},
    key:'expand',
    shortcut:''
  });

  let activeIdx=0;

  function render(q){
    const filtered=commands.filter(c=>c.label.toLowerCase().includes(q.toLowerCase()));
    activeIdx=0;
    list.innerHTML=filtered.map((c,i)=>
      '<div class="cmd-palette-item'+(i===0?' active':'')+'" data-cmd="'+i+'">'
      +c.label+'<kbd>'+(c.shortcut||c.key)+'</kbd></div>').join('');
    list.querySelectorAll('.cmd-palette-item').forEach((el,i)=>{
      el.addEventListener('click',()=>{filtered[i].action();close()});
      el.addEventListener('mouseenter',()=>{
        list.querySelectorAll('.cmd-palette-item').forEach(e=>e.classList.remove('active'));
        el.classList.add('active');activeIdx=i});
    });
    return filtered;
  }

  function open(){palette.classList.add('open');input.value='';render('');input.focus()}
  function close(){palette.classList.remove('open')}

  document.addEventListener('keydown',e=>{
    if((e.metaKey||e.ctrlKey) && e.key === 'k'){e.preventDefault();
      palette.classList.contains('open')?close():open();return}
    if(!palette.classList.contains('open'))return;
    if(e.key==='Escape'){close();return}
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      e.preventDefault();
      const items=list.querySelectorAll('.cmd-palette-item');
      if(!items.length)return;
      items[activeIdx]?.classList.remove('active');
      activeIdx=e.key==='ArrowDown'?(activeIdx+1)%items.length:(activeIdx-1+items.length)%items.length;
      items[activeIdx]?.classList.add('active');
      items[activeIdx]?.scrollIntoView({block:'nearest'});return}
    if(e.key==='Enter'){
      const items=list.querySelectorAll('.cmd-palette-item');
      if(items[activeIdx])items[activeIdx].click();return}
  });

  input?.addEventListener('input',()=>render(input.value));
  palette.addEventListener('click',e=>{if(e.target===palette)close()});
})();
"""

# ---------------------------------------------------------------------------
# Table sort
# ---------------------------------------------------------------------------

_TABLE_SORT = """\
(function initTableSort(){
  $$('.table th[data-sortable]').forEach(th=>{
    th.addEventListener('click',()=>{
      const table=th.closest('.table');
      if(!table)return;
      const idx=[...th.parentElement.children].indexOf(th);
      const tbody=table.querySelector('tbody')||table;
      const rows=[...tbody.querySelectorAll('tr')].filter(r=>r.querySelector('td'));
      const cur=th.getAttribute('aria-sort');
      const dir=cur==='ascending'?'descending':'ascending';
      // Reset siblings
      [...th.parentElement.children].forEach(s=>{s.removeAttribute('aria-sort')});
      th.setAttribute('aria-sort',dir);

      rows.sort((a,b)=>{
        const at=(a.children[idx]?.textContent||'').trim();
        const bt=(b.children[idx]?.textContent||'').trim();
        const an=parseFloat(at),bn=parseFloat(bt);
        const cmp=(!isNaN(an)&&!isNaN(bn))?an-bn:at.localeCompare(bt);
        return dir==='ascending'?cmp:-cmp;
      });
      rows.forEach(r=>tbody.appendChild(r));
    });
  });
})();
"""

# ---------------------------------------------------------------------------
# Toast
# ---------------------------------------------------------------------------

_TOAST = """\
function toast(msg){
  let c=$('.toast-container');
  if(!c){c=document.createElement('div');c.className='toast-container';document.body.appendChild(c)}
  const t=document.createElement('div');t.className='toast';t.textContent=msg;
  c.appendChild(t);
  setTimeout(()=>{t.style.opacity='0';t.style.transform='translateY(8px)';
    setTimeout(()=>t.remove(),300)},3000);
}
"""

# ---------------------------------------------------------------------------
# Lazy highlight (IntersectionObserver for code snippets)
# ---------------------------------------------------------------------------

_SCOPE_COUNTERS = """\
function updateCloneScopeCounters(){
  const sections=['functions','blocks','segments'];
  let total=0;
  sections.forEach(id=>{
    const sec=document.querySelector('[data-section="'+id+'"]');
    if(!sec)return;
    const vis=[...sec.querySelectorAll('.group[data-group="'+id+'"]')]
      .filter(g=>g.style.display!=='none'&&g.getAttribute('data-novelty-hidden')!=='true');
    total+=vis.length;
    const tabCount=document.querySelector('[data-clone-tab-count="'+id+'"]');
    if(tabCount){tabCount.textContent=vis.length;tabCount.dataset.totalGroups=vis.length}
  });
  const mainBtn=document.querySelector('[data-main-clones-count]');
  if(mainBtn)mainBtn.setAttribute('data-main-clones-count',total);
}
"""

_LAZY_HIGHLIGHT = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_ALL_MODULES = (
    _CORE,
    _TOAST,
    _THEME,
    _TABS,
    _SUB_TABS,
    _SECTIONS,
    _NOVELTY,
    _MODALS,
    _SUGGESTIONS,
    _DEP_GRAPH,
    _META_PANEL,
    _EXPORT,
    _CMD_PALETTE,
    _TABLE_SORT,
    _SCOPE_COUNTERS,
    _LAZY_HIGHLIGHT,
)


def build_js() -> str:
    """Return the complete JS string for the HTML report, wrapped in an IIFE."""
    body = "\n".join(_ALL_MODULES)
    return f"(function(){{\n'use strict';\n{body}\n}})();\n"

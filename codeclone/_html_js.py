# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
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
    const has=root.getAttribute('data-theme');
    const isDark=has?has==='dark'
      :matchMedia('(prefers-color-scheme:light)').matches?false:true;
    const next=isDark?'light':'dark';
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
(function initBadgeModal(){
  const dlg=$('#badge-modal');
  if(!dlg)return;

  /* --- state --- */
  var _grade='',_score=0,_variant='grade';

  /* --- grade→shields color (canonical bands) --- */
  function badgeColor(g){
    return g==='A'?'brightgreen':g==='B'?'green':g==='C'?'yellow':g==='D'?'orange':'red'}

  /* --- build shield URLs & embed codes for current variant --- */
  function render(){
    var label,alt,url;
    if(_variant==='full'){
      label=_score+' ('+_grade+')';alt='codeclone '+_score+' ('+_grade+')';
    }else{
      label='grade '+_grade;alt='codeclone grade '+_grade;}
    url='https://img.shields.io/badge/codeclone-'
      +encodeURIComponent(label).replace(/-/g,'--')+'-'+badgeColor(_grade);
    var prev=dlg.querySelector('#badge-preview');
    if(prev)prev.innerHTML='<img src="'+url+'" alt="'+alt+'">';
    var md=dlg.querySelector('#badge-code-md');
    if(md)md.textContent='!['+alt+']('+url+')';
    var ht=dlg.querySelector('#badge-code-html');
    if(ht)ht.textContent='<img src="'+url+'" alt="'+alt+'">';}

  /* --- tabs --- */
  dlg.querySelectorAll('[data-badge-tab]').forEach(function(tab){
    tab.addEventListener('click',function(){
      dlg.querySelectorAll('[data-badge-tab]').forEach(function(t){
        t.classList.remove('badge-tab--active');t.setAttribute('aria-selected','false')});
      tab.classList.add('badge-tab--active');tab.setAttribute('aria-selected','true');
      _variant=tab.dataset.badgeTab;render();});});

  /* --- open --- */
  document.addEventListener('click',function(e){
    var btn=e.target.closest('[data-badge-open]');
    if(!btn)return;
    _grade=btn.dataset.badgeGrade||'';
    _score=parseInt(btn.dataset.badgeScore||'0',10);
    _variant='grade';
    dlg.querySelectorAll('[data-badge-tab]').forEach(function(t){
      var active=t.dataset.badgeTab==='grade';
      t.classList.toggle('badge-tab--active',active);
      t.setAttribute('aria-selected',active?'true':'false');});
    render();dlg.showModal();
    var fc=dlg.querySelector('[data-badge-close]');if(fc)fc.focus();});

  /* --- close --- */
  var closeBtn=dlg.querySelector('[data-badge-close]');
  if(closeBtn)closeBtn.addEventListener('click',function(){dlg.close()});
  dlg.addEventListener('click',function(e){if(e.target===dlg)dlg.close()});

  /* --- copy with feedback --- */
  dlg.addEventListener('click',function(e){
    var copyBtn=e.target.closest('[data-badge-copy]');
    if(!copyBtn)return;
    var which=copyBtn.dataset.badgeCopy;
    var code=dlg.querySelector('#badge-code-'+which);
    if(!code)return;
    navigator.clipboard.writeText(code.textContent).then(function(){
      copyBtn.textContent='\u2713 Copied';copyBtn.classList.add('badge-copy-btn--ok');
      setTimeout(function(){copyBtn.textContent='Copy';
        copyBtn.classList.remove('badge-copy-btn--ok')},1500);});});
})();
(function initProvModal(){
  const dlg=$('#prov-modal');
  if(!dlg)return;
  const openBtn=$('[data-prov-open]');
  const closeBtn=dlg.querySelector('[data-prov-close]');
  if(openBtn)openBtn.addEventListener('click',()=>dlg.showModal());
  if(closeBtn)closeBtn.addEventListener('click',()=>dlg.close());
  dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close()});
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

_EXPORT = ""  # removed: Export JSON button eliminated from topbar

# ---------------------------------------------------------------------------
# Command Palette (Cmd/Ctrl+K)
# ---------------------------------------------------------------------------

_CMD_PALETTE = ""  # removed: command palette eliminated

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
# IDE links
# ---------------------------------------------------------------------------

_IDE_LINKS = r"""
(function initIdeLinks(){
  const KEY='codeclone-ide';
  const root=document.documentElement;
  var scanRoot=root.getAttribute('data-scan-root')||'';
  var projectName=scanRoot.replace(/\/$/,'').split('/').pop()||'';

  function relPath(abs){
    var r=scanRoot.replace(/\/$/,'')+'/';
    if(abs.indexOf(r)===0)return abs.substring(r.length);
    return abs;
  }

  const SCHEMES={
    pycharm:{label:'PyCharm',
      url:function(f,l){return 'jetbrains://pycharm/navigate/reference?project='+encodeURIComponent(projectName)+'&path='+encodeURIComponent(relPath(f))+':'+l}},
    idea:{label:'IntelliJ IDEA',
      url:function(f,l){return 'jetbrains://idea/navigate/reference?project='+encodeURIComponent(projectName)+'&path='+encodeURIComponent(relPath(f))+':'+l}},
    vscode:{label:'VS Code',
      url:function(f,l){return 'vscode://file'+f+':'+l}},
    cursor:{label:'Cursor',
      url:function(f,l){return 'cursor://file'+f+':'+l}},
    fleet:{label:'Fleet',
      url:function(f,l){return 'fleet://open?file='+encodeURIComponent(f)+'&line='+l}},
    zed:{label:'Zed',
      url:function(f,l){return 'zed://file'+f+':'+l}},
    '': {label:'None',url:null}
  };

  var current=localStorage.getItem(KEY)||'';
  root.setAttribute('data-ide',current);

  const btn=$('.ide-picker-btn');
  const menu=$('.ide-menu');
  const label=$('.ide-picker-label');
  if(!btn||!menu)return;

  function updateLabel(){
    if(!label)return;
    var s=SCHEMES[current];
    label.textContent=s&&current?s.label:'IDE';
  }

  function setChecked(){
    menu.querySelectorAll('button').forEach(function(b){
      b.setAttribute('aria-checked',b.dataset.ide===current?'true':'false');
    });
  }

  function applyHrefs(){
    var s=SCHEMES[current];
    $$('.ide-link[data-file]').forEach(function(a){
      if(!current||!s||!s.url){a.removeAttribute('href');return}
      var f=a.getAttribute('data-file'),l=a.getAttribute('data-line')||'1';
      if(!f)return;
      a.setAttribute('href',s.url(f,l));
    });
  }

  setChecked();
  updateLabel();
  applyHrefs();

  // Reapply hrefs when new content becomes visible (tab switch)
  var mo=new MutationObserver(function(){applyHrefs()});
  document.querySelectorAll('.tab-panel').forEach(function(p){
    mo.observe(p,{attributes:true,attributeFilter:['class']});
  });

  btn.addEventListener('click',function(e){
    e.stopPropagation();
    var open=menu.hasAttribute('data-open');
    if(open){menu.removeAttribute('data-open');btn.setAttribute('aria-expanded','false')}
    else{menu.setAttribute('data-open','');btn.setAttribute('aria-expanded','true')}
  });

  document.addEventListener('click',function(){
    menu.removeAttribute('data-open');btn.setAttribute('aria-expanded','false');
  });

  menu.addEventListener('click',function(e){
    e.stopPropagation();
    var b=e.target.closest('button[data-ide]');
    if(!b)return;
    current=b.dataset.ide;
    localStorage.setItem(KEY,current);
    root.setAttribute('data-ide',current);
    setChecked();
    updateLabel();
    applyHrefs();
    menu.removeAttribute('data-open');btn.setAttribute('aria-expanded','false');
  });

})();
"""

# ---------------------------------------------------------------------------
# Tooltips (fixed-position, escapes overflow containers)
# ---------------------------------------------------------------------------

_TOOLTIPS = """\
(function initTooltips(){
  let tip=null;
  function show(e){
    const el=e.target;
    const text=el.getAttribute('data-tip');
    if(!text)return;
    tip=document.createElement('div');
    tip.className='kpi-tooltip';
    tip.textContent=text;
    document.body.appendChild(tip);
    const r=el.getBoundingClientRect();
    const tw=tip.offsetWidth;
    const th=tip.offsetHeight;
    let left=r.left+r.width/2-tw/2;
    let top=r.bottom+6;
    if(left<4)left=4;
    if(left+tw>window.innerWidth-4)left=window.innerWidth-tw-4;
    if(top+th>window.innerHeight-4){top=r.top-th-6}
    tip.style.left=left+'px';
    tip.style.top=top+'px';
  }
  function hide(){if(tip){tip.remove();tip=null}}
  document.addEventListener('mouseenter',function(e){
    if(e.target.matches('.kpi-help[data-tip]'))show(e);
  },true);
  document.addEventListener('mouseleave',function(e){
    if(e.target.matches('.kpi-help[data-tip]'))hide();
  },true);
})();
"""

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
    _IDE_LINKS,
    _TOOLTIPS,
)


def build_js() -> str:
    """Return the complete JS string for the HTML report, wrapped in an IIFE."""
    body = "\n".join(_ALL_MODULES)
    return f"(function(){{\n'use strict';\n{body}\n}})();\n"

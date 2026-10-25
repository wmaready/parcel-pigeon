/* Market map explorer: every player, every connection, one clean picture.
   Reads PLAYERS / PEDGES / REALMS from the main page; refreshes when live data adds players. */
(function(){
'use strict';
if(typeof PLAYERS==='undefined'||typeof PEDGES==='undefined'||typeof REALMS==='undefined')return;
const assetBase=new URL('./',document.currentScript?.src||document.baseURI);
const host=document.querySelector('#s-mna .view[data-view="map"]');if(!host)return;
const COL={national:'#5B8DEF',regional:'#F28DB2',gig:'#FF9B42',retail:'#FF9900',
  '3pl':'#2EC4B6',global:'#FFCC00',software:'#A57BE0',cold:'#4CC9F0',auto:'#9BE15D',capital:'#B9875A',consultancy:'#FF6F91'};
const KIND={owns:'own',acquired:'own',merged:'own',spun:'own',sold:'own',invested:'inv',partner:'part'};
const RANK={owns:0,acquired:1,merged:2,spun:3,sold:4,invested:5,partner:6};
const VERB={owns:'Owns',acquired:'Bought',merged:'Merged with',spun:'Spun off',sold:'Sold',invested:'Invested in',partner:'Partners with'};
const VERB_IN={owns:'Owned by',acquired:'Bought by',merged:'Merged with',spun:'Spun off from',sold:'Sold by',invested:'Backed by',partner:'Partners with'};
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const OWN={public:'Public',private:'Private',sub:'Subsidiary',pe:'Private equity',gov:'Government',pending:'Going public'};
const safeUrl=u=>/^https?:\/\//i.test(u||'')?u:null;
// a curated record (company-foundation.js) lists every source it was checked against and the date it was checked
const foundSrc=p=>{const L=[...new Set([...(p.srcs||[]),p.src].map(safeUrl).filter(Boolean))],host=u=>{try{const x=new URL(u);return (x.hostname.replace(/^www\./,'')+x.pathname).replace(/\/$/,'')}catch(e){return 'source'}};
  const d=p.chk&&(typeof fmtD==='function'?fmtD(String(p.chk),{month:'short',day:'numeric',year:'numeric'}):String(p.chk));
  return `<div class="mx-sec mx-found">${L.map(u=>`<a class="mx-src" href="${esc(u)}" target="_blank" rel="noopener noreferrer">Source: ${esc(host(u))} ↗</a>`).join(' ')}${d?`<p class="mx-empty">Record checked ${esc(d)}</p>`:''}</div>`};

let N=[],E=[],byId={},sig='',sel=null,filt=new Set(REALMS.map(r=>r[0])),T={x:0,y:0,k:1},W=0,H=0,laidOut=false;

/* ---- data: unique players, one connection per pair ---- */
function build(){
  const seen=new Map();N=[];byId={};
  PLAYERS.forEach(p=>{
    if(!p||!p.id||!COL[p.realm])return;
    const keys=[p.n,...(p.al||[])].map(x=>String(x).trim().toLowerCase()).filter(Boolean);
    const dup=keys.map(k=>seen.get(k)).find(Boolean);
    if(dup&&byId[dup]){byId[p.id]=byId[dup];return}
    const n={id:p.id,p,deg:0,x:0,y:0,vx:0,vy:0,links:[]};N.push(n);byId[p.id]=n;
    keys.forEach(k=>{if(!seen.has(k))seen.set(k,p.id)});
  });
  const pair=new Map();
  const add=(a,b,k,e)=>{const A=byId[a],B=byId[b];if(!A||!B||A===B)return;
    const key=[A.id,B.id].sort().join('|');let x=pair.get(key);
    if(!x){x={a:A,b:B,k,hist:[]};pair.set(key,x)}
    else if(RANK[k]<RANK[x.k]){x.k=k;x.a=A;x.b=B}
    if(e&&!x.hist.some(h=>h.k===e.k&&h.y===e.y))x.hist.push(e)};
  PEDGES.forEach(e=>{if(e&&RANK[e.k]!=null)add(e.a,e.b,e.k,e)});
  PLAYERS.forEach(p=>{if(p&&p.parent)add(p.parent,p.id,'owns',null)});
  E=[...pair.values()];
  E.forEach(e=>{e.a.deg++;e.b.deg++;e.a.links.push(e);e.b.links.push(e)});
  const ranked=[...N].sort((a,b)=>b.deg-a.deg);
  ranked.forEach((n,i)=>n.tier=i<18?1:i<70?2:3);
  N.forEach(n=>n.r=4+Math.sqrt(n.deg)*2.4);
}

/* ---- layout: sectors around a ring, force pass to untangle ---- */
function layout(){
  const R=REALMS.map(r=>r[0]),C={};
  R.forEach((k,i)=>{const a=i/R.length*Math.PI*2-Math.PI/2;C[k]={x:Math.cos(a)*520,y:Math.sin(a)*520}});
  let seed=7;const rnd=()=>(seed=(seed*16807)%2147483647)/2147483647;
  N.forEach(n=>{const c=C[n.p.realm];n.x=c.x+(rnd()-.5)*220;n.y=c.y+(rnd()-.5)*220;n.vx=n.vy=0});
  for(let it=0;it<260;it++){
    const t=1-it/260;
    for(let i=0;i<N.length;i++){const a=N[i];
      for(let j=i+1;j<N.length;j++){const b=N[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1;
        if(d2>90000)continue;const f=1600/d2;dx*=f;dy*=f;a.vx+=dx;a.vy+=dy;b.vx-=dx;b.vy-=dy}}
    E.forEach(e=>{const dx=e.b.x-e.a.x,dy=e.b.y-e.a.y,d=Math.hypot(dx,dy)||1,f=(d-70)*0.012;
      const fx=dx/d*f,fy=dy/d*f;e.a.vx+=fx;e.a.vy+=fy;e.b.vx-=fx;e.b.vy-=fy});
    N.forEach(n=>{const c=C[n.p.realm];n.vx+=(c.x-n.x)*0.02;n.vy+=(c.y-n.y)*0.02;
      const v=Math.hypot(n.vx,n.vy),m=30*t+2;if(v>m){n.vx*=m/v;n.vy*=m/v}
      n.x+=n.vx;n.y+=n.vy;n.vx*=.55;n.vy*=.55});
  }
  laidOut=true;
}

/* ---- markup ---- */
const wrap=document.createElement('div');wrap.className='mx';
wrap.innerHTML=`<div class="mx-top">
  <div class="mx-search"><svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input id="mxQ" type="search" placeholder="Find a company, old name, or owner" autocomplete="off" aria-label="Search the market map"><div class="mx-sugg" id="mxSugg" hidden></div></div>
  <div class="mx-mode" role="group" aria-label="Map view"><button data-m="geo" aria-pressed="true">Map</button><button data-m="home" aria-pressed="false">Sectors</button></div>
</div>
<div class="mx-stats" id="mxStats"></div>
<details class="mx-filters"><summary id="mxFilterLabel">Sectors · All</summary><div class="mx-chips" id="mxChips" role="group" aria-label="Show sectors"></div></details>
<nav class="mx-crumb" id="mxCrumb" aria-label="Where you are"></nav><div class="mx-geo" id="mxGeoWrap"><p class="mx-gcov" id="mxGcov"></p><div class="mx-gmap" id="mxGeo"></div><div class="mx-gnote" id="mxGnote"></div></div><div class="mx-home" id="mxHome"></div><div class="mx-sect" id="mxSect"></div><div class="mx-co" id="mxCo"></div>
<div class="mx-body">
  <div class="mx-stage" id="mxStage">
    <svg id="mxSvg" role="img" aria-label="Network of parcel market players"><g class="mx-g z1" id="mxG"><g id="mxE"></g><g id="mxN"></g></g></svg>
    <div class="mx-key"><span><svg viewBox="0 0 22 6"><path d="M0 3H22" stroke="#8D99A6" stroke-width="1.5"/></svg>Owns / bought</span><span><svg viewBox="0 0 22 6"><path d="M0 3H22" stroke="#8D99A6" stroke-width="1.5" stroke-dasharray="4 3"/></svg>Invested</span><span><svg viewBox="0 0 22 6"><path d="M0 3H22" stroke="#8D99A6" stroke-width="1.5" stroke-dasharray="1 3" stroke-linecap="round"/></svg>Partners</span></div>
    <div class="mx-hint" id="mxHint">Drag to move · pinch or scroll to zoom · tap a dot</div>
    <div class="mx-zoom"><button data-z="1.4" aria-label="Zoom in">+</button><button data-z="0.7" aria-label="Zoom out">&minus;</button><button data-z="0" aria-label="Show everything">&#8634;</button></div>
  </div>
  <aside class="mx-side" id="mxSide" aria-live="polite"></aside>
</div>
<div class="mx-list" id="mxList"></div>`;
host.prepend(wrap);
const $=id=>document.getElementById(id);
const stage=$('mxStage'),svg=$('mxSvg'),G=$('mxG'),side=$('mxSide');

function draw(){
  $('mxE').innerHTML=E.map((e,i)=>`<line class="mx-e k-${KIND[e.k]}" data-i="${i}" x1="${e.a.x.toFixed(1)}" y1="${e.a.y.toFixed(1)}" x2="${e.b.x.toFixed(1)}" y2="${e.b.y.toFixed(1)}"/>`).join('');
  $('mxN').innerHTML=N.map(n=>`<g class="mx-n t${n.tier}" data-id="${esc(n.id)}" transform="translate(${n.x.toFixed(1)},${n.y.toFixed(1)})"><circle r="${n.r.toFixed(1)}" fill="${COL[n.p.realm]}"/><text x="${(n.r+4).toFixed(1)}" y="4" font-size="${n.tier===1?14:11}">${esc(n.p.n)}</text></g>`).join('');
  applyFilter();
}
function counts(){const c={};N.forEach(n=>c[n.p.realm]=(c[n.p.realm]||0)+1);return c}
function chips(){const c=counts();
  const all=filt.size===REALMS.length;
  $('mxFilterLabel').textContent=all?'Sectors · All':filt.size===1?'Sectors · '+(RL[[...filt][0]]||[...filt][0]):'Sectors · '+filt.size+' selected';
  $('mxChips').innerHTML=`<button class="mx-chip" data-r="*" aria-pressed="${all}">All sectors</button>`+REALMS.map(([k,l])=>`<button class="mx-chip" data-r="${k}" style="--c:${COL[k]}" aria-pressed="${filt.has(k)}"><i></i>${esc(l)} <em>${c[k]||0}</em></button>`).join('');}
function stats(){const own=E.filter(e=>KIND[e.k]==='own').length;
  $('mxStats').innerHTML=`<b>${N.length}</b> companies · <b>${E.length}</b> connections · <b>${own}</b> ownership links · <b>${REALMS.length}</b> sectors`;}

function applyFilter(){
  const on=id=>filt.has(byId[id].p.realm);
  $('mxN').querySelectorAll('.mx-n').forEach(g=>g.classList.toggle('off',!on(g.dataset.id)));
  $('mxE').querySelectorAll('.mx-e').forEach(l=>{const e=E[l.dataset.i];l.classList.toggle('off',!(filt.has(e.a.p.realm)&&filt.has(e.b.p.realm)))});
  if(wrap.classList.contains('list'))list();
}

/* ---- view transform ---- */
function apply(){G.setAttribute('transform',`translate(${T.x},${T.y}) scale(${T.k})`);
  G.classList.remove('z1','z2','z3');G.classList.add(T.k<0.8?'z1':T.k<1.6?'z2':'z3');G.style.setProperty('--fs',(12/T.k).toFixed(2)+'px');G.style.setProperty('--fs1',(14/T.k).toFixed(2)+'px');}
function size(){const r=stage.getBoundingClientRect();W=r.width;H=r.height}
function fit(nodes){size();if(!W||!H)return;const L=(nodes&&nodes.length?nodes:N.filter(n=>filt.has(n.p.realm)));if(!L.length)return;
  let x0,y0,x1,y1;if(nodes&&nodes.length){x0=y0=1e9;x1=y1=-1e9;L.forEach(n=>{x0=Math.min(x0,n.x-n.r);y0=Math.min(y0,n.y-n.r);x1=Math.max(x1,n.x+n.r);y1=Math.max(y1,n.y+n.r)})}else{const xs=L.map(n=>n.x).sort((a,b)=>a-b),ys=L.map(n=>n.y).sort((a,b)=>a-b),q=f=>Math.floor((L.length-1)*f);x0=xs[q(.04)];x1=xs[q(.96)];y0=ys[q(.04)];y1=ys[q(.96)]}
  const pad=nodes&&nodes.length?80:30,k=Math.min(3,Math.max(0.15,Math.min((W-pad*2)/(x1-x0||1),(H-pad*2)/(y1-y0||1))));
  T={k,x:W/2-(x0+x1)/2*k,y:H/2-(y0+y1)/2*k};apply();}
function zoomAt(f,px,py){const k=Math.min(6,Math.max(0.12,T.k*f));const q=k/T.k;T={k,x:px-(px-T.x)*q,y:py-(py-T.y)*q};apply();}

stage.addEventListener('wheel',e=>{e.preventDefault();const dy=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?100:1);
  const r=stage.getBoundingClientRect();zoomAt(Math.exp(-dy*0.0018),e.clientX-r.left,e.clientY-r.top)},{passive:false});
const ptr=new Map();let drag=null,moved=0,pinch=null;
stage.addEventListener('pointerdown',e=>{if(e.target.closest('.mx-zoom'))return;stage.setPointerCapture(e.pointerId);ptr.set(e.pointerId,{x:e.clientX,y:e.clientY});
  moved=0;drag={x:e.clientX,y:e.clientY,tx:T.x,ty:T.y,target:e.target};
  if(ptr.size===2){const [a,b]=[...ptr.values()];pinch={d:Math.hypot(a.x-b.x,a.y-b.y),k:T.k}}});
stage.addEventListener('pointermove',e=>{if(!ptr.has(e.pointerId))return;ptr.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if(ptr.size===2&&pinch){const [a,b]=[...ptr.values()],r=stage.getBoundingClientRect(),d=Math.hypot(a.x-b.x,a.y-b.y);
    zoomAt(pinch.k*d/pinch.d/T.k,(a.x+b.x)/2-r.left,(a.y+b.y)/2-r.top);moved=99;return}
  if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;moved=Math.max(moved,Math.hypot(dx,dy));
  if(moved>5){stage.classList.add('drag');T.x=drag.tx+dx;T.y=drag.ty+dy;apply()}});
const up=e=>{if(!ptr.has(e.pointerId))return;ptr.delete(e.pointerId);if(ptr.size<2)pinch=null;
  if(ptr.size===0){stage.classList.remove('drag');
    if(drag&&moved<=5){const g=drag.target.closest&&drag.target.closest('.mx-n');if(g)select(g.dataset.id);else if(e.type==='pointerup')select(null)}
    drag=null}
  else{const [p]=[...ptr.values()];drag={x:p.x,y:p.y,tx:T.x,ty:T.y,target:stage};}};
stage.addEventListener('pointerup',up);stage.addEventListener('pointercancel',up);
wrap.querySelector('.mx-zoom').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const z=+b.dataset.z;
  if(!z){select(null);fit();return}size();zoomAt(z,W/2,H/2)});

/* ---- selection ---- */
function rel(n){const out={up:[],down:[],inv:[],invBy:[],part:[],deal:[]};
  n.links.forEach(e=>{const o=e.a===n?e.b:e.a,from=e.a===n,k=e.k,yr=(e.hist.find(h=>h.y)||{}).y||'';
    const item={o,k,yr,e};
    if(KIND[k]==='part')out.part.push(item);
    else if(k==='invested')(from?out.inv:out.invBy).push(item);
    else if(k==='owns'||k==='acquired')(from?out.down:out.up).push(item);
    else out.deal.push({...item,from});});
  Object.values(out).forEach(a=>a.sort((x,y)=>y.o.deg-x.o.deg||x.o.p.n.localeCompare(y.o.p.n)));return out;}
const LG=(p,c)=>typeof logoOrMono==='function'?logoOrMono(p,c):'';
function linkBtn(it,label){return `<button class="mx-link" data-go="${esc(it.o.id)}" style="--c:${COL[it.o.p.realm]}">${LG(it.o.p,'lgs')}${esc(it.o.p.n)}<small>${esc(label||'')}${it.yr?(label?' · ':'')+esc(it.yr):''}</small></button>`}
function sec(t,a,lab){if(!a.length)return '';const L=a.slice(0,40);return `<div class="mx-sec"><h4>${t} (${a.length})</h4>${L.map(it=>linkBtn(it,typeof lab==='function'?lab(it):lab)).join('')}${a.length>40?`<div class="mx-empty">+${a.length-40} more</div>`:''}</div>`}
function panel(){
  if(!sel){const hubs=[...N].filter(n=>filt.has(n.p.realm)).sort((a,b)=>b.deg-a.deg).slice(0,8);
    side.innerHTML=`<h3>The parcel market</h3><div class="mx-sub">Every carrier, platform, warehouse and investor we track, and how they connect.</div>
    <p class="mx-empty">Bigger dots have more connections. Tap any dot, or search above, to see who owns it, what it bought, and who it works with.</p>
    <div class="mx-sec mx-hubs"><h4>Most connected</h4>${hubs.map(o=>linkBtn({o,yr:''},o.deg+' links')).join('')}</div>`;
    side.classList.remove('open');return}
  const n=sel,p=n.p,r=rel(n),url=safeUrl(p.src);
  const former=(p.al||[]).filter(a=>a&&a.toLowerCase()!==p.n.toLowerCase());
  side.innerHTML=`<button class="mx-x" aria-label="Close">&times;</button><h3 class="mx-hl">${LG(p,'mx-big')}<span>${esc(p.n)}</span></h3>
  <div class="mx-sub">${[p.hq,p.yr?'since '+p.yr:''].filter(Boolean).map(esc).join(' · ')}</div>
  <div><span class="mx-tag" style="--c:${COL[p.realm]}"><i></i>${esc(RL[p.realm]||p.realm)}</span><span class="mx-tag">${esc(OWN[p.own]||p.own||'')}${p.tk?' · '+esc(p.tk):''}</span></div>
  ${p.s?`<p>${esc(p.s)}</p>`:''}
  ${p.vet?`<div class="pvet"><b>Record check</b><p>${esc(p.vet)}</p></div>`:''}
  ${p.hist&&p.hist.length?`<details class="mx-sec phist"><summary><h4 style="display:inline">History · ${p.hist.length}</h4></summary><ol>${p.hist.map(h=>`<li><span class="mono">${esc(h.y)}</span>${esc(h.t)}</li>`).join('')}</ol></details>`:''}
  ${former.length?`<div class="mx-sec"><h4>Also known as</h4><div class="mx-empty">${former.map(esc).join(' · ')}</div></div>`:''}
  <!--rel-->${sec('Owned by',r.up,it=>it.k==='acquired'?'bought it':'')}
  ${sec('Owns',r.down,it=>it.k==='acquired'?'bought':'')}
  ${sec('Other deals',r.deal,it=>it.from?VERB[it.k]:VERB_IN[it.k])}
  ${sec('Backed by',r.invBy,'')}
  ${sec('Invested in',r.inv,'')}
  ${sec('Partners',r.part,'')}
  ${!n.links.length?'<p class="mx-empty">No connections tracked yet.</p>':''}
  ${p.foundation?foundSrc(p):url?`<div class="mx-sec"><a class="mx-src" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Source ↗</a></div>`:''}`;
  side.classList.add('open');side.scrollTop=0;
}
function detailOf(n){const s0=sel;sel=n;panel();const h=side.innerHTML;sel=s0;panel();return h.replace('<button class="mx-x" aria-label="Close">&times;</button>','')}
function select(id,zoom){
  if(id&&curM!=='graph'){openCo(id);return}
  sel=id?byId[id]||null:null;
  if(sel&&!filt.has(sel.p.realm)){filt.add(sel.p.realm);chips();applyFilter()}
  G.classList.toggle('focus',!!sel);
  const on=new Set();if(sel){on.add(sel.id);sel.links.forEach(e=>{on.add(e.a.id);on.add(e.b.id)})}
  $('mxN').querySelectorAll('.mx-n').forEach(g=>{g.classList.toggle('on',on.has(g.dataset.id));g.classList.toggle('sel',!!sel&&g.dataset.id===sel.id)});
  $('mxE').querySelectorAll('.mx-e').forEach(l=>{const e=E[l.dataset.i];l.classList.toggle('on',!!sel&&(e.a===sel||e.b===sel))});
  panel();
  if(sel&&zoom)fit([...on].map(i=>byId[i]));
}
side.addEventListener('click',e=>{const g=e.target.closest('[data-go]');if(g){select(g.dataset.go,true);return}
  if(e.target.closest('.mx-x'))select(null)});

/* ---- search ---- */
const q=$('mxQ'),sugg=$('mxSugg');
function matches(t){t=t.trim().toLowerCase();if(!t)return [];
  if(window.ppCompanySearch){const seen=new Set();return window.ppCompanySearch(t,N.map(n=>n.p),PEDGES,RL).map(x=>byId[x.p.id]).filter(n=>n&&!seen.has(n.id)&&seen.add(n.id))}
  return N.map(n=>{const names=[n.p.n,...(n.p.al||[])].map(x=>String(x).toLowerCase());
    const s=names.some(x=>x.startsWith(t))?0:names.some(x=>x.includes(t))?1:(n.p.hq||'').toLowerCase().includes(t)?2:9;
    return {n,s}}).filter(x=>x.s<9).sort((a,b)=>a.s-b.s||b.n.deg-a.n.deg).map(x=>x.n);}
q.addEventListener('input',()=>{const L=matches(q.value);
  G.classList.toggle('search',!!q.value.trim()&&!sel);const hit=new Set(L.map(n=>n.id));
  $('mxN').querySelectorAll('.mx-n').forEach(g=>g.classList.toggle('hit',hit.has(g.dataset.id)));
  if(!L.length){sugg.hidden=!q.value.trim();sugg.innerHTML=q.value.trim()?(window.ppReqBtn?window.ppReqBtn(q.value.trim()):'<button disabled>No match</button>'):'';return}
  sugg.hidden=false;sugg.innerHTML=L.slice(0,7).map(n=>{const t=q.value.trim().toLowerCase(),al=(n.p.al||[]).find(a=>a.toLowerCase().includes(t)&&!n.p.n.toLowerCase().includes(t));
    return `<button data-go="${esc(n.id)}"><span>${esc(n.p.n)}${al?` <small style="margin:0">(was ${esc(al)})</small>`:''}</span><small>${esc(RL[n.p.realm]||'')}</small></button>`}).join('');
  if(wrap.classList.contains('list'))list();});
q.addEventListener('keydown',e=>{if(e.key==='Enter'){const b=sugg.querySelector('[data-go]');if(b)b.click()}if(e.key==='Escape'){q.value='';q.dispatchEvent(new Event('input'))}});
sugg.addEventListener('click',e=>{const b=e.target.closest('[data-go]');if(!b)return;sugg.hidden=true;q.value='';G.classList.remove('search');
  openCo(b.dataset.go)});
document.addEventListener('click',e=>{if(!e.target.closest('.mx-search'))sugg.hidden=true});

$('mxChips').addEventListener('click',e=>{const b=e.target.closest('[data-r]');if(!b)return;const r=b.dataset.r;
  if(r==='*')filt=new Set(REALMS.map(x=>x[0]));
  else if(filt.size===REALMS.length)filt=new Set([r]);
  else{filt.has(r)?filt.delete(r):filt.add(r);if(!filt.size)filt=new Set(REALMS.map(x=>x[0]))}
  chips();applyFilter();if(sel&&!filt.has(sel.p.realm))select(null);else panel();if(curM==='geo')drawGeo();else fit()});

/* ---- list view: families grouped by sector ---- */
function list(){
  const t=q.value.trim(),hit=t?new Set(matches(t).map(n=>n.id)):null;
  $('mxList').innerHTML=REALMS.filter(([k])=>filt.has(k)).map(([k,l])=>{
    const L=N.filter(n=>n.p.realm===k&&(!hit||hit.has(n.id))).sort((a,b)=>b.deg-a.deg||a.p.n.localeCompare(b.p.n));
    if(!L.length)return '';
    return `<details class="mx-grp" style="--c:${COL[k]}"${hit||filt.size<REALMS.length?' open':''}><summary><i></i>${esc(l)}<em>${L.length}</em></summary><div class="mx-rows">${L.map(n=>{
      const r=rel(n),par=r.up[0];
      return `<button class="mx-row" data-go="${esc(n.id)}"><b>${esc(n.p.n)}</b>${par?` <span class="mx-kids">· part of ${esc(par.o.p.n)}</span>`:''}${r.down.length?` <span class="mx-kids">· owns ${r.down.length}</span>`:''}<small>${esc(n.p.s||'')}</small></button>`}).join('')}</div></details>`}).join('')||'<p class="mx-empty">Nothing matches.</p>';
}
$('mxList').addEventListener('click',e=>{const b=e.target.closest('[data-go]');if(b){mode('graph');select(b.dataset.go,true)}});
let curM='home',curSec=null,curCo=null,origin='geo',LMAP=null,LLAY=null,lfP=null,geoResetPending=false;
function leaflet(){if(window.L&&L.map&&L.markerClusterGroup)return Promise.resolve();if(lfP)return lfP;
  const style=path=>new Promise((ok,no)=>{const href=new URL(path,assetBase).href;const old=document.querySelector(`link[data-mx-style="${path}"]`);if(old?.sheet){ok();return}if(old)old.remove();const c=document.createElement('link');c.rel='stylesheet';c.href=href;c.dataset.mxStyle=path;c.onload=ok;c.onerror=()=>{c.remove();no(new Error('Map styles unavailable'))};document.head.appendChild(c)});
  const script=path=>new Promise((ok,no)=>{const j=document.createElement('script');j.src=new URL(path,assetBase).href;j.onload=ok;j.onerror=()=>{j.remove();no(new Error('Map library unavailable'))};document.head.appendChild(j)});
  // map files live in map-assets/ (moved there Oct 2026). The top-level fallback stays for one release so a cached older
  // deploy still finds them; remove it after that release.
  const any=(load,name)=>load('map-assets/'+name).catch(()=>load(name));
  lfP=Promise.all([any(style,'leaflet.css'),any(style,'MarkerCluster.css'),(window.L&&L.map?Promise.resolve():any(script,'leaflet.js')).then(()=>any(script,'leaflet.markercluster.js'))]).then(()=>{if(!window.L?.markerClusterGroup)throw new Error('Map clustering unavailable')}).catch(e=>{lfP=null;throw e});return lfP}
function resetGeo(){if(!LMAP)return;if(!$('mxGeo').offsetWidth){geoResetPending=true;return}geoResetPending=false;LMAP.invalidateSize();LMAP.fitBounds([[24,-125],[50,-66]],{padding:[22,22],animate:false});}
function geo(){if(curM!=='geo'||!$('mxGeo').offsetWidth)return;
  $('mxGnote').textContent='Loading map…';leaflet().then(()=>{
  if(!LMAP){LMAP=L.map('mxGeo',{worldCopyJump:true,minZoom:2,maxZoom:12,zoomControl:true,attributionControl:true});
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,attribution:'Tiles &copy; Esri'}).addTo(LMAP);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,className:'mx-ref'}).addTo(LMAP);
    LMAP.on('zoomend moveend',()=>{labels();setTimeout(labels,350)});
    const Reset=L.Control.extend({options:{position:'topright'},onAdd(){const c=L.DomUtil.create('div','leaflet-bar mx-map-reset');const b=L.DomUtil.create('button','',c);b.type='button';b.title='Reset to U.S. view';b.setAttribute('aria-label','Reset to U.S. view');b.textContent='↺';L.DomEvent.disableClickPropagation(c);L.DomEvent.disableScrollPropagation(c);b.addEventListener('click',resetGeo);return c}});new Reset().addTo(LMAP);
    new ResizeObserver(()=>{if(!$('mxGeo').offsetWidth)return;if(geoResetPending)resetGeo();else LMAP.invalidateSize();labels()}).observe($('mxGeo'))}
  if(curM!=='geo')return;
  resetGeo();geoSig='';drawGeo();setTimeout(()=>{if(curM==='geo'){LMAP.invalidateSize();labels()}},400)}).catch(()=>{$('mxGnote').innerHTML='Map unavailable. <button class="mx-retry" type="button">Retry map</button>'})}
$('mxGnote').addEventListener('click',e=>{if(e.target.closest('.mx-retry'))geo()});
let geoSig='';
function drawGeo(){if(!LMAP||typeof wmLoc!=='function')return;
  const big=N.filter(n=>(n.tier<=2||n.deg>=3)&&filt.has(n.p.realm)).map(n=>({n,loc:wmLoc(n.p)})).filter(({loc})=>loc&&!loc.via&&Array.isArray(loc.g)&&loc.g.length===2&&loc.g.every(Number.isFinite));
  // what the map shows, from the current sector filter: headquarters only, never service coverage
  const inF=N.filter(n=>filt.has(n.p.realm)).length;
  $('mxGcov').innerHTML=`Headquarters only, not service coverage. <b>${big.length}</b> of <b>${inF}</b> companies have a mapped location.`;
  const s=JSON.stringify(big.map(({n,loc})=>[n.id,n.p.n,n.p.realm,loc.g]));if(s===geoSig)return;geoSig=s;
  if(LLAY)LLAY.remove();
  LLAY=L.markerClusterGroup({maxClusterRadius:()=>window.innerWidth<600?64:48,showCoverageOnHover:false,spiderfyOnMaxZoom:true,zoomToBoundsOnClick:true,spiderfyDistanceMultiplier:2.2,animate:!window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    iconCreateFunction:cluster=>{const count=cluster.getChildCount();return L.divIcon({className:'mx-cluster',html:`<span class="mx-cluster-face">${count}</span>`,iconSize:[44,44],iconAnchor:[22,22]})}}).addTo(LMAP);
  big.forEach(({n,loc})=>{
    const [lon,lat]=loc.g;
    const icon=L.divIcon({className:'mx-marker',html:`<span class="mx-marker-face" style="--c:${COL[n.p.realm]}"><span></span></span>`,iconSize:[44,44],iconAnchor:[22,22]});
    const m=L.marker([lat,lon],{icon,title:n.p.n,alt:n.p.n,keyboard:true,riseOnHover:true,mxMajor:n.tier===1,mxDegree:n.deg});
    m.bindTooltip(esc(n.p.n),{direction:'top',offset:[0,-16],className:'mx-tip',permanent:false});
    m.on('add',()=>{const el=m.getElement();if(el)el.setAttribute('aria-label','Open '+n.p.n+' profile')});
    m.on('click',()=>openCo(n.id));LLAY.addLayer(m)});
  LLAY.on('clusterclick',e=>{const el=e.layer.getElement();if(el)el.setAttribute('aria-label','Explore '+e.layer.getChildCount()+' headquarters')});
  LLAY.on('animationend spiderfied unspiderfied',()=>{document.querySelectorAll('#mxGeo .mx-cluster').forEach(el=>el.setAttribute('aria-label','Explore '+el.textContent+' headquarters'));labels()});
  $('mxGnote').innerHTML=`<b>${big.length}</b> headquarters · <b>${filt.size===REALMS.length?'All sectors':filt.size+' sector'+(filt.size===1?'':'s')}</b>${big.length?'':' · No headquarters in these sectors'}`;
  labels()}
function labels(){if(!LMAP||!LLAY||!LLAY.getVisibleParent)return;const zoom=LMAP.getZoom();
  const update=(layer,text,permanent,cluster,direction='top')=>{const tip=layer.getTooltip();
    if(!tip||tip.options.permanent!==permanent||tip.getContent()!==text||tip.options.direction!==direction){layer.unbindTooltip();layer.bindTooltip(text,{direction,offset:direction==='top'?[0,cluster?-22:-16]:direction==='bottom'?[0,cluster?22:16]:[direction==='right'?20:-20,0],className:cluster?'mx-tip mx-tip-cluster':'mx-tip',permanent})}
    if(permanent)layer.openTooltip()};
  const visible=new Set();LLAY.eachLayer(marker=>{const parent=LLAY.getVisibleParent(marker);if(parent&&parent.getElement())visible.add(parent)});
  const brands=['UPS','FedEx','Amazon','DHL Group','USPS','Walmart','OnTrac'];
  const priority=m=>{const i=brands.indexOf(m.options.title);return i<0?(m.options.mxMajor?100:200)-(m.options.mxDegree||0)/100:i};
  const candidates=[];
  visible.forEach(layer=>{if(typeof layer.getAllChildMarkers==='function'){
      const major=layer.getAllChildMarkers().filter(m=>m.options.mxMajor||brands.includes(m.options.title)).sort((a,b)=>priority(a)-priority(b))[0];
      layer.unbindTooltip();
      if(major)candidates.push({layer,text:esc(major.options.title),cluster:true,rank:priority(major)});
    }else{update(layer,esc(layer.options.title),false,false);if(zoom>=7||layer.options.mxMajor||brands.includes(layer.options.title))candidates.push({layer,text:esc(layer.options.title),cluster:false,rank:priority(layer)})}});
  const bounds=LMAP.getContainer().getBoundingClientRect(),used=[];
  const overlaps=(a,b)=>a.left<b.right+6&&a.right>b.left-6&&a.top<b.bottom+6&&a.bottom>b.top-6;
  // Reserve actual marker targets and map controls; move labels, never headquarters.
  if(bounds.width)visible.forEach(layer=>{const r=layer.getElement().getBoundingClientRect();if(r.width)used.push({left:r.left+6,right:r.right-6,top:r.top+6,bottom:r.bottom-6})});
  $('mxGeo').querySelectorAll('.leaflet-control').forEach(el=>used.push(el.getBoundingClientRect()));
  candidates.sort((a,b)=>a.rank-b.rank).forEach(({layer,text,cluster})=>{
    let placed=false;
    for(const direction of ['top','right','bottom','left']){
      update(layer,text,true,cluster,direction);
      const el=layer.getTooltip()?.getElement?.(),r=el?.getBoundingClientRect();
      if(!bounds.width||!r){placed=true;break}
      const inside=r.left>=bounds.left+6&&r.right<=bounds.right-6&&r.top>=bounds.top+6&&r.bottom<=bounds.bottom-6;
      if(inside&&!used.some(b=>overlaps(r,b))){used.push(r);placed=true;break}
    }
    if(!placed)update(layer,text,false,cluster);
  })}
let HIST=[],LAST=null,RESTORING=false;
function goBack(){const s=HIST.pop();if(!s)return;RESTORING=true;try{s.m==='co'&&byId[s.co]?openCo(s.co):s.m==='sec'?openSec(s.r):s.m==='geo'?(curCo=null,mode('geo')):home()}finally{RESTORING=false;LAST={m:curM,r:curSec,co:curCo};crumb()}}
function mode(m){const nx={m,r:curSec,co:curCo};if(!RESTORING&&LAST&&(LAST.m!==nx.m||LAST.co!==nx.co||LAST.r!==nx.r)){HIST.push(LAST);if(HIST.length>50)HIST.shift()}if(m==='geo'&&!RESTORING)HIST=[];LAST=nx;curM=m;wrap.dataset.m=m;wrap.classList.toggle('list',false);
  if(m==='geo'){curCo=null;curSec=null;q.value='';sugg.hidden=true;G.classList.remove('search')}
  if(m==='geo'||m==='home')origin=m;wrap.querySelectorAll('.mx-mode button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.m===origin)));if(m==='geo')geo();
  crumb();
  if(m==='graph')requestAnimationFrame(()=>{size();if(sel){fit([sel,...sel.links.map(e=>e.a===sel?e.b:e.a)])}else fit()});
  else{side.classList.remove('open')}}
wrap.querySelector('.mx-mode').addEventListener('click',e=>{const b=e.target.closest('[data-m]');if(!b)return;
  if(b.dataset.m==='geo'){curCo=null;curSec=null;mode('geo')}else home()});
function crumb(){const c=$('mxCrumb');if(curM==='graph'||curM==='home'||curM==='geo'){c.innerHTML='';return}
  const s=curSec||(curCo&&byId[curCo].p.realm);
  const pv=HIST[HIST.length-1],pl=pv?(pv.m==='co'&&byId[pv.co]?byId[pv.co].p.n:pv.m==='sec'?RL[pv.r]:pv.m==='geo'?'map':'all sectors'):'';
  c.innerHTML=(pv?`<button data-nav="back" class="mx-back">‹ Back to ${esc(pl)}</button><span>·</span>`:'')+(origin==="geo"?`<button data-nav="geo">Map</button><span>·</span>`:"")+`<button data-nav="home">All sectors</button>`+(s?`<span>›</span><button data-nav="sec" data-r="${s}" ${curM==='sec'?'aria-current="page"':''}>${esc(RL[s])}</button>`:'')+(curM==='co'?`<span>›</span><b>${esc(byId[curCo].p.n)}</b>`:'');}
$('mxCrumb').addEventListener('click',e=>{const b=e.target.closest('[data-nav]');if(!b)return;b.dataset.nav==='back'?goBack():b.dataset.nav==='geo'?(curCo=null,mode('geo')):b.dataset.nav==='home'?home():openSec(b.dataset.r)});
function top(){wrap.scrollIntoView({block:'start',behavior:'smooth'})}
function home(){curSec=null;curCo=null;
  const c=counts();
  $('mxHome').innerHTML=`<p class="mx-lead">Pick a corner of the parcel market to explore. Tap any company to see who owns it and who it works with.</p><div class="mx-tiles">`+REALMS.map(([k,l])=>{
    const L=N.filter(n=>n.p.realm===k).sort((a,b)=>b.deg-a.deg);
    return `<button class="mx-tile" data-r="${k}" style="--c:${COL[k]}"><span class="mx-tn"><i></i>${esc(l)}</span><span class="mx-tc">${c[k]||0}<small> companies</small></span><span class="mx-tt">${L.slice(0,3).map(n=>esc(n.p.n)).join(' · ')}</span></button>`}).join('')+'</div>';
  mode('home')}
$('mxHome').addEventListener('click',e=>{const b=e.target.closest('[data-r]');if(b)openSec(b.dataset.r)});
function openSec(r){curSec=r;curCo=null;
  const L=N.filter(n=>n.p.realm===r).sort((a,b)=>b.deg-a.deg||a.p.n.localeCompare(b.p.n));
  $('mxSect').innerHTML=`<h3 class="mx-h" style="--c:${COL[r]}"><i></i>${esc(RL[r])} <em>${L.length}</em></h3><div class="mx-cards">`+L.map(n=>{const rr=rel(n),par=rr.up[0];
    return `<button class="mx-card" data-go="${esc(n.id)}" style="--c:${COL[r]}"><b class="mx-hl">${LG(n.p,'lgs')}${esc(n.p.n)}</b><small>${par?'Part of '+esc(par.o.p.n):esc(OWN[n.p.own]||'')}${n.deg?' · '+n.deg+' link'+(n.deg>1?'s':''):''}</small></button>`}).join('')+'</div>';
  mode('sec');top()}
$('mxSect').addEventListener('click',e=>{const b=e.target.closest('[data-go]');if(b)openCo(b.dataset.go)});
const GRP=[['up','Owned by'],['down','Owns'],['deal','Deals'],['invBy','Backed by'],['inv','Invested in'],['part','Partners']];
const GCOL={up:'var(--mx-own)',down:'var(--mx-own)',deal:'var(--mx-deal)',invBy:'var(--mx-invest)',inv:'var(--mx-invest)',part:'var(--mx-partner)'};
function explain(n,r){const nm=esc(n.p.n),dl=typeof DEALS!=='undefined'&&typeof dealPlayers==='function'?DEALS.filter(d=>dealPlayers(d).some(id=>byId[id]===n)).length:0,L=a=>a.slice(0,3).map(x=>esc(x.o.p.n)).join(', ')+(a.length>3?' +'+(a.length-3):'');
  const lines=[];if(r.up.length)lines.push(['Players',`Owned by <b>${L(r.up)}</b>`]);if(r.down.length)lines.push(['Players',`Owns <b>${r.down.length}</b> compan${r.down.length>1?'ies':'y'}: ${L(r.down)}`]);
  if(r.deal.length||dl)lines.push(['M&A',`${r.deal.length?`Deals with ${L(r.deal)}`:''}${dl?`${r.deal.length?' · ':''}<b>${dl}</b> deal walkthrough${dl>1?'s':''} below`:''}`]);
  if(r.invBy.length||r.inv.length)lines.push(['Money',[r.invBy.length?`Backed by ${L(r.invBy)}`:'',r.inv.length?`Invested in ${L(r.inv)}`:''].filter(Boolean).join(' · ')]);
  if(r.part.length)lines.push(['Partners',`Works with ${L(r.part)}`]);
  const why=r.up.length?`${nm} is part of a bigger group, so news about its owner can affect it.`:r.down.length>2?`${nm} is a hub: it controls several other players in the market.`:r.deal.length||dl?`${nm} has been active in mergers and acquisitions.`:r.part.length?`${nm} mostly matters through its partnerships.`:`${nm} operates largely on its own in our tracking.`;
  return `<div class="mx-why"><h4>How ${nm} connects</h4><p>${why}</p>${lines.map(([k,t])=>`<div class="mx-wr"><span>${k}</span><div>${t}</div></div>`).join('')}</div>`}
let DH=[];
function openCo(id){const n=byId[id];if(!n)return;curCo=n.id;curSec=n.p.realm;
  if(typeof seenNew==='function'&&typeof store!=='undefined'){const seen=seenNew();seen.add(n.id);store.set('pw-seen-new',JSON.stringify([...seen].slice(-300)));if(typeof navBadge==='function')navBadge()}
  const r=rel(n),ring=[];GRP.forEach(([g])=>r[g].forEach(it=>ring.push({...it,g})));
  const MAX=12,shown=ring.slice(0,MAX),cx=320,cy=320,RR=235;
  const nodes=shown.map((it,i)=>{const a=-Math.PI/2+i/shown.length*Math.PI*2,x=cx+Math.cos(a)*RR,y=cy+Math.sin(a)*RR;
    return {it,x,y};});
  const lines=nodes.map(({it,x,y})=>`<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${GCOL[it.g]}" stroke-width="1.5" ${it.g==='part'?'stroke-dasharray="2 4"':it.g.startsWith('inv')?'stroke-dasharray="5 4"':''}/>`).join('');
  const badges=nodes.map(({it,x,y})=>`<button class="mx-family-node" data-go="${esc(it.o.id)}" style="--x:${(x/640*100).toFixed(2)}%;--y:${(y/640*100).toFixed(2)}%;--mx-relation:${GCOL[it.g]}">${LG(it.o.p,'lgm')}<span class="mx-family-name">${esc(it.o.p.n)}</span><small>${esc(GRP.find(([g])=>g===it.g)?.[1]||'')}${it.yr?' · '+esc(it.yr):''}</small></button>`).join('');
  $('mxCo').innerHTML=`<div class="mx-cowrap"><div class="mx-orb">${shown.length?`<div class="mx-family" aria-label="${esc(n.p.n)} and its connections"><svg viewBox="0 0 640 640" aria-hidden="true">${lines}</svg><div class="mx-family-root">${LG(n.p,'lgl')}<b>${esc(n.p.n)}</b></div><div class="mx-family-branches">${badges}</div></div>
    <div class="mx-leg">${GRP.filter(([g])=>r[g].length).map(([g,l])=>`<span><i style="background:${GCOL[g]}"></i>${l} ${r[g].length}</span>`).join('')}</div>${ring.length>MAX?`<div class="mx-empty mx-family-more">Showing 12 of ${ring.length}. Full list in the details.</div>`:''}`:'<p class="mx-empty">No connections tracked yet.</p>'}</div>
    <div class="mx-det">${(DH=detailOf(n).split('<!--rel-->'))[0]}${explain(n,r)}<div class="pacts"><button class="pact plain" data-mx-players="${esc(n.id)}"><span><b>View in Players</b></span><span class="pgo">›</span></button>${typeof DEALS!=='undefined'&&typeof dealPlayers==='function'?DEALS.filter(d=>dealPlayers(d).some(id=>byId[id]===n)).map(d=>`<button class="pact" data-deal="${DEALS.indexOf(d)}"><span><b>${esc(d.title||d.target)}</b><small>M&A walkthrough</small></span><span class="pgo">›</span></button>`).join(''):''}<button class="pact plain" data-newsq="${esc(n.p.n)}"><span><b>Related news</b></span><span class="pgo">›</span></button></div>${DH[1]||''}</div></div>`;
  mode('co');top()}
$('mxCo').addEventListener('click',e=>{const b=e.target.closest('[data-go]');if(b)openCo(b.dataset.go)});

// All entry points resolve through the same canonical company profile.
document.addEventListener('click',e=>{const players=e.target.closest('[data-mx-players]');if(players){$('mq').value=byId[players.dataset.mxPlayers]?.p.n||'';goTo('mna','players');renderPlayers();return}
  const b=e.target.closest('[data-pl]');if(!b||!byId[b.dataset.pl])return;e.preventDefault();e.stopImmediatePropagation();window.coopClose&&window.coopClose();goTo('mna','map');openCo(b.dataset.pl)},true);

/* ---- lifecycle ---- */
function refresh(){
  const s=JSON.stringify([PLAYERS,PEDGES]);if(s===sig&&laidOut)return;sig=s;
  const keep=sel&&sel.id;build();layout();draw();chips();stats();
  sel=null;if(keep&&byId[keep])select(keep);else panel();
  if(curM==='geo'&&LMAP)drawGeo();else if(curM==='co'&&byId[curCo])openCo(curCo);else if(curM==='sec')openSec(curSec);else if(curM==='home')home();
  requestAnimationFrame(()=>fit());
}
refresh();home();mode('geo');
if(typeof renderMap==='function'){const rm=renderMap;renderMap=function(){try{rm.apply(this,arguments)}catch(e){console.warn(e)}refresh();if(curM==='geo')geo();requestAnimationFrame(()=>{size();if(W&&!T._fit){T._fit=1;fit()}})}}
new ResizeObserver(()=>{const w=W;size();if(W&&!w)fit()}).observe(stage);
setTimeout(()=>{const h=$('mxHint');if(h)h.style.display='none'},9000);
document.addEventListener('keydown',e=>{if(e.key!=='Backspace'||!HIST.length||/INPUT|TEXTAREA|SELECT/.test((e.target.tagName||''))||e.target.isContentEditable)return;const w=document.querySelector('.mx');if(!w||!w.offsetParent||w.dataset.m==='geo')return;e.preventDefault();goBack()});

})();

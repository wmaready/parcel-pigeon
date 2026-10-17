/* ===== Ask Coop: answers parcel questions from the app's own knowledge — vetted facts (data/coop.json), the carriers'
   own rate and service guides (data/guides), live fuel and rate-clock dates, companies and stories. Every answer shows
   its sources. When config.json names an "ask" address, Coop also writes a full answer from the same material. ===== */
(function () {
  'use strict';
  const E = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const G = n => { try { return eval(n); } catch (e) { return undefined; } }; // app globals (const, not on window)
  const STOP = new Set('a an the and or of to in on for is are be do does did can i my we our you your it its at by with what how why when which who should will would much many from about this that there their than then as if me us per'.split(' '));
  const words = s => String(s || '').toLowerCase().replace(/[^a-z0-9.%$ ]+/g, ' ').split(/\s+/).filter(w => w && !STOP.has(w));
  const GEN = new Set('when does apply start starts fees fee surcharge surcharges price prices rate rates cost costs week this package packages shipping ups fedex usps amazon ontrac dhl calculated work works mean means much'.split(' '));
  let KB = null, GUIDES = null, GIDX = null, ASKURL = null;

  const load = async () => {
    if (!KB) KB = await fetch('data/coop.json', { cache: 'no-store' }).then(r => r.ok ? r.json() : { facts: [] }).catch(() => ({ facts: [] }));
    if (!GUIDES) {
      GUIDES = [];
      const idx = await fetch('data/guides/index.json').then(r => r.ok ? r.json() : {}).catch(() => ({}));
      await Promise.all(Object.entries(idx).map(([car, v]) => fetch(v.file).then(r => r.ok ? r.json() : null).then(g => {
        if (!g) return; (g.chunks || []).forEach(([d, t]) => { const doc = (g.docs || [])[d] || {}; GUIDES.push({ car, doc, t: String(t) }); });
      }).catch(() => {})));
      GIDX = GUIDES.map(x => { const m = new Map(); words(x.t).forEach(w => m.set(w, (m.get(w) || 0) + 1)); return m; });
    }
  };

  const CARS = ['UPS', 'FedEx', 'USPS', 'Amazon', 'OnTrac', 'DHL', 'Spee-Dee'];
  const carsIn = q => CARS.filter(c => new RegExp('\\b' + c.replace('-', '\\-') + '\\b', 'i').test(q));

  function factHits(q) {
    const ql = q.toLowerCase(), qw = new Set(words(q));
    return (KB.facts || []).map(f => {
      let s = 0; f.k.forEach(k => { if (ql.includes(k)) s += k.includes(' ') ? 3 : 2; else if (qw.has(k)) s += 2; });
      words(f.t).forEach(w => { if (qw.has(w)) s += .3; });
      return { f, s };
    }).filter(x => x.s >= 2).sort((a, b) => b.s - a.s).slice(0, 2).map(x => x.f);
  }

  function guideHits(q) {
    const qw = [...new Set(words(q))], cs = carsIn(q), N = GUIDES.length || 1;
    const df = w => GIDX.reduce((n, m) => n + (m.has(w) ? 1 : 0), 0) || 1;
    const idf = Object.fromEntries(qw.map(w => [w, Math.log(1 + N / df(w))]));
    return GUIDES.map((g, i) => {
      if (cs.length && !cs.includes(g.car)) return null;
      let s = 0, hit = 0; qw.forEach(w => { const c = GIDX[i].get(w); if (c) { s += idf[w] * (1 + Math.log(c)); hit++; } });
      return hit >= Math.min(2, qw.length) ? { g, s: s * hit } : null;
    }).filter(Boolean).sort((a, b) => b.s - a.s).slice(0, 2).map(x => ({ ...x.g, ex: excerpt(x.g.t, qw) }));
  }

  function excerpt(t, qw) {
    const flat = t.replace(/\s+/g, ' '), lo = flat.toLowerCase();
    let best = 0, bs = -1;
    for (let i = 0; i < lo.length; i += 60) { const win = lo.slice(i, i + 320); const sc = qw.filter(w => win.includes(w)).length; if (sc > bs) { bs = sc; best = i; } }
    const st = Math.max(0, flat.lastIndexOf('. ', best) + 2);
    return (st > 0 ? '…' : '') + flat.slice(st, st + 340).trim() + '…';
  }

  function liveBits(q) {
    const out = [], ql = q.toLowerCase(), cs = carsIn(q);
    const FUEL = G('FUEL'), DATES = G('DATES') || [], daysTo = G('daysTo'), fmtD = G('fmtD');
    if (/fuel|diesel|surcharge %|fsc/.test(ql) && FUEL && FUEL.current) {
      const pick = cs.length ? cs : ['UPS', 'FedEx', 'OnTrac'];
      const L = pick.filter(c => FUEL.current[c]).map(c => `${c} Ground ${FUEL.current[c].ground}%${FUEL.current[c].air ? `, air ${FUEL.current[c].air}%` : ''}`);
      if (L.length) out.push({ h: 'Fuel this week', t: L.join(' · ') + ` (effective ${fmtD ? fmtD(FUEL.eff) : FUEL.eff}).`, go: 'fuel:chart' });
    }
    if (/when|next|date|deadline|upcoming|effective|start|peak|gri|increase|change/.test(ql) && daysTo) {
      const qw = words(q);
      const up = DATES.filter(d => daysTo(d.d) >= 0 && (!cs.length || cs.some(c => String(d.c).includes(c))) && qw.some(w => w.length > 3 && !GEN.has(w) && d.w.toLowerCase().includes(w)))
        .sort((a, b) => a.d.localeCompare(b.d)).slice(0, 3);
      if (up.length) out.push({ h: 'On the rate clock', list: up.map(d => ({ t: `${fmtD ? fmtD(d.d, { month: 'short', day: 'numeric', year: 'numeric' }) : d.d}: ${d.w}`, clock: d.id })) });
    }
    return out;
  }

  function peopleAndNews(q) {
    const PLAYERS = G('PLAYERS') || [], NEWS = G('NEWS') || [], THREADS = G('THREADS') || {}, thrStories = G('thrStories'), MIN = G('THR_MIN') || 4;
    const ql = q.toLowerCase(), qw = words(q).filter(w => w.length > 2 && !GEN.has(w));
    const pl = PLAYERS.filter(p => [p.n, ...(p.al || [])].some(n => n && n.length > 2 && new RegExp('\\b' + n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'i').test(q))).slice(0, 2);
    const th = Object.entries(THREADS).filter(([k, t]) => thrStories && thrStories(k).length >= MIN && qw.filter(w => String(t.n).toLowerCase().includes(w)).length >= 1)
      .map(([k, t]) => ({ k, n: t.n, s: t.s })).slice(0, 1);
    const ns = NEWS.map(n => ({ n, s: qw.filter(w => (n.title + ' ' + n.sum).toLowerCase().includes(w)).length }))
      .filter(x => (qw.length && x.s >= Math.max(1, Math.min(2, qw.length))) || pl.some(p => (x.n.title + ' ' + x.n.sum).toLowerCase().includes(p.n.toLowerCase()))).sort((a, b) => b.s - a.s || b.n.date.localeCompare(a.n.date)).slice(0, 3).map(x => x.n);
    return { pl, th, ns };
  }

  function answer(q) {
    const fx = factHits(q), gd = guideHits(q), live = liveBits(q), { pl, th, ns } = peopleAndNews(q), fmtD = G('fmtD') || (d => d);
    const src = [];
    let h = '';
    if (fx.length) {
      h += `<p class="ak-lead">${E(fx[0].t)}</p>`; src.push([fx[0].s, fx[0].u]);
      if (fx[1]) { h += `<p>${E(fx[1].t)}</p>`; src.push([fx[1].s, fx[1].u]); }
    }
    live.forEach(b => {
      h += `<div class="ak-box"><span class="lbl">${E(b.h)}</span>${b.t ? `<p>${E(b.t)}</p>` : ''}${b.list ? b.list.map(x => `<button type="button" class="link" data-clock="${E(x.clock)}" data-akclose>${E(x.t)}</button>`).join('') : ''}${b.go ? `<button type="button" class="link" data-cgo="${b.go}" data-akclose>Open the fuel tab ›</button>` : ''}</div>`;
    });
    gd.forEach(g => { h += `<div class="ak-box ak-guide"><span class="lbl">From the ${E(g.car)} guide</span><p>${E(g.ex)}</p>${g.doc.u ? `<a href="${E(g.doc.u)}" target="_blank" rel="noopener">${E(g.doc.n || 'Open the guide')} ›</a>` : ''}</div>`; if (g.doc.u) src.push([g.doc.n, g.doc.u]); });
    pl.forEach(p => { h += `<div class="ak-box"><span class="lbl">Company</span><button type="button" class="link" data-pl="${E(p.id)}" data-akclose><b>${E(p.n)}</b></button>${p.what ? `<p>${E(p.what)}</p>` : ''}</div>`; });
    th.forEach(t => { h += `<div class="ak-box"><span class="lbl">Storyline</span><button type="button" class="link" data-thread="${E(t.k)}" data-akclose><b>${E(t.n)}</b></button>${t.s ? `<p>${E(t.s)}</p>` : ''}</div>`; });
    const DEALS = G('DEALS') || [], dl = DEALS.map((d, i) => ({ d, i })).filter(({ d }, j, A) => A.findIndex(x => String(x.d.target).toLowerCase() === String(d.target).toLowerCase()) === j).filter(({ d }) => pl.some(p => [d.buyer, d.target, d.title].join(' ').toLowerCase().includes(p.n.toLowerCase()))).slice(0, 2);
    if (dl.length) h += `<div class="ak-box"><span class="lbl">Deals</span>${dl.map(({ d, i }) => `<button type="button" class="link" data-akdeal="${i}" data-akclose><b>${E(d.title)}</b> <small>· ${E(d.value || '')} · ${E(d.status || '')}</small></button>`).join('')}</div>`;
    if (ns.length) h += `<div class="ak-box"><span class="lbl">Related stories</span>${ns.map(n => `<button type="button" class="link" data-open="${E(n.id)}" data-akclose>${E(n.title)} <small>· ${E(fmtD(n.date))}</small></button>`).join('')}</div>`;
    const found = !!(fx.length || gd.length || live.length || pl.length || th.length || ns.length);
    if (!found) h = `<p class="ak-lead">I don't have that one on file yet. Try a fee name, a carrier or a company. Examples: “dim weight divisor”, “UPS additional handling”, “when do FedEx peak fees start”.</p>`;
    return { h, src, found, ctx: [...fx.map(f => f.t), ...gd.map(g => `[${g.car} guide: ${g.doc.n}] ${g.ex}`), ...live.map(b => b.t || (b.list || []).map(x => x.t).join('; ')), ...ns.map(n => `[Story ${n.date}] ${n.title}: ${n.sum}`)] };
  }

  /* ---- panel ---- */
  let dlg;
  function panel() {
    if (dlg) return dlg;
    dlg = document.createElement('div'); dlg.className = 'akwrap'; dlg.hidden = true;
    dlg.innerHTML = `<div class="akpanel" role="dialog" aria-modal="true" aria-labelledby="akT">
      <div class="akhd"><span class="xname" id="akT">Ask Coop</span><small>Answers from the carriers' guides, live fees and the news desk</small><button type="button" class="cm-x" data-akclose aria-label="Close">×</button></div>
      <form class="akform"><label class="sr" for="akQ">Your parcel question</label><input id="akQ" type="search" autocomplete="off" placeholder="e.g. How is dim weight calculated?"><button type="submit">Ask</button></form>
      <div class="akchips">${['How is dim weight calculated?', 'When does UPS additional handling apply?', 'Fuel surcharge this week', 'When do peak fees start?', 'What is a delivery area surcharge?'].map(x => `<button type="button" data-akq="${E(x)}">${E(x)}</button>`).join('')}</div>
      <div class="akout" aria-live="polite"></div></div>`;
    document.body.appendChild(dlg);
    dlg.querySelector('form').addEventListener('submit', e => { e.preventDefault(); run(dlg.querySelector('#akQ').value); });
    dlg.addEventListener('click', e => {
      const c = e.target.closest('[data-akq]'); if (c) { dlg.querySelector('#akQ').value = c.dataset.akq; run(c.dataset.akq); return; }
      const dd = e.target.closest('[data-akdeal]');
      if (dd) { const v = dd.dataset.akdeal, goTo = G('goTo'); close(); if (goTo) { goTo('mna', 'deals'); setTimeout(() => { const x = document.getElementById('xs-' + v); if (x) { x.scrollIntoView({ block: 'center' }); const b = x.querySelector('[data-explain]'); b && b.click(); } }, 150); } return; }
      if (e.target === dlg || e.target.closest('[data-akclose]')) setTimeout(close, 0);
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !dlg.hidden) close(); });
    return dlg;
  }
  let lastFocus = null;
  function open(q) { const d = panel(); lastFocus = document.activeElement; d.hidden = false; document.body.classList.add('akopen'); const i = d.querySelector('#akQ'); i.value = q || ''; if (q) run(q); else { d.querySelector('.akout').innerHTML = ''; } setTimeout(() => i.focus(), 30); }
  function close() { if (!dlg) return; dlg.hidden = true; document.body.classList.remove('akopen'); lastFocus && lastFocus.focus && lastFocus.focus(); }

  let runId = 0;
  async function run(q) {
    q = String(q || '').trim(); if (q.length < 2) return; const id = ++runId, out = dlg.querySelector('.akout');
    out.innerHTML = '<p class="ak-wait">Coop is flipping through the guides…</p>';
    await load(); if (id !== runId) return;
    const a = answer(q);
    dlg.classList.add('answered');
    out.innerHTML = `<div class="ak-a">${a.h}</div>${a.src.length ? `<p class="ak-src"><span class="lbl">Sources</span>${[...new Map(a.src.map(s => [s[1], s])).values()].map(([n, u]) => `<a href="${E(u)}" target="_blank" rel="noopener">${E(n)}</a>`).join(' · ')}</p>` : ''}${ASKURL && a.found ? '<div class="ak-ai"><p class="ak-wait">Coop is writing a fuller answer…</p></div>' : ''}`;
    if (window.gsap && !(matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches)) gsap.fromTo(out.querySelectorAll('.ak-a > *'), { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: .35, stagger: .07 });
    if (ASKURL && a.found) {
      try {
        const r = await fetch(ASKURL, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ q, ctx: a.ctx.slice(0, 8) }) });
        const j = r.ok ? await r.json() : null; if (id !== runId) return;
        const box = out.querySelector('.ak-ai'); if (!box) return;
        box.innerHTML = j && j.a ? `<span class="lbl">Coop's take</span><p>${E(j.a)}</p>` : '';
      } catch (e) { const box = out.querySelector('.ak-ai'); if (box) box.innerHTML = ''; }
    }
  }

  window.PP_ASK = true;
  window.askCoop = open;
  window.askCoopAnswer = async q => { await load(); return answer(q); }; // used by tests
  window.askCoopReady = () => fetch('config.json', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(j => { if (j && j.ask) ASKURL = String(j.ask); }).catch(() => {});
  window.askCoopReady();
  document.addEventListener('click', e => { const b = e.target.closest('[data-askopen]'); if (!b) return; e.preventDefault(); setTimeout(() => open(b.dataset.askopen || ''), 0); });
})();

/* ===== Ask Coop: answers parcel questions from the app's own knowledge — vetted facts (data/coop.json), the carriers'
   own rate and service guides (data/guides), the pricing history since 2018 (data/almanac.json) and its year-over-year
   notes (data/patterns.json), live fuel and rate-clock dates, companies (with their double-checked facts) and stories.
   Everything is matched in the browser: no AI call, no cost per question. Every answer shows its sources and links each
   story (#s=<id>) and company page (#c=<id>). Two date rules everywhere: the announced date and the date a change takes
   effect are separate and never swapped, and a missing date is said to be missing, never guessed. A story resting on one
   smaller outlet is always labelled unconfirmed.
   When config.json names an "ask" address, Coop also writes a full answer from the same material (off unless set). ===== */
(function () {
  'use strict';
  const E = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const G = n => { try { return eval(n); } catch (e) { return undefined; } }; // app globals (const, not on window)
  const STOP = new Set('a an the and or of to in on for is are be do does did can i my we our you your it its at by with what how why when which who should will would much many from about this that there their than then as if me us per has have had made make'.split(' '));
  const words = s => String(s || '').toLowerCase().replace(/[^a-z0-9.%$ ]+/g, ' ').split(/\s+/).filter(w => w && !STOP.has(w));
  const GEN = new Set('when does apply start starts fees fee surcharge surcharges price prices rate rates cost costs week this package packages shipping ups fedex usps amazon ontrac dhl calculated work works mean means much year years announced announce effective change changes off-cycle off cycle history past previous since compare versus last next was were been happened dates date where owns owned owner based founded headquartered headquarters'.split(' '));
  // the generic words of a pricing kind ("GRI", "peak", "surcharge"): the kind itself matches them, so they never have to appear in a headline
  const KINDW = new Set('gri general rate rates increase increases hike annual price prices peak demand holiday fuel table tables surcharge surcharges fees fee'.split(' '));
  // whole-word match from the start of a word: "ontrac" is not in "contract", "owns" is not in "towns"
  const hasW = (txt, w) => new RegExp('\\b' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(txt);
  let KB = null, GUIDES = null, GIDX = null, ASKURL = null, ALMA = null, PATS = null, PROGS = null;

  const getJSON = (u, dflt) => fetch(u).then(r => r.ok ? r.json() : dflt).catch(() => dflt);
  const load = async () => {
    if (!KB) KB = await fetch('data/coop.json', { cache: 'no-store' }).then(r => r.ok ? r.json() : { facts: [] }).catch(() => ({ facts: [] }));
    if (!ALMA) {
      // reuse the copy the Year-over-year view already loaded, else fetch our own
      const A = G('ALM'), P = G('PAT');
      [ALMA, PATS] = Array.isArray(A) ? [A, P || { items: [] }] : await Promise.all([getJSON('data/almanac.json', []), getJSON('data/patterns.json', { items: [] })]);
      if (!Array.isArray(ALMA)) ALMA = [];
      if (!PATS || !Array.isArray(PATS.items)) PATS = { items: [] };
    }
    // what each program advertises (data/programs.json, kept by the pipeline); read defensively, it may be absent
    if (!PROGS) {
      const j = await getJSON('data/programs.json', null);
      const L = Array.isArray(j) ? j : j && Array.isArray(j.programs) ? j.programs : j && typeof j === 'object' ? Object.values(j).filter(x => x && typeof x === 'object' && !Array.isArray(x)) : [];
      PROGS = L.map(progNorm).filter(Boolean);
    }
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
  const carsNamed = q => CARS.filter(c => new RegExp('\\b' + c.replace('-', '\\-') + '\\b', 'i').test(q));
  // a question about a carrier's program ("Small Business Rates") is about that carrier, even when it doesn't name it
  const carsIn = q => { const c = carsNamed(q); return c.length ? c : [...new Set(progHits(q).map(p => p.carrier).filter(x => CARS.includes(x)))]; };

  /* ---- programs (data/programs.json): SBR, Ground Saver, One Rate and what each says it includes ---- */
  const txtOf = x => typeof x === 'string' ? x : x && typeof x === 'object' ? String(x.text || x.t || x.item || x.what || x.name || x.n || '') : '';
  const listOf = v => (Array.isArray(v) ? v : v ? [v] : []).map(x => ({ t: txtOf(x), src: x && typeof x === 'object' ? (x.src || x.url || x.source || null) : null, checked: x && typeof x === 'object' ? (x.checked || null) : null })).filter(x => x.t);
  function progNorm(r) {
    if (!r || typeof r !== 'object') return null;
    const name = String(r.program || r.name || r.n || r.title || '').trim(), carrier = String(r.carrier || r.c || '').trim();
    if (!name) return null;
    const bare = name.replace(new RegExp('^' + carrier.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s+', 'i'), '');
    const acr = bare.split(/\s+/).filter(w => /^[A-Z]/.test(w)).map(w => w[0]).join('');
    const names = [...new Set([name, bare, ...(Array.isArray(r.aliases) ? r.aliases : Array.isArray(r.al) ? r.al : []), ...(acr.length >= 3 ? [acr] : [])].map(String).filter(n => n.length >= 3))];
    return { id: r.id || name, name, carrier, names, inc: listOf(r.inclusions || r.includes || r.included || r.promises || r.advertised),
      none: listOf(r.no_fees || r.excluded_fees || r.waived || r.not_charged), changes: listOf(r.changes),
      src: r.src || r.url || r.source || (Array.isArray(r.sources) ? r.sources[0] : null), checked: r.checked || null };
  }
  const progHits = q => (PROGS || []).filter(p => p.names.some(n => new RegExp('\\b' + n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'i').test(q))).slice(0, 2);
  const progText = p => `${p.carrier && !new RegExp('^' + p.carrier, 'i').test(p.name) ? p.carrier + ' ' : ''}${p.name}${p.inc.length ? `: advertised as including ${p.inc.map(x => x.t).join('; ')}` : ''}${p.none.length ? `. No ${p.none.map(x => x.t).join(', ')}` : ''}.`;
  const today = () => G('TODAY') || new Date().toISOString().slice(0, 10);
  const longD = d => { const f = G('fmtD'); const s = f ? f(String(d).slice(0, 10), { month: 'short', day: 'numeric', year: 'numeric' }) : ''; return s || String(d); };

  /* ---- dates: announced and effective are always two separate, labelled fields ---- */
  // the two dates as plain text; a date we don't have says so instead of borrowing the other one
  function dateLine(ann, eff, other) {
    if (!ann && !eff) return other ? `Date: ${longD(other)}` : '';
    return `Announced: ${ann ? longD(ann) : 'date not on file'} · Takes effect: ${eff ? longD(eff) : 'date not on file'}`;
  }

  /* ---- question cues ---- */
  const OFFC_Q = /off[- ]?cycle|mid[- ]?year|outside (the|their|its) (usual|normal|annual)|unscheduled|surprise (increase|change|fee)/i;
  const HIST_Q = /\b(history|histor|announc|effective|since|past|previous|last|each year|every year|over the years|year over year|yoy|compare|vs\.?|versus|trend|pattern|usually|typically|when did|when was|how much did|20[12]\d)\b/i;
  const KINDQ = [
    [/\bgri\b|general rate|rate (increase|hike)|annual (increase|rate)|price (increase|change)|prices? (rise|went up|go up)|increase/i, ['gri', 'price_change']],
    [/peak|demand surcharge|holiday (surcharge|price|rate)/i, ['peak']],
    [/fuel (table|surcharge table)|fuel tables?/i, ['fuel_table']],
    [/\bdim\b|dimensional|divisor/i, ['dim', 'other']],
    [/delivery area|\bdas\b/i, ['das']],
    [/(?<!peak |demand )surcharge|\bfees?\b|additional handling|large package|oversize/i, ['surcharge', 'fee', 'das', 'dim']],
  ];
  function yearsIn(q) {
    const y = +today().slice(0, 4), out = new Set((q.match(/\b20[12]\d\b/g) || []).map(Number));
    if (/\bthis year\b|\bso far\b|\bytd\b/i.test(q)) out.add(y);
    if (/\blast year\b/i.test(q)) out.add(y - 1);
    if (/\bnext year\b/i.test(q)) out.add(y + 1);
    return [...out];
  }
  // the content words of a question: no carrier names, years or generic pricing words
  const cwords = q => words(q).filter(w => w.length > 3 && !GEN.has(w) && !/^\d+$/.test(w));
  const isOff = e => { const c = G('cycleOf'); return !!(c && c(e.carrier, e.kind, e.effective, e.announced) === 'off'); };

  /* ---- pricing history (data/almanac.json) ---- */
  function almanacHits(q) {
    const cs = carsIn(q), ys = yearsIn(q), off = OFFC_Q.test(q), hist = HIST_Q.test(q), kinds = new Set(), qw = cwords(q);
    KINDQ.forEach(([re, ks]) => { if (re.test(q)) ks.forEach(k => kinds.add(k)); });
    // only when the question is about a change over time: a pricing kind with a carrier, a year or a history word, or off-cycle
    if (!off && !(kinds.size && (cs.length || ys.length || hist))) return [];
    // a plain "FedEx peak surcharge" question: only the changes from the past year and those coming up
    const since = !off && !hist && !ys.length ? new Date(Date.parse(today()) - 365 * 864e5).toISOString().slice(0, 10) : '';
    const hits = ALMA.filter(e => e && e.carrier && e.headline).map(e => {
      const effY = +(String(e.effective || e.date || '').slice(0, 4)) || null;
      if (since && String(e.effective || e.date || '') < since) return null;
      if (cs.length && !cs.some(c => String(e.carrier).toLowerCase() === c.toLowerCase())) return null;
      if (ys.length && !ys.some(y => +e.year === y || effY === y)) return null;
      if (off && !isOff(e)) return null;
      // a named fee ("additional handling", "divisor") must be in the entry itself, not just the same kind of change
      const txt = e.headline + ' ' + (e.details || []).join(' '), spec = qw.filter(w => !KINDW.has(w)), on = spec.filter(w => hasW(txt, w)).length;
      if (spec.length && !on) return null;
      if (!off && kinds.size && !kinds.has(e.kind) && !on) return null;
      let s = (kinds.has(e.kind) ? 3 : 0) + on + (hasW(e.headline, spec[0] || '\u0000') ? 1 : 0);
      if (ys.some(y => +e.year === y)) s += 1;
      return { e, s };
    }).filter(Boolean);
    return hits.filter(x => !closedBy(x.e)).sort((a, b) => b.s - a.s || String(b.e.effective || b.e.date || '').localeCompare(String(a.e.effective || a.e.date || ''))).slice(0, off ? 6 : since ? 2 : 4).map(x => x.e);
  }
  /* A "not yet announced" placeholder (no announced or effective date, no figure) is closed once a Pricing & GRI story for
     the same carrier lands with a change taking effect from November of the year before to the end of that year: the
     answer then leads with that story, never with "not yet announced". */
  const isPlaceholder = e => e && !e.announced && !e.effective && e.pct == null && /\bnot (yet )?(announced|published)\b/i.test(String(e.headline || '') + ' ' + String(e.note || ''));
  function closedBy(e) {
    if (!isPlaceholder(e) || !e.year) return null;
    const y = +e.year, lo = `${y - 1}-11-01`, hi = `${y}-12-31`;
    return (G('NEWS') || []).filter(n => n && n.cat === 'Pricing & GRI' && (Array.isArray(n.c) ? n.c : [n.c]).some(c => String(c).toLowerCase() === String(e.carrier).toLowerCase())
      && [n.act, ...(n.dates || []).map(d => d && d.d)].some(d => d && d >= lo && d <= hi)).sort((a, b) => String(b.date).localeCompare(a.date))[0] || null;
  }
  // the stories that closed the placeholders a question would otherwise have hit
  function closingStories(q) {
    const cs = carsIn(q), ys = yearsIn(q);
    if (!cs.length && !ys.length) return [];
    return [...new Set(ALMA.filter(e => isPlaceholder(e) && (!cs.length || cs.some(c => String(e.carrier).toLowerCase() === c.toLowerCase())) && (!ys.length || ys.includes(+e.year)))
      .map(closedBy).filter(Boolean))];
  }
  // "UPS 2026 GRI: …" already names its carrier; "DIM divisor cut …" doesn't
  const almHead = e => new RegExp('^' + String(e.carrier).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'i').test(e.headline) ? e.headline : `${e.carrier}: ${e.headline}`;
  const almText = e => `${almHead(e)}. ${dateLine(e.announced, e.effective, e.date)}.${e.pct != null ? ` Average ${e.pct}%.` : ''}${isOff(e) ? ' Off-cycle (outside the usual annual increase and peak season).' : ''}${e.conf === 'partial' ? ' Partly confirmed.' : ''}`;

  /* ---- year-over-year notes (data/patterns.json) ---- */
  function patternHits(q) {
    const cs = carsIn(q), qw = cwords(q), cue = /pattern|trend|year over year|yoy|compare|usually|typical|every year|each year|history/i.test(q);
    return PATS.items.map(p => {
      if (cs.length && !(p.carriers || []).some(c => cs.includes(c))) return null;
      const txt = (p.t + ' ' + p.body).toLowerCase(), s = qw.filter(w => txt.includes(w)).length;
      return (cue && (s >= 1 || cs.length)) || s >= 2 ? { p, s } : null;
    }).filter(Boolean).sort((a, b) => b.s - a.s).slice(0, 1).map(x => x.p);
  }

  /* ---- vetted facts (data/coop.json), with a warning when the pricing history shows a figure has since changed ---- */
  function factHits(q) {
    const ql = q.toLowerCase(), qw = new Set(words(q)), cs = carsNamed(q);
    // a question that names a carrier never gets a note about other carriers only
    const other = f => { if (!cs.length) return false; const fc = carsNamed(f.t); return fc.length > 0 && !fc.some(c => cs.includes(c)); };
    return (KB.facts || []).filter(f => !other(f)).map(f => {
      let s = 0; f.k.forEach(k => { if (ql.includes(k)) s += k.includes(' ') ? 3 : 2; else if (qw.has(k)) s += 2; });
      words(f.t).forEach(w => { if (qw.has(w)) s += .3; });
      return { f, s };
    }).filter(x => x.s >= 2).sort((a, b) => b.s - a.s).slice(0, 2).map(x => x.f);
  }
  // a change already in effect that moved a number this fact still quotes ("divisor cut from 166 to 139"), for the same carrier
  function supersededBy(f) {
    const t = String(f.t), now = today();
    return ALMA.find(e => {
      if (!e || !e.effective || e.effective > now || !new RegExp('\\b' + String(e.carrier).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b').test(t)) return false;
      const m = /\b(?:from\s+)?\$?(\d+(?:\.\d+)?)\s*(?:to|->|→)\s*\$?(\d+(?:\.\d+)?)\b/i.exec(e.headline || '');
      if (!m || m[1] === m[2]) return false;
      const has = n => new RegExp('(?<![\\d.])' + n.replace('.', '\\.') + '(?![\\d])').test(t);
      return has(m[1]) && !has(m[2]);
    }) || null;
  }

  function guideHits(q) {
    const qw = [...new Set(words(q))], cs = carsIn(q), N = GUIDES.length || 1;
    const df = w => GIDX.reduce((n, m) => n + (m.has(w) ? 1 : 0), 0) || 1;
    const idf = Object.fromEntries(qw.map(w => [w, Math.log(1 + N / df(w))]));
    return GUIDES.map((g, i) => {
      if (cs.length && !cs.includes(g.car)) return null;
      let s = 0, hit = 0; qw.forEach(w => { const c = GIDX[i].get(w); if (c) { s += idf[w] * (1 + Math.log(c)); hit++; } });
      if (hit < Math.min(2, qw.length)) return null;
      // prefer the current year's guide: last year's counts a little less, older or undated documents much less
      const y = guideYear(g), cy = +today().slice(0, 4);
      return { g, s: s * hit * (!y ? .45 : y >= cy ? 1 : y === cy - 1 ? .7 : .4) };
    }).filter(Boolean).sort((a, b) => b.s - a.s).slice(0, 2).map(x => ({ ...x.g, ex: excerpt(x.g.t, qw), y: guideYear(x.g), eff: guideEff(x.g) }));
  }
  // a guide's effective date: the app's Docs entry for the same file, else an "Effective <date>" the passage states
  const MON = '(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\\.?';
  function guideEff(g) {
    const DOCS = G('DOCS') || [], key = G('docKey'), u = g.doc && g.doc.u;
    const d = u && key && DOCS.find(x => x && x.u && key(x._u0 || x.u) === key(u));
    if (d && d.eff) return d.eff;
    const m = new RegExp('effective\\s+(' + MON + '\\s+\\d{1,2},?\\s+20[1-3]\\d)', 'i').exec(g.t);
    if (!m) return null;
    const t = new Date(m[1].replace(/\.(?=\s)/, '') + ' 12:00');
    return isNaN(t) ? null : `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
  }
  const guideYear = g => +(g.doc && g.doc.y) || +String(guideEff(g) || '').slice(0, 4) || null;
  const guideMeta = g => [g.y ? String(g.y) : 'Year not stated', g.eff ? `effective ${longD(g.eff)}` : 'effective date not on file'].join(' · ');

  function excerpt(t, qw) {
    const flat = t.replace(/\s+/g, ' '), lo = flat.toLowerCase();
    let best = 0, bs = -1;
    for (let i = 0; i < lo.length; i += 60) { const win = lo.slice(i, i + 320); const sc = qw.filter(w => win.includes(w)).length; if (sc > bs) { bs = sc; best = i; } }
    const st = Math.max(0, flat.lastIndexOf('. ', best) + 2);
    return (st > 0 ? '…' : '') + flat.slice(st, st + 340).trim() + '…';
  }

  function liveBits(q) {
    const out = [], ql = q.toLowerCase(), cs = carsIn(q);
    const FUEL = G('FUEL'), DATES = G('DATES') || [], daysTo = G('daysTo');
    if (/fuel|diesel|surcharge %|fsc/.test(ql) && !/fuel table/.test(ql) && FUEL && FUEL.current) {
      // each carrier's own effective week, "last confirmed week of …" when it is more than 8 days old (as the Fuel tab)
      const pick = cs.length ? cs : ['UPS', 'FedEx', 'OnTrac'], FA = window.FUEL_API, wk = FUEL.wk || {};
      const when = c => { const d = wk[c] && wk[c].ground; return d ? (FA ? FA.wk(d) : `week of ${longD(d)}`) : ''; };
      const old = c => { const d = wk[c] && wk[c].ground; return !d || (FA ? FA.old(d) : true); };
      const P = pick.filter(c => FUEL.current[c] && FUEL.current[c].ground != null);
      const L = P.map(c => `${c} Ground ${FUEL.current[c].ground}%${FUEL.current[c].air ? `, air ${FUEL.current[c].air}%` : ''}${when(c) ? ` (${when(c)})` : ''}`);
      if (L.length) out.push({ h: P.some(old) ? 'Fuel, latest posted weeks' : 'Fuel this week', t: L.join(' · ') + '.', go: 'fuel:chart', gol: 'Open the fuel tab ›' });
    }
    if (/when|next|date|deadline|upcoming|effective|start|peak|gri|increase|change/.test(ql) && daysTo) {
      const qw = words(q);
      const up = DATES.filter(d => daysTo(d.d) >= 0 && (!cs.length || cs.some(c => String(d.c).includes(c))) && qw.some(w => w.length > 3 && !GEN.has(w) && d.w.toLowerCase().includes(w)))
        .sort((a, b) => a.d.localeCompare(b.d)).slice(0, 3);
      // rate clock dates are the dates a change takes effect
      if (up.length) out.push({ h: 'On the rate clock', list: up.map(d => ({ t: `Takes effect ${longD(d.d)}: ${d.w}`, clock: d.id })) });
    }
    return out;
  }

  function peopleAndNews(q) {
    const PLAYERS = G('PLAYERS') || [], NEWS = G('NEWS') || [], THREADS = G('THREADS') || {}, thrStories = G('thrStories'), MIN = G('THR_MIN') || 4;
    const qw = words(q).filter(w => w.length > 2 && !GEN.has(w)), cs = carsIn(q), ys = yearsIn(q), off = OFFC_Q.test(q);
    const seen = new Set();
    const pl = PLAYERS.filter(p => [p.n, ...(p.al || [])].some(n => n && n.length > 2 && new RegExp('\\b' + n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'i').test(q)))
      .filter(p => !seen.has(p.id) && seen.add(p.id)).slice(0, 2);
    const th = Object.entries(THREADS).filter(([k, t]) => thrStories && thrStories(k).length >= MIN && qw.filter(w => String(t.n).toLowerCase().includes(w)).length >= 1)
      .map(([k, t]) => ({ k, n: t.n, s: t.s })).slice(0, 1);
    const carOf = n => (Array.isArray(n.c) ? n.c : [n.c]).map(String);
    let ns;
    if (off) {
      // off-cycle question: the stories the desk flagged as off-cycle, for the carriers and year asked about
      ns = NEWS.filter(n => n.offc && (!cs.length || carOf(n).some(c => cs.includes(c))) && (!ys.length || ys.some(y => [n.act, n.date].some(d => String(d || '').startsWith(String(y))))))
        .sort((a, b) => String(b.date).localeCompare(a.date)).slice(0, 4);
    } else {
      ns = NEWS.map(n => ({ n, s: qw.filter(w => hasW(n.title + ' ' + n.sum, w)).length }))
        .filter(x => (qw.length && x.s >= Math.max(1, Math.min(2, qw.length))) || pl.some(p => hasW(x.n.title + ' ' + x.n.sum, p.n))).sort((a, b) => b.s - a.s || b.n.date.localeCompare(a.n.date)).slice(0, 3).map(x => x.n);
    }
    return { pl, th, ns };
  }

  /* ---- companies: profile plus the facts sweep.py double-checks (players.json "facts", merged into PLAYERS at load) ---- */
  const OWN = { public: 'Public company', private: 'Privately held', sub: 'Subsidiary', gov: 'Government', pe: 'Private-equity owned' };
  function coFacts(p) {
    const PL = G('PL') || {}, par = p.parent && PL[p.parent];
    const own = p.own && OWN[p.own] ? OWN[p.own] + (p.own === 'public' && p.tk ? ` (${p.tk})` : '') + (par ? ` of ${par.n}` : '') : (par ? `Part of ${par.n}` : '');
    return [p.hq && ['Headquarters', p.hq], p.yr && ['Founded', String(p.yr)], own && ['Ownership', own]].filter(Boolean);
  }
  const coText = p => `${p.n}: ${p.s || ''} ${coFacts(p).map(([k, v]) => `${k}: ${v}.`).join(' ')}${p.vf ? ` (Facts double-checked ${p.vf}.)` : ''}`.trim();
  const CO_Q = /\b(hq|headquarter\w*|based|founded|started|how old|owner|owns|owned|parent|public|private|ticker)\b/i;

  /* ---- stories: dates and flags as the desk recorded them ---- */
  const storyTags = n => (n.offc ? '<span class="tag tag-offc">Off-cycle</span>' : '') + (n.unconf ? '<span class="tag tag-unconf" title="Reported by one smaller outlet so far; not yet confirmed by the company or the major or trade press">Unconfirmed</span>' : '');
  // only the dates the story states, each with its own label
  const storyDates = n => [n.ann && `Announced: ${longD(n.ann)}`, n.act && `Takes effect: ${longD(n.act)}`].filter(Boolean).join(' · ');
  const storyCtx = n => `[Story ${n.date}${n.unconf ? ', UNCONFIRMED: one smaller outlet so far, say so' : ''}${n.offc ? ', off-cycle' : ''}] ${n.title}: ${n.sum}${storyDates(n) ? ' ' + storyDates(n) + '.' : ''}`;
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return 'source'; } };
  const sLink = (n, inner) => `<a class="link" href="#s=${E(n.id)}" data-aks="${E(n.id)}">${inner}</a>`;
  const cLink = (p, inner) => `<a class="link" href="#c=${E(p.id)}" data-akc="${E(p.id)}">${inner}</a>`;

  function answer(q) {
    const fx = factHits(q), al = almanacHits(q), pt = patternHits(q), live = liveBits(q), { pl, th } = peopleAndNews(q), fmtD = G('fmtD') || (d => d);
    const pg = progHits(q), cl = closingStories(q);
    let { ns } = peopleAndNews(q);
    ns = [...cl, ...ns.filter(n => !cl.includes(n))].slice(0, Math.max(3, cl.length));
    const off = OFFC_Q.test(q), ys = yearsIn(q), coQ = !fx.length && pl.length && CO_Q.test(q) && coFacts(pl[0]).length;
    // a dated pricing question or a company-facts question is answered from those; rate-table excerpts would only be noise
    // a program question is answered from the program record; generic rate-guide passages would only blur it
    const gd = (al.length && (ys.length || off)) || coQ || pg.length || cl.length ? [] : guideHits(q);
    const src = [];
    let h = '';
    pg.forEach((p, i) => {
      h += `<p${!i ? ' class="ak-lead"' : ''}>${E(progText(p))}</p>`;
      if (p.changes.length) h += `<div class="ak-box ak-warn"><span class="lbl">Changes on file</span>${p.changes.map(c => `<p>${E(c.t)}</p>`).join('')}</div>`;
      h += p.src || p.checked ? `<p class="ak-note"><small>${p.src ? `<a href="${E(p.src)}" target="_blank" rel="noopener">${E(p.carrier || 'Program')} program page ›</a> ` : ''}${p.checked ? `Checked ${E(longD(p.checked))}.` : ''}</small></p>` : '';
      if (p.src) src.push([`${p.name}`, p.src]);
    });
    const lead = !pg.length;
    if (!pg.length && cl.length && !al.length) {
      const n = cl[0];
      h += `<p class="ak-lead">${E(n.title)}. ${E(storyDates(n) || `Reported ${longD(n.date)}`)}.</p>`;
    }
    const stale = fx.map(supersededBy);
    const facts = lead => fx.forEach((f, i) => {
      if (stale[i]) h += `<div class="ak-box ak-warn"><span class="lbl">Changed since this note</span><p>${E(almHead(stale[i]))}. ${E(dateLine(stale[i].announced, stale[i].effective))}.</p></div>`;
      h += `<p${lead && !i ? ' class="ak-lead"' : ''}>${E(f.t)}</p>`; src.push([f.s, f.u]);
    });
    if (off && (al.length || ns.length)) {
      h += `<p class="ak-lead">Here ${al.length + ns.length === 1 ? 'is the off-cycle change' : 'are the off-cycle changes'} on file${carsIn(q).length ? ' for ' + E(carsIn(q).join(' and ')) : ''}${ys.length ? ' in ' + ys.join(' and ') : ''}: price changes that take effect outside the carrier's usual annual increase and peak season.</p>`;
    } else if (al.length && ys.length) {
      const e = al[0];
      h += `<p${lead ? ' class="ak-lead"' : ''}>${E(almHead(e))}. ${E(dateLine(e.announced, e.effective, e.date))}.</p>`;
      facts(false);
    } else if (fx.length) {
      facts(lead && !cl.length);
    } else if (coQ) {
      const p = pl[0];
      h += `<p class="ak-lead">${E(p.n)}: ${coFacts(p).map(([k, v]) => `${k.toLowerCase()} ${E(v)}`).join('; ')}.${p.vf ? '' : ' <small>(from the market map; not yet double-checked)</small>'}</p>`;
    } else if (al.length) {
      const e = al[0];
      h += `<p${lead ? ' class="ak-lead"' : ''}>${E(almHead(e))}. ${E(dateLine(e.announced, e.effective, e.date))}.</p>`;
    }
    if (al.length) {
      h += `<div class="ak-box ak-alm"><span class="lbl">${off ? 'Off-cycle changes in the pricing history' : 'Pricing history'}</span>${al.map(e => {
        const u = (e.sources || [])[0]; if (u) src.push([`${e.carrier} ${e.year} (${host(u)})`, u]);
        return `<div class="ak-ev"><b>${E(almHead(e))}</b>${isOff(e) ? '<span class="tag tag-offc">Off-cycle</span>' : ''}<small>${E(dateLine(e.announced, e.effective, e.date))}${e.pct != null ? ` · Average ${E(e.pct)}%` : ''}</small>${e.conf === 'partial' ? `<small class="ak-note">Partly confirmed${e.note ? ': ' + E(String(e.note).slice(0, 220)) : ''}</small>` : ''}${u ? `<a href="${E(u)}" target="_blank" rel="noopener">Source ›</a>` : ''}</div>`;
      }).join('')}<button type="button" class="link" data-goto="clock:years" data-akclose>See every year side by side ›</button></div>`;
    }
    pt.forEach(p => { h += `<div class="ak-box"><span class="lbl">Year over year</span><b>${E(p.t)}</b><p>${E(p.body)}</p></div>`; });
    live.forEach(b => {
      h += `<div class="ak-box"><span class="lbl">${E(b.h)}</span>${b.t ? `<p>${E(b.t)}</p>` : ''}${b.list ? b.list.map(x => `<button type="button" class="link" data-clock="${E(x.clock)}" data-akclose>${E(x.t)}</button>`).join('') : ''}${b.go ? `<button type="button" class="link" data-goto="${E(b.go)}" data-akclose>${E(b.gol)}</button>` : ''}</div>`;
    });
    // each excerpt names its document, year and effective date; an older year says so
    const cy = +today().slice(0, 4);
    gd.forEach(g => { h += `<div class="ak-box ak-guide"><span class="lbl">From the ${E(g.car)} guide: ${E(g.doc.n || 'document')}</span><small>${E(guideMeta(g))}</small>${!g.y || g.y < cy ? `<small class="ak-note">${g.y ? `This is a ${E(g.y)} document` : 'This document states no year'}; check the carrier's current version.</small>` : ''}<p>${E(g.ex)}</p>${g.doc.u ? `<a href="${E(g.doc.u)}" target="_blank" rel="noopener">${E(g.doc.n || 'Open the guide')} ›</a>` : ''}</div>`; if (g.doc.u) src.push([g.doc.n, g.doc.u]); });
    pl.forEach(p => {
      const F = coFacts(p);
      h += `<div class="ak-box"><span class="lbl">Company</span>${cLink(p, `<b>${E(p.n)}</b>`)}${p.s ? `<p>${E(p.s)}</p>` : ''}${F.length ? `<p class="ak-facts">${F.map(([k, v]) => `<span><i>${E(k)}</i> ${E(v)}</span>`).join('')}</p>` : ''}${p.vf ? `<small>Facts double-checked ${E(longD(p.vf))}${(p.vsrc || []).length ? ` against ${(p.vsrc || []).length} sources` : ''}</small>` : ''}${cLink(p, 'Open the company page ›')}</div>`;
    });
    th.forEach(t => { h += `<div class="ak-box"><span class="lbl">Storyline</span><button type="button" class="link" data-thread="${E(t.k)}" data-akclose><b>${E(t.n)}</b></button>${t.s ? `<p>${E(t.s)}</p>` : ''}</div>`; });
    const DEALS = G('DEALS') || [], dl = DEALS.map((d, i) => ({ d, i })).filter(({ d }, j, A) => A.findIndex(x => String(x.d.target).toLowerCase() === String(d.target).toLowerCase()) === j).filter(({ d }) => pl.some(p => hasW([d.buyer, d.target, d.title].join(' '), p.n))).slice(0, 2);
    if (dl.length) h += `<div class="ak-box"><span class="lbl">Deals</span>${dl.map(({ d, i }) => `<button type="button" class="link" data-akdeal="${i}" data-akclose><b>${E(d.title)}</b> <small>· ${E(d.value || '')} · ${E(d.status || '')}</small></button>`).join('')}</div>`;
    if (ns.length) h += `<div class="ak-box ak-stories"><span class="lbl">${off ? 'Off-cycle stories' : 'Related stories'}</span>${ns.map(n => `<div class="ak-st">${sLink(n, `${E(n.title)} <small>· ${E(fmtD(n.date))}</small>`)}${storyTags(n)}${storyDates(n) ? `<small>${E(storyDates(n))}</small>` : ''}</div>`).join('')}${ns.some(n => n.unconf) ? '<small class="ak-note">Unconfirmed: reported by one smaller outlet so far, not yet confirmed by the company or the major or trade press.</small>' : ''}</div>`;
    const found = !!(pg.length || fx.length || al.length || pt.length || gd.length || live.length || pl.length || th.length || ns.length);
    if (!found) h = `<p class="ak-lead">I don't have that one on file yet. Try a fee name, a carrier or a company. Examples: “dim weight divisor”, “UPS additional handling”, “when do FedEx peak fees start”, “when was the 2026 UPS GRI announced”.</p>`;
    const ctx = [
      ...pg.map(p => `[Program] ${progText(p)}${p.changes.length ? ' Changes: ' + p.changes.map(c => c.t).join('; ') : ''}`),
      ...fx.map((f, i) => f.t + (stale[i] ? ` [Changed since: ${almText(stale[i])}]` : '')),
      ...al.map(e => `[Pricing history] ${almText(e)}`),
      ...pt.map(p => `[Year over year] ${p.t}: ${p.body}`),
      ...pl.map(p => `[Company] ${coText(p)}`),
      ...live.map(b => b.t || (b.list || []).map(x => x.t).join('; ')),
      ...gd.map(g => `[${g.car} guide: ${g.doc.n}, ${guideMeta(g)}] ${g.ex}`),
      ...ns.map(storyCtx),
    ];
    return { h, src, found, ctx, al, pl, ns };
  }

  /* ---- panel ---- */
  let dlg;
  function panel() {
    if (dlg) return dlg;
    dlg = document.createElement('div'); dlg.className = 'akwrap'; dlg.hidden = true;
    dlg.innerHTML = `<div class="akpanel" role="dialog" aria-modal="true" aria-labelledby="akT">
      <div class="akhd"><span class="xname" id="akT">Ask Coop</span><small>Answers from the carriers' guides, the pricing history, live fees and the news desk</small><button type="button" class="cm-x" data-akclose aria-label="Close">×</button></div>
      <form class="akform"><label class="sr" for="akQ">Your parcel question</label><input id="akQ" type="search" autocomplete="off" placeholder="e.g. How is dim weight calculated?"><button type="submit">Ask</button></form>
      <div class="akchips">${['How is dim weight calculated?', 'When was the 2026 UPS GRI announced?', 'Off-cycle changes this year', 'Fuel surcharge this week', 'When do peak fees start?', 'Where is FedEx headquartered?'].map(x => `<button type="button" data-akq="${E(x)}">${E(x)}</button>`).join('')}</div>
      <div class="akout" aria-live="polite"></div></div>`;
    document.body.appendChild(dlg);
    dlg.querySelector('form').addEventListener('submit', e => { e.preventDefault(); run(dlg.querySelector('#akQ').value); });
    dlg.addEventListener('click', e => {
      const c = e.target.closest('[data-akq]'); if (c) { dlg.querySelector('#akQ').value = c.dataset.akq; run(c.dataset.akq); return; }
      // story and company links are real #s= / #c= links (copyable); a tap opens them in the app
      const s = e.target.closest('a[data-aks]');
      if (s) { e.preventDefault(); e.stopPropagation(); const id = s.dataset.aks, mr = G('markRead'), os = G('openStory'); close(); if (mr) mr([id]); if (os) os(id); return; }
      const co = e.target.closest('a[data-akc]');
      if (co) { e.preventDefault(); e.stopPropagation(); const id = co.dataset.akc, oc = G('openCompany'); close(); if (oc) oc(id); return; }
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

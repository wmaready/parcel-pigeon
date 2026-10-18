/* Shared saved-company search. No remote research or invented company records. */
(function () {
  'use strict';
  const norm = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  window.ppCompanySearch = function (query, players, edges, realms) {
    const q = norm(query), compact = q.replace(/ /g, ''), tokens = q.split(/\s+/).filter(Boolean);
    if (!q) return [];
    const byId = new Map(players.map(p => [p.id, p]));
    const namesOf = p => [p.n, ...(p.al || []), p.tk].filter(Boolean);
    const contains = text => { const n = norm(text), ws = n.split(' '); return tokens.every(t => t.length <= 3 ? ws.includes(t) : n.includes(t)) || (compact.length > 3 && n.replace(/ /g, '').includes(compact)); };
    return players.map(p => {
      const names = namesOf(p);
      const exact = names.find(n => norm(n) === q || norm(n).replace(/ /g, '') === compact);
      if (exact) return { p, score: 0, reason: exact === p.n ? 'Company name' : 'Name / ticker: ' + exact };
      const name = names.find(n => norm(n).startsWith(q) || contains(n));
      if (name) return { p, score: 1, reason: name === p.n ? 'Company name' : 'Name / ticker: ' + name };
      const fields = [[p.hq, 'Headquarters'], [realms[p.realm], 'Sector'], [p.s || p.what, 'Company profile']];
      const field = fields.find(([text]) => text && contains(text));
      if (field) return { p, score: 2, reason: field[1] + ': ' + String(field[0]) };
      const relations = edges.filter(e => e.a === p.id || e.b === p.id);
      const related = relations.map(e => ({ e, other: byId.get(e.a === p.id ? e.b : e.a) })).find(x => x.other && namesOf(x.other).some(contains));
      if (related) return { p, score: 3, reason: 'Connection: ' + related.other.n + (related.e.t ? ' · ' + related.e.t : '') };
      const history = (p.hist || []).find(h => contains(h.t));
      if (history) return { p, score: 4, reason: 'History: ' + history.t };
      return null;
    }).filter(Boolean).sort((a, b) => a.score - b.score || a.p.n.localeCompare(b.p.n));
  };
})();
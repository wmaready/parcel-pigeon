// Pull the app's built-in data (stories, rate clock, deals, docs, brief, fuel) out of index.html into data/seed.json,
// so the auditor checks exactly what readers see. Usage: node pipeline/export_seed.js index.html data/seed.json
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const main = scripts.find(s => s.includes('const NEWS=['));
const data = main.slice(0, main.indexOf('/* ================= constants'));
const appConst = main.slice(main.indexOf('/* ================= constants'), main.indexOf('/* ================= helpers'));
const m = { exports: {} };
new Function('module', data + '\n' + appConst + '\nmodule.exports={NEWS,DATES,DEALS,DOCS,BRIEF,FUEL,FUELDB:typeof FUELDB!=="undefined"?FUELDB:[],PLAYERS:typeof PLAYERS!=="undefined"?PLAYERS:[],PEDGES:typeof PEDGES!=="undefined"?PEDGES:[]};')(m);
const o = m.exports;
const lastFuel = o.FUELDB.length ? o.FUELDB[o.FUELDB.length - 1][0] : null;
fs.writeFileSync(process.argv[3], JSON.stringify({ news: o.NEWS, clock: o.DATES, deals: o.DEALS, docs: o.DOCS, brief: o.BRIEF, players: o.PLAYERS, edges: o.PEDGES,
  fuel: { eff: o.FUEL.eff, last_week: lastFuel, current: o.FUEL.current } }, null, 1));
console.log(`seed: ${o.NEWS.length} stories, ${o.DATES.length} clock entries, ${o.DEALS.length} deals, ${o.DOCS.length} docs, ${o.PLAYERS.length} players`);

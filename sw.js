// Parcel Pigeon service worker: network first, so readers always get the latest news.
// The cached copy is only used when the phone is offline or the site answers with an error (a 404 or 500 is a failure,
// never shown as the page). Pages fall back to the saved app; images and data fall back to their own saved copy (never
// the app page, which would make a logo look broken). Every saved copy carries the time it was saved; when one is used,
// the page is told, so it can say "Offline — saved <time>".
// Page and data are versioned together: once a page has been served from the saved copy, that page's data requests also
// come from the saved copies first, so an old page never mixes with newer data (or the reverse) on a flaky connection.
// Doc watch's dated page pictures (data/snapshots/) are large proof files: network only, never cached.
// Scripts the page loads (company-foundation.js, company-search.js, mx.js, ask.js, map-assets/*) are cached on first use.
const C='pp-v35';
const OFFLINE=new Set();          // clients whose page came from the saved copy
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
const stamp=res=>{const h=new Headers(res.headers);h.set('x-pp-saved',String(Date.now()));
  return res.blob().then(b=>new Response(b,{status:res.status,statusText:res.statusText,headers:h}))};
const tell=(id,m)=>{if(!m||!id)return;const t=+m.headers.get('x-pp-saved')||null;
  self.clients.get(id).then(c=>c&&c.postMessage({type:'pp-offline',saved:t})).catch(()=>{})};
self.addEventListener('fetch',e=>{
  const r=e.request,u=new URL(r.url);if(r.method!=='GET'||u.origin!==location.origin)return;
  if(/\/data\/snapshots\//.test(u.pathname))return;             // network only
  const page=r.mode==='navigate',id=page?e.resultingClientId:e.clientId;
  // offline, a page falls back to the saved app; an error answer only to a saved copy of that same address
  const saved=exact=>caches.match(r,{ignoreSearch:!page}).then(m=>m||(page&&!exact?caches.match('./'):null));
  const fromSaved=fail=>saved(!!fail).then(m=>{if(m){if(page)OFFLINE.add(id);tell(id,m);return m}return fail||Response.error()});
  const net=()=>fetch(r).then(res=>{
    if(res.ok){const c=res.clone();stamp(c).then(s=>caches.open(C).then(x=>x.put(r,s))).catch(()=>{});if(page)OFFLINE.delete(id);return res}
    return fromSaved(res)})                                   // an error answer: the saved copy if there is one, else the error
    .catch(()=>fromSaved());
  // a page served from the saved copy reads its data from the saved copies too
  if(!page&&OFFLINE.has(id))e.respondWith(saved(true).then(m=>{if(m){tell(id,m);return m}return net()}));
  else e.respondWith(net());
});

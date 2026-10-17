// Parcel Pigeon service worker: network first, so readers always get the latest news.
// The cached copy is only used when the phone is offline. Pages fall back to the saved app; images and data fall back
// to their own saved copy (never the app page, which would make a logo look broken).
const C='pp-v29';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  const r=e.request;if(r.method!=='GET'||new URL(r.url).origin!==location.origin)return;
  const page=r.mode==='navigate';
  e.respondWith(fetch(r).then(res=>{if(res.ok){const c=res.clone();caches.open(C).then(x=>x.put(r,c))}return res})
    .catch(()=>caches.match(r,{ignoreSearch:!page}).then(m=>m||(page?caches.match('./'):Response.error()))));
});

/* Service worker minimo: rende il programma installabile sul telefono e mostra una pagina
   di cortesia se manca la connessione. I dati finanziari NON vengono salvati sul dispositivo. */
const CACHE = "nureal-shell-v2";
const OFFLINE = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, "/icon-192.png"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || req.mode !== "navigate") return; // le chiamate ai dati passano sempre dalla rete
  event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
});

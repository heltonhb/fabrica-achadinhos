/*
 * sw.js — Service worker do Painel da Vitrine (PWA).
 *
 * Estratégia:
 *  - index.html: network-first (sempre a versão nova quando online) com
 *    fallback pro cache quando offline. O backend já manda no-cache.
 *  - Manifest/ícones: cache-first (raramente mudam).
 *  - /api/metricas: network-first; em falha devolve o último JSON salvo
 *    (com offline:true e cacheado_em) pra exibir badge "Offline · dados de HH:MM".
 *  - /api/checar-pin: nunca cacheado (login sempre no servidor; offline o
 *    front já trata com PIN salvo).
 */

const CACHE = 'painel-v4';
const ESTATICOS = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];

self.addEventListener('install', (e) => {
    e.waitUntil(
        caches.open(CACHE).then((c) => c.addAll(ESTATICOS)).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys()
            .then((chaves) => Promise.all(chaves.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (e) => {
    const url = new URL(e.request.url);

    if (e.request.method !== 'GET') return;

    // Login não usa cache — PIN sempre validado no servidor.
    if (url.pathname === '/api/checar-pin') return;

    // Métricas: rede primeiro, cache como fallback offline.
    if (url.pathname === '/api/metricas') {
        e.respondWith(
            fetch(e.request)
                .then(async (res) => {
                    // Guarda no cache com marca de tempo pra exibir "dados de HH:MM".
                    const corpo = JSON.stringify({
                        ...(await res.clone().json()),
                        cacheado_em: new Date().toISOString(),
                    });
                    const cache = await caches.open(CACHE);
                    await cache.put(
                        e.request,
                        new Response(corpo, { headers: { 'Content-Type': 'application/json' } })
                    );
                    return res;
                })
                .catch(async () => {
                    const salvo = await caches.match(e.request);
                    if (salvo) {
                        const dados = await salvo.json();
                        return new Response(JSON.stringify({ ...dados, offline: true }), {
                            headers: { 'Content-Type': 'application/json' },
                        });
                    }
                    return new Response(JSON.stringify({ sucesso: false, detail: 'offline' }), {
                        status: 503,
                        headers: { 'Content-Type': 'application/json' },
                    });
                })
        );
        return;
    }

    // index.html: network-first — usuário online sempre vê a versão nova;
    // offline devolve a última versão cacheada.
    if (url.pathname === '/' || url.pathname === '/index.html') {
        e.respondWith(
            fetch(e.request)
                .then(async (res) => {
                    const cache = await caches.open(CACHE);
                    await cache.put('/', res.clone());
                    return res;
                })
                .catch(async () => {
                    const cache = await caches.open(CACHE);
                    return (await cache.match('/')) || (await cache.match(e.request));
                })
        );
        return;
    }

    // Estáticos: cache-first.
    e.respondWith(
        caches.match(e.request).then((salvo) => {
            const buscar = fetch(e.request)
                .then((res) => {
                    if (res.ok && url.origin === self.location.origin) {
                        const copia = res.clone();
                        caches.open(CACHE).then((c) => c.put(e.request, copia));
                    }
                    return res;
                })
                .catch(() => salvo);
            return salvo || buscar;
        })
    );
});

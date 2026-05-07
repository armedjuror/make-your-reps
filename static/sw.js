/**
 * Make Your Reps — Service Worker
 * Minimal SW: satisfies PWA installability without aggressive caching
 * (server-rendered Django app — HTML must always be fresh from network)
 */

const CACHE = 'myr-static-v1.5';

// Cache only immutable static assets on install
self.addEventListener('install', e => {
    self.skipWaiting();
    e.waitUntil(
        caches.open(CACHE).then(cache => cache.addAll([
            '/static/board/css/style.css',
            '/static/board/css/dashboard.css',
            '/static/images/logo.png',
        ]).catch(() => {}))
    );
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);

    // Always fetch HTML from network (keeps auth + fresh content)
    if (e.request.mode === 'navigate' || e.request.headers.get('accept')?.includes('text/html')) {
        e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
        return;
    }

    // Cache-first for static assets
    if (url.pathname.startsWith('/static/')) {
        e.respondWith(
            caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
                const clone = res.clone();
                caches.open(CACHE).then(c => c.put(e.request, clone));
                return res;
            }))
        );
        return;
    }

    // Network-first for everything else (API calls etc.)
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});


/**
 * Make Your Reps — Service Worker
 * Minimal SW: satisfies PWA installability without aggressive caching
 * (server-rendered Django app — HTML must always be fresh from network)
 */

const CACHE = 'myr-static-v1.2';

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

// ── Push Notifications ──────────────────────────────────────────────────────

self.addEventListener('push', e => {
    if (!e.data) return;
    let data = {};
    try { data = e.data.json(); } catch { data = { title: 'Steps', body: e.data.text() }; }

    e.waitUntil(
        self.registration.showNotification(data.title || 'Steps', {
            body: data.body || '',
            icon: '/static/images/logo.png',
            badge: '/static/images/logo.png',
            data: { url: data.url || '/board/' },
            vibrate: [150, 50, 150],
        })
    );
});

self.addEventListener('notificationclick', e => {
    e.notification.close();
    const data = e.notification.data || {};
    const url = data.url || '/board/';
    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
            for (const client of list) {
                if (client.url.includes('/board/') && 'focus' in client) {
                    // Tell the open tab to switch pane if we have one
                    if (data.pane) {
                        client.postMessage({ type: 'SWITCH_PANE', pane: data.pane, subTab: data.subTab || null });
                    }
                    return client.focus();
                }
            }
            return clients.openWindow(url);
        })
    );
});

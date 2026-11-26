/**
 * analytics.js — product analytics: time per pane / modal, and which controls get used.
 * Shared verbatim by the web app and the Chrome extension (copy it across unchanged).
 *
 * Events go to our own api/track/, which forwards them to PostHog for the signed-in
 * user. Nothing user-written is ever sent: only pane and modal ids, and code-level
 * names for controls (the onclick handler, data-track, data-pane or an element id).
 *
 * Time only counts while the tab is visible and the user has touched the page in the
 * last two minutes, so a board left open overnight doesn't look like eight hours of use.
 */
const Analytics = (() => {
    const IDLE_MS = 120000;          // time after the last input still counted (reading); beyond it = idle
    const FLUSH_MS = 30000;
    const MAX_SEGMENT_S = 1800;
    const MAX_QUEUE = 200;
    const SESSION_GAP_MS = 30 * 60 * 1000;

    const isExtension = location.protocol === 'chrome-extension:';
    const client = isExtension ? 'extension'
        : /MakeYourRepsAndroid/.test(navigator.userAgent) ? 'android'
        : (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone ? 'pwa'
        : 'web';

    let started = false;
    let queue = [];
    let clicks = {};
    let pane = null;
    let modals = [];                 // open Bootstrap modals, topmost last
    let segStart = null;
    let lastInput = Date.now();
    let idle = false;

    const safe = s => String(s).replace(/\d+/g, 'N').replace(/[^\w:.\-#/ ]/g, '').slice(0, 80);
    const currentView = () => modals.length ? `modal:${modals[modals.length - 1]}` : (pane ? `pane:${pane}` : null);

    function push(event, properties) {
        if (queue.length < MAX_QUEUE) queue.push({ event, properties, ts: Date.now() });
    }

    function closeSegment(reason, endAt) {
        if (segStart === null) return;
        const view = currentView();
        const seconds = Math.min((Math.max(endAt || Date.now(), segStart) - segStart) / 1000, MAX_SEGMENT_S);
        segStart = null;
        if (view && seconds >= 1) {
            push('view_time', { view, kind: view.split(':')[0], seconds: Math.round(seconds * 10) / 10, ended: reason });
        }
    }

    function openSegment() {
        if (started && !idle && segStart === null && document.visibilityState === 'visible') segStart = Date.now();
    }

    function changeView(mutate, reason) {
        closeSegment(reason);
        mutate();
        openSegment();
    }

    // ── Input / idle ──
    function onInput() {
        lastInput = Date.now();
        if (idle) { idle = false; openSegment(); }
    }

    function checkIdle() {
        if (!idle && Date.now() - lastInput > IDLE_MS) {
            idle = true;
            closeSegment('idle', lastInput + IDLE_MS);
        }
    }

    // ── Controls ──
    function controlKey(el) {
        if (el.dataset.track) return el.dataset.track;
        const handler = (el.getAttribute('onclick') || '').match(/^\s*(?:return\s+)?([\w$.]+)\s*\(/);
        if (handler) return handler[1];
        if (el.dataset.pane) return `nav:${el.dataset.pane}`;
        if (el.dataset.bsTarget) return `open:${el.dataset.bsTarget}`;
        if (el.id) return `#${el.id}`;
        return null;
    }

    function onClick(e) {
        if (!started || !e.target.closest) return;
        const el = e.target.closest('[data-track], [onclick], [data-pane], [data-bs-target], button[id], a[id], input[id]');
        if (!el) return;
        const key = controlKey(el);
        if (!key) return;
        const k = `${safe(key)}|${currentView() || 'none'}`;
        clicks[k] = (clicks[k] || 0) + 1;
    }

    // ── Sending ──
    function drain() {
        Object.entries(clicks).forEach(([k, count]) => {
            const [action, view] = k.split('|');
            push('ui_click', { action, view, count: Math.min(count, 1000) });
        });
        clicks = {};
        const batch = queue;
        queue = [];
        return batch;
    }

    async function flush() {
        if (!started || typeof apiClient === 'undefined') return;
        const events = drain();
        if (!events.length) return;
        const res = await apiClient.post('api/track/', { client, events }, { silent: true });
        if (!res || res.status !== 'success') queue = events.concat(queue).slice(-MAX_QUEUE);
    }

    // Page going away: fetch with keepalive outlives the page and can carry auth headers
    function flushOnExit() {
        if (!started) return;
        const events = drain();
        if (!events.length) return;
        const token = typeof apiClient !== 'undefined' ? apiClient.getAccessToken() : null;
        const csrf = !isExtension && typeof apiClient !== 'undefined' && apiClient.getCSRFToken ? apiClient.getCSRFToken() : null;
        try {
            fetch(`${HOST}api/track/`, {
                method: 'POST',
                keepalive: true,
                credentials: isExtension ? 'omit' : 'include',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token && { Authorization: `Bearer ${token}` }),
                    ...(csrf && { 'X-CSRFToken': csrf }),
                },
                body: JSON.stringify({ client, events }),
            });
        } catch (e) { /* dropped; analytics is best-effort */ }
    }

    function tick() {
        checkIdle();
        // Report long sessions progressively so a crashed tab loses at most one interval
        if (segStart !== null) { closeSegment('roll', Math.min(Date.now(), lastInput + IDLE_MS)); openSegment(); }
        flush();
    }

    function appOpened() {
        let last = 0;
        try { last = Number(localStorage.getItem('myr_last_open') || 0); localStorage.setItem('myr_last_open', String(Date.now())); } catch (e) { /* storage blocked */ }
        if (Date.now() - last < SESSION_GAP_MS) return;
        let version;
        try { version = isExtension && chrome.runtime.getManifest().version; } catch (e) { /* not an extension */ }
        push('app_opened', {
            pane: pane || 'home',
            display_mode: client,
            viewport: window.innerWidth < 768 ? 'mobile' : window.innerWidth < 1200 ? 'tablet' : 'desktop',
            ...(version && { app_version: version }),
            ...(Intl.DateTimeFormat && { tz: safe(Intl.DateTimeFormat().resolvedOptions().timeZone || '') }),
        });
    }

    return {
        client,

        /** Call once the user is known to be signed in (after AppConfig loads). */
        start(initialPane) {
            if (started) return;
            started = true;
            pane = initialPane || 'home';
            appOpened();
            openSegment();

            ['pointerdown', 'keydown', 'wheel', 'touchstart', 'mousemove'].forEach(ev =>
                document.addEventListener(ev, onInput, { passive: true, capture: true }));
            document.addEventListener('click', onClick, { capture: true });
            document.addEventListener('shown.bs.modal', e => changeView(() => modals.push(safe(e.target.id || 'modal')), 'modal'));
            document.addEventListener('hidden.bs.modal', e => changeView(() => {
                const i = modals.lastIndexOf(safe(e.target.id || 'modal'));
                if (i >= 0) modals.splice(i, 1);
            }, 'modal'));
            document.addEventListener('visibilitychange', () => {
                if (document.visibilityState === 'hidden') { closeSegment('hidden'); flushOnExit(); }
                else { lastInput = Date.now(); idle = false; openSegment(); }
            });
            window.addEventListener('pagehide', () => { closeSegment('exit'); flushOnExit(); });
            setInterval(tick, FLUSH_MS);
        },

        /** Called by switchPane(). */
        pane(name) {
            if (!started || name === pane) return;
            changeView(() => { pane = name; modals = []; }, 'switch');
        },

        /** Name a control explicitly when it has no onclick/id (or use data-track="..."). */
        action(name) {
            if (!started) return;
            const k = `${safe(name)}|${currentView() || 'none'}`;
            clicks[k] = (clicks[k] || 0) + 1;
        },
    };
})();

document.addEventListener('appConfigLoaded', () => {
    if (typeof AppConfig !== 'undefined' && AppConfig.userDetail) {
        Analytics.start(typeof currentPane !== 'undefined' ? currentPane : 'home');
    }
});

/**
 * notifications.js — Browser notification utility + timeline event notifier
 */

const BrowserNotify = {
    _notifiedIds: new Set(),
    _pollerInterval: null,

    // Must be called from a user gesture (click) for Chrome to show the permission prompt
    async requestPermission() {
        if (!('Notification' in window)) return;
        if (Notification.permission !== 'granted') {
            await Notification.requestPermission();
        }
        this.updatePermissionUI();
        if (Notification.permission === 'granted') {
            await this.subscribePush();
        }
    },

    async subscribePush({ force = false } = {}) {
        if (!('PushManager' in window) || !('serviceWorker' in navigator)) {
            return { ok: false, reason: 'Push not supported on this browser/device.' };
        }
        if (Notification.permission !== 'granted') {
            return { ok: false, reason: 'Notification permission not granted.' };
        }
        try {
            const reg = await navigator.serviceWorker.ready;
            const keyRes = await apiClient.get('board/api/push/vapid-key/');
            if (!keyRes.public_key) {
                return { ok: false, reason: 'VAPID public key not configured on server.' };
            }
            const appKey = this._urlBase64ToUint8Array(keyRes.public_key);

            const existing = await reg.pushManager.getSubscription();
            if (existing && !force) {
                await this._sendSubscriptionToServer(existing);
                return { ok: true };
            }
            // Force-unsubscribe so we get a fresh subscription with the current VAPID key
            if (existing) await existing.unsubscribe();

            const subscription = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: appKey,
            });
            await this._sendSubscriptionToServer(subscription);
            return { ok: true };
        } catch (e) {
            console.error('[Push] Subscribe failed:', e);
            return { ok: false, reason: e.message || String(e) };
        }
    },

    async _sendSubscriptionToServer(subscription) {
        const sub = subscription.toJSON();
        await apiClient.post('board/api/push/subscribe/', {
            endpoint: sub.endpoint,
            keys: sub.keys,
        });
    },

    _urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const raw = atob(base64);
        return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
    },

    updatePermissionUI() {
        const btn = document.getElementById('notif-permission-btn');
        const status = document.getElementById('notif-permission-status');
        if (!btn || !status) return;
        const p = ('Notification' in window) ? Notification.permission : 'unsupported';
        if (p === 'granted') {
            btn.style.display = 'none';
            status.textContent = 'Browser notifications are enabled.';
        } else if (p === 'denied') {
            btn.style.display = 'none';
            status.textContent = 'Notifications blocked. Enable them in your browser site settings.';
        } else {
            btn.style.display = '';
            status.textContent = '';
        }
    },

    send(title, body, options = {}) {
        if (!('Notification' in window) || Notification.permission !== 'granted') return;
        const { pane, subTab, ...notifOptions } = options;
        const swOptions = {
            body,
            icon: '/static/images/logo.png',
            data: { pane, subTab },
            ...notifOptions,
        };
        // Mobile browsers require showNotification via service worker
        // (new Notification() is unsupported or restricted on mobile)
        if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
            navigator.serviceWorker.ready
                .then(reg => reg.showNotification(title, swOptions))
                .catch(e => console.error('[BrowserNotify] SW notify failed:', e));
            return;
        }
        // Desktop fallback
        try {
            const n = new Notification(title, swOptions);
            n.onclick = () => {
                window.focus();
                n.close();
                if (pane && typeof switchPane === 'function') switchPane(pane, subTab || null);
            };
        } catch (e) {
            console.error('[BrowserNotify] Failed:', e);
        }
    },

    startTimelinePoller() {
        this._pollTimeline();
        this._pollerInterval = setInterval(() => this._pollTimeline(), 60_000);
    },

    stopTimelinePoller() {
        clearInterval(this._pollerInterval);
    },

    async _pollTimeline() {
        if (!('Notification' in window) || Notification.permission !== 'granted') return;
        try {
            const today = getDate(new Date());
            const res = await apiClient.get(`board/api/timeline/?date=${today}&limit=100`, { silent: true });
            if (res.status !== 'success') return;

            const now = Date.now();
            const WINDOW_MS = 2 * 60 * 1000;

            for (const event of res.data) {
                if (this._notifiedIds.has(event.id)) continue;
                const diff = new Date(event.timestamp).getTime() - now;
                if (diff >= -WINDOW_MS && diff <= WINDOW_MS) {
                    const { pane, subTab } = this._paneForType(event.event_type);
                    this.send(this._titleForType(event.event_type), event.event, { pane, subTab });
                    this._notifiedIds.add(event.id);
                }
            }
        } catch (e) {
            console.error('[BrowserNotify] Poll error:', e);
        }
    },

    _paneForType(type) {
        const map = {
            habit:                  { pane: 'trackers' },
            sleep_tracker:          { pane: 'trackers' },
            accountability_habit:   { pane: 'trackers' },
            todo:                   { pane: 'todos' },
            journal:                { pane: 'journals' },
            friend_request:         { pane: 'others', subTab: 'friends' },
            accountability_invite:  { pane: 'others', subTab: 'friends' },
        };
        return map[type] || { pane: 'home' };
    },

    _titleForType(type) {
        const map = {
            habit: 'Habit Reminder', todo: 'Task Due', routine: 'Routine',
            sleep_tracker: 'Sleep Tracker', journal: 'Journal Time', text: 'Reminder',
            meeting: 'Meeting', friend_request: 'Friend Request',
            accountability_invite: 'Accountability Invite',
            accountability_habit: 'Accountability Check',
        };
        return map[type] || 'Steps';
    },
};

(function initNotificationTestButtons() {
    const statusEl = () => document.getElementById('test-notif-status');

    const setStatus = (msg, ok = true) => {
        const el = statusEl();
        if (!el) return;
        el.textContent = msg;
        el.style.color = ok ? 'var(--ink-brown)' : 'var(--danger, #c0392b)';
        setTimeout(() => { if (el) el.textContent = ''; }, 4000);
    };

    document.getElementById('test-browser-notif-btn')?.addEventListener('click', () => {
        if (Notification.permission !== 'granted') {
            setStatus('Enable browser notifications first.', false);
            return;
        }
        BrowserNotify.send('Make Your Reps', 'Browser notifications are working!', { pane: 'home' });
        setStatus('Browser notification sent.');
    });

    document.getElementById('test-push-notif-btn')?.addEventListener('click', async () => {
        const btn = document.getElementById('test-push-notif-btn');
        btn.disabled = true;

        // Force SW update so push handlers are definitely active
        if ('serviceWorker' in navigator) {
            const reg = await navigator.serviceWorker.getRegistration();
            if (reg) await reg.update();
        }

        setStatus('Registering push subscription…');
        const sub = await BrowserNotify.subscribePush({ force: true });
        if (!sub.ok) {
            btn.disabled = false;
            setStatus('Subscription failed: ' + sub.reason, false);
            return;
        }

        setStatus('Sending test push…');
        const res = await apiClient.post('board/api/push/test/');
        btn.disabled = false;
        if (res.status === 'success') {
            setStatus('Push sent — you should receive a notification shortly.');
        } else {
            setStatus(res.message || 'Push failed. Check VAPID keys are configured.', false);
        }
    });
}());


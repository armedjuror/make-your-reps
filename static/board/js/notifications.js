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
        try {
            new Notification(title, {
                body,
                icon: '/static/images/logo.png',
                ...options,
            });
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
            const today = new Date().toISOString().slice(0, 10);
            const res = await apiClient.get(`board/api/timeline/?date=${today}&limit=100`, { silent: true });
            if (res.status !== 'success') return;

            const now = Date.now();
            const WINDOW_MS = 2 * 60 * 1000;

            for (const event of res.data) {
                if (this._notifiedIds.has(event.id)) continue;
                const diff = new Date(event.timestamp).getTime() - now;
                if (diff >= -WINDOW_MS && diff <= WINDOW_MS) {
                    this.send(this._titleForType(event.event_type), event.event);
                    this._notifiedIds.add(event.id);
                }
            }
        } catch (e) {
            console.error('[BrowserNotify] Poll error:', e);
        }
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

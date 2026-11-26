/**
 * Make Your Reps — Service Worker
 *
 * Kept only so the app stays installable as a PWA. It does not intercept or
 * cache anything: a worker that cached JS/CSS kept serving old files after
 * every deploy, and one that answered page loads failed whenever the network
 * request was interrupted. The browser now loads everything itself.
 *
 * On activate it deletes every cache an older version created.
 */

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

// A fetch handler that never calls respondWith(): every request goes straight
// to the network, exactly as if there were no service worker.
self.addEventListener('fetch', () => {});

// ─── Page-side helpers for the Android wrapper ─────────────────────────────
// These touch `window`, which does not exist inside a service worker. Left at
// the top level they threw while the worker was evaluated, so the browser
// rejected every new sw.js and kept an old cached worker alive. They only run
// when this file is loaded in a page.
if (typeof window !== 'undefined') {
    // ─── Helper: check if running in native wrapper ───────────────────────────
    const isAndroidApp = () => typeof window.Android !== 'undefined';

    // ─── Schedule a notification ─────────────────────────────────────────────
    // id: unique string identifier
    // title: notification title
    // body: notification body text
    // epochMillis: Unix timestamp in milliseconds when to fire
    function scheduleTimelineNotification(id, title, body, date) {
      if (isAndroidApp()) {
        window.Android.scheduleNotification(id, title, body, date.getTime());
      }
    }

    // ─── Cancel a notification ────────────────────────────────────────────────
    function cancelScheduledNotification(id) {
      if (isAndroidApp()) {
        window.Android.cancelNotification(id);
      }
    }

    // ─── Pomodoro notifications ───────────────────────────────────────────────
    // sessionDurationMs: e.g. 25 * 60 * 1000 for 25 minutes
    // breakDurationMs: e.g. 5 * 60 * 1000 for 5 minutes
    function startPomodoroNotifications(id, sessionLabel, sessionDurationMs, breakDurationMs) {
      if (isAndroidApp()) {
        window.Android.schedulePomodoroNotification(
          id,
          sessionLabel,
          sessionDurationMs,
          breakDurationMs
        );
      }
    }

    // ─── Update Pomodoro widget ───────────────────────────────────────────────
    // Call this every tick of your Pomodoro timer to keep widget in sync
    function syncPomodoroWidget(label, timeRemainingFormatted, isRunning) {
      if (isAndroidApp()) {
        window.Android.updatePomodoroWidget(JSON.stringify({
          label: label,                  // e.g. "Focus Session"
          timeRemaining: timeRemainingFormatted, // e.g. "24:30"
          isRunning: isRunning           // boolean
        }));
      }
    }

    // ─── Update Timeline widget ───────────────────────────────────────────────
    // Call this whenever your timeline data changes
    function syncTimelineWidget(events) {
      if (isAndroidApp()) {
        // events: array of { title: string, time: string, type: string }
        // Only first 3 will be shown
        window.Android.updateTimelineWidget(JSON.stringify(events));
      }
    }

    // ─── Request notification permission ─────────────────────────────────────
    function requestNotificationPermission() {
      if (isAndroidApp()) {
        window.Android.requestNotificationPermission();
      }
    }

    // Listen for permission result
    window.addEventListener('notificationPermissionResult', (e) => {
      if (e.detail.granted) {
        console.log('Notification permission granted');
      } else {
        console.log('Notification permission denied');
      }
    });

    // ─── Get FCM Token ────────────────────────────────────────────────────────
    // Call this on app init and send token to your backend
    function registerForPushNotifications() {
      if (isAndroidApp()) {
        const token = window.Android.getDeviceFCMToken();
        if (token) {
          // Send to your backend
          fetch('/api/register-device', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, platform: 'android' })
          });
        }
      }
    }

    // ─── Handle widget button actions ─────────────────────────────────────────
    // When user taps Start/Pause/Stop on the widget, the app opens with:
    // URL: makeyourreps://pomodoro?action=start|pause|stop
    // Your router should handle this path and trigger the appropriate Pomodoro action

    // Example with React Router / hash routing:
    window.addEventListener('DOMContentLoaded', () => {
      // Parse the URL the app was opened with
      const url = new URL(window.location.href);
      const action = url.searchParams.get('action');
      if (action && window.location.pathname === '/pomodoro') {
        // Trigger the action in your Pomodoro component
        window.dispatchEvent(new CustomEvent('pomodoroWidgetAction', { detail: { action } }));
      }
    });
}

// ── Squads: web push ──
self.addEventListener('push', (event) => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'makeyourreps', body: event.data && event.data.text() }; }
    event.waitUntil(self.registration.showNotification(data.title || 'makeyourreps', {
        body: data.body || '',
        icon: '/static/images/logo.png',
        badge: '/static/images/logo.png',
        tag: data.tag || undefined,
        data: { url: data.url || '/board/' },
    }));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/board/';
    event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
        for (const c of list) {
            if (c.url.includes('/board/') && 'focus' in c) { c.navigate(url); return c.focus(); }
        }
        return clients.openWindow(url);
    }));
});

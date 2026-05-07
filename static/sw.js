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
"""
Product analytics, sent to PostHog from the server.

Every client (web, PWA, Chrome extension, future Android app) posts its UI events to
/api/track/ and the server forwards them here, so identity comes from the session (no
client-side identify), ad blockers don't drop events, and no third-party script runs
next to journals or private items.

Server-side feature events (habit_logged, todo_completed, ...) come from
main/analytics_signals.py, so they're counted the same whichever client made the change.

Everything is a no-op when POSTHOG_API_KEY is unset (local dev, tests, self-hosters).
"""
import contextvars
import logging
import threading

from django.conf import settings

log = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()

# Which client the current request came from; set by AnalyticsClientMiddleware
current_client = contextvars.ContextVar('myr_client', default='server')

CLIENTS = ('web', 'pwa', 'extension', 'android', 'mcp', 'server')


def enabled():
    return bool(getattr(settings, 'POSTHOG_API_KEY', ''))


def get_client():
    """Lazily build one PostHog client per process (after any gunicorn/celery fork)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from posthog import Posthog
                key = getattr(settings, 'POSTHOG_API_KEY', '')
                _client = Posthog(
                    key or 'disabled',
                    host=getattr(settings, 'POSTHOG_HOST', 'https://us.i.posthog.com'),
                    disabled=not key,
                    disable_geoip=True,
                    flush_interval=2.0,
                    max_retries=2,
                    timeout=5,
                )
    return _client


def capture(user_id, event, properties=None, ip=None, timestamp=None):
    """Queue one event for a user. Never raises; analytics must not break a request."""
    if not enabled() or not user_id:
        return
    props = {'client': current_client.get()}
    props.update(properties or {})
    if ip:
        props['$ip'] = ip
    try:
        get_client().capture(
            event,
            distinct_id=str(user_id),
            properties=props,
            timestamp=timestamp,
            disable_geoip=not ip,
        )
    except Exception:  # pragma: no cover - network/SDK failure
        log.exception('posthog capture failed: %s', event)


def identify(user):
    """Keep the PostHog person in step with the account (used to filter staff and cohorts)."""
    if not enabled() or not user or not user.pk:
        return
    try:
        get_client().set(
            distinct_id=str(user.pk),
            properties={
                'email': user.email,
                'name': user.get_full_name() or user.username,
                'is_staff': bool(user.is_staff or user.is_superuser),
                'date_joined': user.date_joined.isoformat() if user.date_joined else None,
            },
        )
    except Exception:  # pragma: no cover
        log.exception('posthog identify failed')


def detect_client(request):
    """Best guess at the client from request headers alone. The browser can refine it."""
    explicit = (request.META.get('HTTP_X_MYR_CLIENT') or '').lower()
    if explicit in CLIENTS:
        return explicit
    origin = request.META.get('HTTP_ORIGIN', '')
    if origin.startswith('chrome-extension://'):
        return 'extension'
    ua = request.META.get('HTTP_USER_AGENT', '')
    if 'MakeYourRepsAndroid' in ua or ('; wv)' in ua and 'Android' in ua):
        return 'android'
    return 'web'

"""Web Push notification helper using VAPID / pywebpush."""
import json

from django.conf import settings


def _webpush_one(sub, payload):
    """Send payload to a single PushSubscription. Returns None on success, error string on failure."""
    from pywebpush import webpush, WebPushException
    try:
        webpush(
            subscription_info={
                'endpoint': sub.endpoint,
                'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims=settings.VAPID_CLAIMS,
        )
        return None
    except Exception as e:
        return str(e)


def send_push_to_user(user, title, body, url='/board/'):
    """Send a push notification to all active subscriptions for a user."""
    from board.models import PushSubscription

    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return

    payload = json.dumps({'title': title, 'body': body, 'url': url})
    stale = []

    for sub in PushSubscription.objects.filter(user=user):
        err = _webpush_one(sub, payload)
        if err:
            # 404 / 410 = subscription expired; delete it
            if '404' in err or '410' in err:
                stale.append(sub.pk)

    if stale:
        PushSubscription.objects.filter(pk__in=stale).delete()


def send_push_test(user):
    """
    Like send_push_to_user but raises on first error so the test endpoint
    can surface the real reason to the frontend.
    """
    from board.models import PushSubscription

    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        raise RuntimeError('VAPID keys not configured on the server.')

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        raise RuntimeError('pywebpush is not installed.')

    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        raise RuntimeError('No push subscription found for this user.')

    payload = json.dumps({'title': 'Make Your Reps — Test', 'body': 'Push notifications are working!', 'url': '/board/'})
    last_err = None
    stale = []

    for sub in subs:
        err = _webpush_one(sub, payload)
        if err:
            if '404' in err or '410' in err:
                stale.append(sub.pk)
            last_err = err
        else:
            last_err = None  # at least one succeeded

    if stale:
        PushSubscription.objects.filter(pk__in=stale).delete()

    if last_err is not None and len(stale) == len(subs):
        raise RuntimeError(f'Push failed: {last_err}')

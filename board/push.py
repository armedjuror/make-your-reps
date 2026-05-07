"""Web Push notification helper using VAPID / pywebpush."""
import json

from django.conf import settings


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
        except Exception as e:
            # 404 / 410 mean the subscription is gone — clean it up
            resp = getattr(getattr(e, 'response', None), 'status_code', None)
            if resp in (404, 410):
                stale.append(sub.pk)

    if stale:
        PushSubscription.objects.filter(pk__in=stale).delete()

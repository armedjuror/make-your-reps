"""
Notifications. Web push is the primary channel until the native app ships
(then FCM); email is the fallback for anything time-sensitive.

Controls:
* Per-squad mute silences everything except being added and calendar events.
* Quiet hours per user: queued pushes deliver after quiet hours unless stale
  (at-risk alerts are dropped, not delayed).
* Daily cap per user across all squads (default 6). Lowest priority is dropped
  first: recap < reactions < nudges < at-risk. Each lower priority keeps one
  more slot free for the ones above it.
"""
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import escape

logger = logging.getLogger(__name__)

# kind: (priority, channels, mute_exempt, stale_when_delayed, time_sensitive)
KINDS = {
    'recap':               (0, ['push', 'email'], False, False, False),
    'reaction':            (1, ['push'], False, False, False),
    'nudge':               (2, ['push'], False, False, True),
    'at_risk':             (3, ['push'], False, True, True),
    'challenge_at_risk':   (3, ['push'], False, True, True),
    'challenge_dropped':   (4, ['push'], False, False, False),
    'focus_start':         (6, ['push'], False, True, True),
    'challenge_completed': (8, ['push', 'email'], False, False, False),
    'added':               (9, ['push', 'email'], True, False, True),
    'calendar':            (9, [], True, False, False),
    'upgrade':             (9, ['inapp', 'email'], True, False, False),
}
CAP_RESERVE = {0: 3, 1: 2, 2: 1, 3: 0}   # priority -> slots kept free for higher priorities


def prefs_for(user_id):
    from squads.models import NotificationPrefs
    p, _ = NotificationPrefs.objects.get_or_create(user_id=user_id)
    return p


def _tz(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(settings.TIME_ZONE)


def in_quiet_hours(prefs, now=None):
    """(True, quiet_end_datetime) when ``now`` falls inside the user's quiet hours."""
    if not prefs.quiet_start or not prefs.quiet_end:
        return False, None
    local = (now or timezone.now()).astimezone(_tz(prefs.timezone))
    t, start, end = local.time(), prefs.quiet_start, prefs.quiet_end
    inside = (start <= t < end) if start < end else (t >= start or t < end)
    if not inside:
        return False, None
    end_day = local.date() if t < end else local.date() + timedelta(days=1)
    return True, datetime.combine(end_day, end, tzinfo=local.tzinfo)


def pushes_sent_today(user_id, prefs, now=None):
    from squads.models import NotificationLog
    local = (now or timezone.now()).astimezone(_tz(prefs.timezone))
    day_start = datetime.combine(local.date(), datetime.min.time(), tzinfo=local.tzinfo)
    capped = [k for k, v in KINDS.items() if v[0] < 9 and 'push' in v[1]]
    return NotificationLog.objects.filter(user_id=user_id, status='sent', sent_at__gte=day_start,
                                          kind__in=capped).count()


def notify(user_or_id, kind, title, body='', url='', board=None, now=None):
    """Record, then deliver now, queue past quiet hours, or drop. Returns the NotificationLog."""
    from squads import flags
    from squads.models import BoardMembership, NotificationLog
    user_id = getattr(user_or_id, 'id', user_or_id)
    priority, channels, mute_exempt, stale, time_sensitive = KINDS.get(kind, (2, ['push'], False, False, False))
    now = now or timezone.now()
    log = NotificationLog(user_id=user_id, board=board, kind=kind, title=title[:160], body=body[:400],
                          url=url[:400], channels=list(channels))
    if not flags.enabled('notifications') and kind not in ('calendar', 'upgrade'):
        log.status, log.reason = 'dropped', 'flag_off'
        log.save()
        return log
    if board is not None and not mute_exempt and BoardMembership.objects.filter(
            board=board, user_id=user_id, muted=True).exists():
        log.status, log.reason = 'muted', 'squad_muted'
        log.save()
        return log

    prefs = prefs_for(user_id)
    if 'push' in channels and priority in CAP_RESERVE:
        budget = prefs.daily_cap - CAP_RESERVE[priority]
        if pushes_sent_today(user_id, prefs, now) >= budget:
            log.status, log.reason = 'dropped', 'daily_cap'
            log.save()
            return log

    quiet, quiet_end = in_quiet_hours(prefs, now)
    if quiet and priority < 9:
        if stale:
            log.status, log.reason = 'dropped', 'quiet_hours_stale'
            log.save()
            return log
        log.status, log.reason, log.deliver_after = 'queued', 'quiet_hours', quiet_end
        log.save()
        return log

    log.save()
    _deliver(log, time_sensitive)
    return log


def _deliver(log, time_sensitive=None):
    from squads.models import PushSubscription
    if time_sensitive is None:
        time_sensitive = KINDS.get(log.kind, (0, [], False, False, False))[4]
    sent = []
    subs = list(PushSubscription.objects.filter(user_id=log.user_id))
    if 'push' in log.channels and subs:
        payload = json.dumps({'title': log.title, 'body': log.body, 'url': log.url or '/board/',
                              'tag': f'{log.kind}-{log.board_id or 0}'})
        if any(send_webpush(s, payload) for s in subs):
            sent.append('push')
    want_email = 'email' in log.channels or ('push' in log.channels and time_sensitive and 'push' not in sent)
    if want_email and log.user.email:
        if send_email(log.user.email, log.title, log.body, log.url):
            sent.append('email')
    if 'inapp' in log.channels:
        sent.append('inapp')
    log.status = 'sent'
    log.sent_at = timezone.now()
    log.channels = sent      # what actually went out
    log.save(update_fields=['status', 'sent_at', 'channels'])


def send_webpush(sub, payload):
    if not settings.VAPID_PRIVATE_KEY:
        return False
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning('pywebpush not installed; push skipped')
        return False
    try:
        webpush(subscription_info={'endpoint': sub.endpoint, 'keys': sub.keys}, data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.VAPID_CLAIMS_EMAIL}, timeout=10)
        return True
    except WebPushException as e:
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        if code in (404, 410):
            sub.delete()   # the browser unsubscribed
        else:
            logger.warning('Web push failed: %s', e)
        return False
    except Exception:
        logger.exception('Web push failed')
        return False


def send_email(to, subject, body, url='', attachments=None, html_extra=''):
    link = f'{settings.SITE_URL}{url}' if url and url.startswith('/') else url
    html = f'''<div style="font-family:Montserrat,Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#2c2c2c">
      <p style="font-size:15px;line-height:1.5">{escape(body)}</p>{html_extra}
      {f'<p><a href="{escape(link)}" style="display:inline-block;padding:10px 18px;border-radius:8px;background:#2c2c2c;color:#fff;text-decoration:none">Open makeyourreps</a></p>' if link else ''}
      <p style="font-size:12px;color:#888">You get this because you are in a squad on makeyourreps. Mute a squad from its Settings tab.</p>
    </div>'''
    try:
        msg = EmailMultiAlternatives(subject, f'{body}\n\n{link}'.strip(), settings.DEFAULT_FROM_EMAIL, [to])
        msg.attach_alternative(html, 'text/html')
        for att in attachments or []:
            msg.attach(*att)
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('Email to %s failed', to)
        return False


def deliver_queued(now=None):
    from squads.models import NotificationLog
    now = now or timezone.now()
    for log in NotificationLog.objects.filter(status='queued', deliver_after__lte=now).select_related('user')[:500]:
        _deliver(log)

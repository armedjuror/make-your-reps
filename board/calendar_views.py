"""Views for Google Calendar integration: OAuth, webhook, calendar management."""
import uuid
from datetime import datetime, timedelta, date, timezone as dt_timezone
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.response import Response
from rest_framework.views import APIView

from board.models import (
    GoogleCalendarToken, LinkedCalendar, TimelineEvent, TimelineEventType,
)
from board.calendar_client import (
    list_calendars, fetch_events_for_day, create_event,
    register_webhook, stop_webhook,
)

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'
_CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar openid email'


# ── OAuth ─────────────────────────────────────────────────────────────────────

class CalendarAuthView(APIView):
    """Returns the Google OAuth URL for the frontend to redirect to."""

    def get(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'error', 'message': 'Not authenticated'}, status=401)
        params = {
            'client_id': settings.GOOGLE_CALENDAR_CLIENT_ID,
            'redirect_uri': settings.GOOGLE_CALENDAR_REDIRECT_URI,
            'response_type': 'code',
            'scope': _CALENDAR_SCOPE,
            'access_type': 'offline',
            'prompt': 'consent select_account',
            'state': str(user_id),
        }
        return Response({'url': GOOGLE_AUTH_URL + '?' + urlencode(params)})


class CalendarCallbackView(APIView):
    """OAuth callback — exchanges code for tokens, syncs calendar list, redirects to board."""

    def get(self, request):
        code = request.GET.get('code')
        user_id = request.GET.get('state')
        if not code or not user_id:
            return redirect('/board/?calendar=error&pane=settings')

        token_resp = requests.post(GOOGLE_TOKEN_URL, data={
            'code': code,
            'client_id': settings.GOOGLE_CALENDAR_CLIENT_ID,
            'client_secret': settings.GOOGLE_CALENDAR_CLIENT_SECRET,
            'redirect_uri': settings.GOOGLE_CALENDAR_REDIRECT_URI,
            'grant_type': 'authorization_code',
        }, timeout=10)
        if token_resp.status_code != 200:
            return redirect('/board/?calendar=error&pane=settings')

        token_data = token_resp.json()
        userinfo = requests.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {token_data["access_token"]}'},
            timeout=10,
        ).json()
        google_email = userinfo.get('email', '')

        from django.contrib.auth.models import User
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return redirect('/board/?calendar=error&pane=settings')

        expiry = timezone.now() + timedelta(seconds=token_data.get('expires_in', 3600))
        token_obj, _ = GoogleCalendarToken.objects.update_or_create(
            user=user,
            google_email=google_email,
            defaults={
                'access_token': token_data['access_token'],
                'refresh_token': token_data.get('refresh_token', ''),
                'token_expiry': expiry,
            },
        )
        _sync_calendar_list(token_obj)
        return redirect('/board/?calendar=connected&pane=settings')


# ── Calendar management ───────────────────────────────────────────────────────

class CalendarListView(APIView):
    """List all connected Google accounts and their calendars."""

    def get(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'error', 'message': 'Not authenticated'}, status=401)
        tokens = GoogleCalendarToken.objects.filter(
            user_id=user_id
        ).prefetch_related('calendars')
        data = []
        for t in tokens:
            data.append({
                'id': t.id,
                'google_email': t.google_email,
                'calendars': [
                    {
                        'id': c.id,
                        'calendar_id': c.calendar_id,
                        'name': c.name,
                        'color': c.color,
                        'is_enabled': c.is_enabled,
                        'sync_habits': c.sync_habits,
                        'sync_tasks': c.sync_tasks,
                    }
                    for c in t.calendars.all()
                ],
            })
        return Response({'status': 'success', 'data': data})


class CalendarRefreshView(APIView):
    """Re-sync calendar list from Google (picks up newly created calendars)."""

    def post(self, request, token_id):
        user_id = request.session.get('user_id')
        try:
            token_obj = GoogleCalendarToken.objects.get(id=token_id, user_id=user_id)
        except GoogleCalendarToken.DoesNotExist:
            return Response({'status': 'error', 'message': 'Not found'}, status=404)
        _sync_calendar_list(token_obj)
        return Response({'status': 'success'})


class CalendarUpdateView(APIView):
    """Update a linked calendar's settings (is_enabled, sync_habits, sync_tasks)."""

    def patch(self, request, cal_id):
        user_id = request.session.get('user_id')
        try:
            cal = LinkedCalendar.objects.select_related('token').get(
                id=cal_id, token__user_id=user_id
            )
        except LinkedCalendar.DoesNotExist:
            return Response({'status': 'error', 'message': 'Not found'}, status=404)

        was_enabled = cal.is_enabled
        for field in ('is_enabled', 'sync_habits', 'sync_tasks'):
            if field in request.data:
                setattr(cal, field, request.data[field])
        cal.save()

        if cal.is_enabled and not was_enabled and not cal.webhook_channel_id:
            _register_calendar_webhook(cal)
        elif not cal.is_enabled and was_enabled and cal.webhook_channel_id:
            stop_webhook(cal.token, cal.webhook_channel_id, cal.webhook_resource_id)
            cal.webhook_channel_id = ''
            cal.webhook_resource_id = ''
            cal.webhook_expiry = None
            cal.save(update_fields=['webhook_channel_id', 'webhook_resource_id', 'webhook_expiry'])

        return Response({'status': 'success'})


class CalendarDisconnectView(APIView):
    """Remove a Google account and all its linked calendars."""

    def delete(self, request, token_id):
        user_id = request.session.get('user_id')
        try:
            token_obj = GoogleCalendarToken.objects.get(id=token_id, user_id=user_id)
        except GoogleCalendarToken.DoesNotExist:
            return Response({'status': 'error', 'message': 'Not found'}, status=404)

        calendar_ids = list(token_obj.calendars.values_list('calendar_id', flat=True))

        for cal in token_obj.calendars.all():
            if cal.webhook_channel_id:
                stop_webhook(token_obj, cal.webhook_channel_id, cal.webhook_resource_id)

        # Delete all MEETING timeline events that came from this account's calendars
        TimelineEvent.objects.filter(
            user=token_obj.user,
            event_type=TimelineEventType.MEETING,
            reference__calendar_id__in=calendar_ids,
        ).delete()

        token_obj.delete()
        return Response({'status': 'success'})


# ── Webhook receiver ──────────────────────────────────────────────────────────

@csrf_exempt
def calendar_webhook(request, cal_id):
    """Receive Google Calendar push notifications and upsert timeline events."""
    if request.method != 'POST':
        return HttpResponse(status=405)

    channel_id = request.headers.get('X-Goog-Channel-Id', '')
    resource_state = request.headers.get('X-Goog-Resource-State', '')

    # Initial sync ping — just acknowledge
    if resource_state == 'sync':
        return HttpResponse(status=200)

    try:
        cal = LinkedCalendar.objects.select_related('token__user').get(
            id=cal_id,
            webhook_channel_id=channel_id,
            is_enabled=True,
        )
    except LinkedCalendar.DoesNotExist:
        return HttpResponse(status=200)

    _upsert_calendar_events_for_day(cal, date.today())
    return HttpResponse(status=200)


# ── Public helper used by views.py ────────────────────────────────────────────

def sync_calendar_events_for_user_date(user, target_date):
    """
    Called from TimelineEventViewSet.list when no MEETING events are in DB yet.
    Fetches from Google Calendar and upserts into TimelineEvent for that date.
    """
    enabled = LinkedCalendar.objects.filter(
        token__user=user, is_enabled=True,
    ).select_related('token')
    for cal in enabled:
        try:
            _upsert_calendar_events_for_day(cal, target_date)
        except Exception:
            pass


def push_habit_to_calendar(user, habit):
    """
    Push a habit reminder to all calendars with sync_habits=True.
    Creates a single-day event at the habit's notify_at time.
    """
    if not habit.notify_at:
        return
    calendars = LinkedCalendar.objects.filter(
        token__user=user, is_enabled=True, sync_habits=True,
    ).select_related('token')
    today = date.today()
    for cal in calendars:
        try:
            start = datetime.combine(today, habit.notify_at).replace(tzinfo=dt_timezone.utc)
            end = start + timedelta(minutes=30)
            create_event(
                cal.token, cal.calendar_id,
                summary=f'Habit: {habit.habit}',
                start_dt=start, end_dt=end,
                description=habit.detail or '',
            )
        except Exception:
            pass


def push_task_to_calendar(user, task):
    """
    Push a task deadline as a Google Calendar event to all calendars with sync_tasks=True.
    """
    if not task.deadline:
        return
    calendars = LinkedCalendar.objects.filter(
        token__user=user, is_enabled=True, sync_tasks=True,
    ).select_related('token')
    for cal in calendars:
        try:
            end = task.deadline
            start = end - timedelta(hours=1)
            create_event(
                cal.token, cal.calendar_id,
                summary=f'Task due: {task.task_name}',
                start_dt=start, end_dt=end,
                description=f'Group: {task.group.name}' if task.group else '',
            )
        except Exception:
            pass


# ── Private helpers ───────────────────────────────────────────────────────────

def _sync_calendar_list(token_obj):
    """Fetch calendar list from Google and upsert LinkedCalendar rows."""
    for item in list_calendars(token_obj):
        cal, created = LinkedCalendar.objects.get_or_create(
            token=token_obj,
            calendar_id=item['id'],
            defaults={
                'name': item.get('summary', item['id']),
                'color': item.get('backgroundColor', ''),
                'is_enabled': bool(item.get('primary', False)),
            },
        )
        if not created:
            cal.name = item.get('summary', cal.name)
            cal.color = item.get('backgroundColor', cal.color)
            cal.save(update_fields=['name', 'color'])

        if cal.is_enabled and not cal.webhook_channel_id:
            _register_calendar_webhook(cal)


def _register_calendar_webhook(cal):
    channel_id = str(uuid.uuid4())
    webhook_url = f"{settings.SITE_URL}/board/api/calendar/webhook/{cal.id}/"
    result = register_webhook(cal.token, cal.calendar_id, webhook_url, channel_id)
    if result:
        cal.webhook_channel_id = result.get('id', channel_id)
        cal.webhook_resource_id = result.get('resourceId', '')
        expiry_ms = result.get('expiration')
        if expiry_ms:
            cal.webhook_expiry = datetime.fromtimestamp(
                int(expiry_ms) / 1000, tz=dt_timezone.utc
            )
        cal.save(update_fields=['webhook_channel_id', 'webhook_resource_id', 'webhook_expiry'])


def _parse_gcal_timestamp(event):
    """Parse start time from a Google Calendar event dict. Returns aware datetime or None."""
    start_raw = event.get('start', {})
    start_str = start_raw.get('dateTime') or start_raw.get('date')
    if not start_str:
        return None
    try:
        if 'T' in start_str:
            return datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        # All-day event — treat as 09:00 UTC
        return datetime.fromisoformat(start_str + 'T09:00:00+00:00')
    except ValueError:
        return None


def _upsert_calendar_events_for_day(cal, target_date):
    """Fetch events for target_date and upsert into TimelineEvent (type=MEETING)."""
    user = cal.token.user
    events = fetch_events_for_day(cal.token, cal.calendar_id, target_date)

    for event in events:
        gcal_id = event.get('id')
        if not gcal_id:
            continue

        ts = _parse_gcal_timestamp(event)
        if not ts:
            continue

        # Extract conference / video link
        conf_link = None
        for ep in event.get('conferenceData', {}).get('entryPoints', []):
            if ep.get('entryPointType') == 'video':
                conf_link = ep.get('uri')
                break
        if not conf_link:
            conf_link = event.get('hangoutLink')

        summary = event.get('summary') or 'Calendar event'
        reference = {
            'gcal_event_id': gcal_id,
            'calendar_id': cal.calendar_id,
            'calendar_name': cal.name,
        }
        if conf_link:
            reference['conference_link'] = conf_link

        # action: {'join': url} triggers the existing Join button in timeline.js
        action = {'join': conf_link} if conf_link else None

        existing = TimelineEvent.objects.filter(
            user=user,
            event_type=TimelineEventType.MEETING,
            reference__gcal_event_id=gcal_id,
        ).first()

        if existing:
            existing.timestamp = ts
            existing.event = summary
            existing.reference = reference
            existing.action = action
            existing.save(update_fields=['timestamp', 'event', 'reference', 'action', 'updated_at'])
        else:
            TimelineEvent.objects.create(
                user=user,
                timestamp=ts,
                event_type=TimelineEventType.MEETING,
                event=summary,
                reference=reference,
                action=action,
            )

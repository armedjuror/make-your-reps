"""Google Calendar API client — token refresh, event fetch, event push, webhook management."""
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
from django.conf import settings
from django.utils import timezone


GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
CALENDAR_BASE = 'https://www.googleapis.com/calendar/v3'
_TIMEOUT = 10


def _refresh_if_needed(token_obj):
    """Return a valid access token, refreshing from Google if near expiry."""
    if token_obj.token_expiry > timezone.now() + timedelta(minutes=5):
        return token_obj.access_token
    resp = requests.post(GOOGLE_TOKEN_URL, data={
        'client_id': settings.GOOGLE_CALENDAR_CLIENT_ID,
        'client_secret': settings.GOOGLE_CALENDAR_CLIENT_SECRET,
        'refresh_token': token_obj.refresh_token,
        'grant_type': 'refresh_token',
    }, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    token_obj.access_token = data['access_token']
    token_obj.token_expiry = timezone.now() + timedelta(seconds=data.get('expires_in', 3600))
    token_obj.save(update_fields=['access_token', 'token_expiry', 'updated_at'])
    return token_obj.access_token


def _auth_headers(token_obj):
    return {'Authorization': f'Bearer {_refresh_if_needed(token_obj)}'}


def list_calendars(token_obj):
    """Return list of Google calendar dicts for the account."""
    resp = requests.get(
        f'{CALENDAR_BASE}/users/me/calendarList',
        headers=_auth_headers(token_obj),
        timeout=_TIMEOUT,
    )
    return resp.json().get('items', []) if resp.status_code == 200 else []


def fetch_events_for_day(token_obj, calendar_id, target_date):
    """Return list of Google Calendar event dicts for target_date (date object)."""
    day_start = datetime.combine(target_date, datetime.min.time()).strftime('%Y-%m-%dT00:00:00Z')
    day_end = datetime.combine(target_date, datetime.min.time()).strftime('%Y-%m-%dT23:59:59Z')
    resp = requests.get(
        f'{CALENDAR_BASE}/calendars/{quote(calendar_id, safe="")}/events',
        headers=_auth_headers(token_obj),
        params={
            'timeMin': day_start,
            'timeMax': day_end,
            'singleEvents': True,
            'orderBy': 'startTime',
            'maxResults': 50,
        },
        timeout=_TIMEOUT,
    )
    return resp.json().get('items', []) if resp.status_code == 200 else []


def create_event(token_obj, calendar_id, summary, start_dt, end_dt, description=''):
    """Create a Google Calendar event. Returns event dict on success, None on failure."""
    resp = requests.post(
        f'{CALENDAR_BASE}/calendars/{quote(calendar_id, safe="")}/events',
        headers={**_auth_headers(token_obj), 'Content-Type': 'application/json'},
        json={
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'UTC'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'UTC'},
        },
        timeout=_TIMEOUT,
    )
    return resp.json() if resp.status_code in (200, 201) else None


def register_webhook(token_obj, calendar_id, webhook_url, channel_id):
    """Register a Google Calendar push notification channel. Returns response dict or None."""
    expiry_ms = int((timezone.now() + timedelta(days=7)).timestamp() * 1000)
    resp = requests.post(
        f'{CALENDAR_BASE}/calendars/{quote(calendar_id, safe="")}/events/watch',
        headers={**_auth_headers(token_obj), 'Content-Type': 'application/json'},
        json={
            'id': channel_id,
            'type': 'web_hook',
            'address': webhook_url,
            'expiration': str(expiry_ms),
        },
        timeout=_TIMEOUT,
    )
    return resp.json() if resp.status_code == 200 else None


def stop_webhook(token_obj, channel_id, resource_id):
    """Stop a push notification channel (best-effort)."""
    try:
        requests.post(
            f'{CALENDAR_BASE}/channels/stop',
            headers={**_auth_headers(token_obj), 'Content-Type': 'application/json'},
            json={'id': channel_id, 'resourceId': resource_id},
            timeout=_TIMEOUT,
        )
    except Exception:
        pass

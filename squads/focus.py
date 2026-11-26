"""
Scheduled squad focus sessions.

* Members with Google Calendar connected get an event inserted in their own
  calendar (no attendee list, so Google sends no duplicate invite). Everyone
  else gets an email with an .ics attachment (METHOD:REQUEST, STATUS:CONFIRMED).
* One UID per session; edits bump SEQUENCE and resend; cancelling sends
  METHOD:CANCEL or deletes the Google event.
* RSVP is optional and informational (signed Yes / No links in the email).
* Sessions always run. Completed = present for >= 80% of the focus blocks.
  Points need a quorum: 2+ unique members completed.
* Completing auto-logs the session's linked habit, quorum or not.
"""
import logging
from datetime import timedelta, timezone as dt_timezone
from urllib.parse import quote

import requests
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from board.models import GoogleCalendarToken, HabitLog, LogSource
from squads import items, limits
from squads.events import track
from squads.models import (
    CalendarDelivery, FeedItem, FocusAttendance, FocusRSVP, FocusSession, FocusStatus, MembershipStatus,
)

logger = logging.getLogger(__name__)
COMPLETE_SHARE = 0.8
HEARTBEAT_MAX_GAP = 90      # seconds credited per heartbeat at most
RSVP_SALT = 'squads.focus.rsvp'


class FocusError(Exception):
    pass


# ──────────────────────────────────────
# iCalendar
# ──────────────────────────────────────

def _ics_dt(dt):
    return dt.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _ics_escape(text):
    return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _fold(line):
    out, raw = [], line.encode('utf-8')
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:   # never split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode('utf-8'))
        raw = b' ' + raw[cut:]
    out.append(raw.decode('utf-8'))
    return '\r\n'.join(out)


def build_ics(session, method='REQUEST', attendee_email=None):
    board = session.board
    status = 'CANCELLED' if method == 'CANCEL' else 'CONFIRMED'
    room = f'{settings.SITE_URL}/squads/focus/{session.id}/room/'
    desc = (f'{board.emoji} {board.name} focus session: {session.blocks} x {session.block_minutes} min.\n'
            f'Join the live room: {room}')
    organizer = settings.DEFAULT_FROM_EMAIL.split('<')[-1].rstrip('>') if '<' in settings.DEFAULT_FROM_EMAIL \
        else settings.DEFAULT_FROM_EMAIL
    lines = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//makeyourreps//Squads//EN', 'CALSCALE:GREGORIAN',
        f'METHOD:{method}', 'BEGIN:VEVENT',
        f'UID:{session.ics_uid}', f'SEQUENCE:{session.ics_sequence}', f'DTSTAMP:{_ics_dt(timezone.now())}',
        f'DTSTART:{_ics_dt(session.start_at)}', f'DTEND:{_ics_dt(session.end_at)}',
        f'SUMMARY:{_ics_escape(f"{board.emoji} {session.title} · {board.name}".strip())}',
        f'DESCRIPTION:{_ics_escape(desc)}', f'URL:{room}', f'STATUS:{status}',
        f'ORGANIZER;CN=makeyourreps:mailto:{organizer}',
    ]
    if attendee_email:
        lines.append(f'ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=FALSE:mailto:{attendee_email}')
    if method != 'CANCEL':
        lines += ['BEGIN:VALARM', 'TRIGGER:-PT10M', 'ACTION:DISPLAY', 'DESCRIPTION:Focus session starts soon',
                  'END:VALARM']
    lines += ['END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(_fold(l) for l in lines) + '\r\n'


# ──────────────────────────────────────
# RSVP links
# ──────────────────────────────────────

def rsvp_token(session, user_id, response):
    return signing.dumps({'s': session.id, 'u': user_id, 'r': response}, salt=RSVP_SALT)


def read_rsvp_token(token):
    return signing.loads(token, salt=RSVP_SALT, max_age=60 * 60 * 24 * 60)


def set_rsvp(session, user_id, response):
    if response not in ('yes', 'no', 'maybe'):
        raise FocusError('RSVP must be yes, no or maybe')
    obj, _ = FocusRSVP.objects.update_or_create(session=session, user_id=user_id, defaults={'response': response})
    return obj


# ──────────────────────────────────────
# Delivery
# ──────────────────────────────────────

def _google_token(user_id):
    return GoogleCalendarToken.objects.filter(user_id=user_id).order_by('created_at').first()


def _google_body(session):
    board = session.board
    return {
        'summary': f'{board.emoji} {session.title} · {board.name}'.strip(),
        'description': f'Join the live room: {settings.SITE_URL}/squads/focus/{session.id}/room/',
        'start': {'dateTime': session.start_at.isoformat(), 'timeZone': 'UTC'},
        'end': {'dateTime': session.end_at.isoformat(), 'timeZone': 'UTC'},
        'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 10}]},
        'source': {'title': 'makeyourreps', 'url': f'{settings.SITE_URL}/squads/focus/{session.id}/room/'},
    }


def _google_call(method, token, path, body=None):
    from board.calendar_client import CALENDAR_BASE, _auth_headers
    try:
        resp = requests.request(method, f'{CALENDAR_BASE}{path}', json=body, timeout=10,
                                headers={**_auth_headers(token), 'Content-Type': 'application/json'})
    except Exception:   # network error or a token Google no longer refreshes
        logger.exception('Google Calendar request failed')
        return None
    if resp.status_code >= 300:
        logger.warning('Google Calendar %s %s: %s', method, path, resp.status_code)
        return None
    return resp.json() if resp.content else {}


def _rsvp_html(session, user_id):
    links = ' · '.join(
        f'<a href="{settings.SITE_URL}/squads/focus/rsvp/{rsvp_token(session, user_id, r)}/">{label}</a>'
        for r, label in (('yes', "Yes, I'm in"), ('no', "Can't make it")))
    return f'<p style="font-size:14px">Coming? {links} <span style="color:#888">(optional)</span></p>'


def deliver_to(session, user, method='REQUEST'):
    from squads.notify import send_email
    token = _google_token(user.id)
    delivery = CalendarDelivery.objects.filter(session=session, user=user).first()
    when = timezone.localtime(session.start_at).strftime('%a %d %b, %I:%M %p')
    if token:
        cal = 'primary'
        if method == 'CANCEL':
            if delivery and delivery.external_id:
                _google_call('DELETE', token, f'/calendars/{cal}/events/{quote(delivery.external_id, safe="")}')
            status, ext = 'cancelled', delivery.external_id if delivery else ''
        elif delivery and delivery.external_id and delivery.channel == 'google':
            res = _google_call('PATCH', token, f'/calendars/{cal}/events/{quote(delivery.external_id, safe="")}',
                               _google_body(session))
            status, ext = ('sent' if res is not None else 'failed'), delivery.external_id
        else:
            res = _google_call('POST', token, f'/calendars/{cal}/events', _google_body(session))
            status, ext = ('sent' if res else 'failed'), (res or {}).get('id', '')
        if status != 'failed':
            CalendarDelivery.objects.update_or_create(session=session, user=user, defaults={
                'channel': 'google', 'external_id': ext, 'calendar_token': token, 'status': status,
                'sequence': session.ics_sequence})
            return 'google'
    if not user.email:
        return None
    ics = build_ics(session, method, user.email)
    verb = {'REQUEST': 'scheduled' if session.ics_sequence == 0 else 'updated', 'CANCEL': 'cancelled'}[method]
    subject = f'{session.board.emoji} Focus session {verb}: {when}'
    body = (f'{session.board.name}: {session.blocks} x {session.block_minutes} min focus, {when}.'
            if method != 'CANCEL' else f'The {session.board.name} focus session on {when} was cancelled.')
    ok = send_email(user.email, subject, body, url=f'/squads/focus/{session.id}/room/' if method != 'CANCEL' else '',
                    attachments=[('invite.ics', ics, f'text/calendar; method={method}; charset=UTF-8')],
                    html_extra=_rsvp_html(session, user.id) if method != 'CANCEL' else '')
    CalendarDelivery.objects.update_or_create(session=session, user=user, defaults={
        'channel': 'ics_email', 'status': ('cancelled' if method == 'CANCEL' else 'sent') if ok else 'failed',
        'sequence': session.ics_sequence})
    return 'ics_email'


def deliver_all(session, method='REQUEST'):
    out = {}
    for m in session.board.active_memberships().select_related('user'):
        try:
            out[m.user_id] = deliver_to(session, m.user, method)
        except Exception:
            logger.exception('Focus delivery to %s failed', m.user_id)
    return out


# ──────────────────────────────────────
# Schedule, edit, cancel
# ──────────────────────────────────────

def sessions_this_week(board, day):
    start = day - timedelta(days=day.weekday())
    return FocusSession.objects.filter(board=board, start_at__date__gte=start,
                                       start_at__date__lt=start + timedelta(days=7)).exclude(
        status=FocusStatus.CANCELLED).count()


def schedule(board, host_id, *, start_at, block_minutes=50, blocks=1, break_minutes=10, title='Focus session',
             linked_habit=None, deliver=True):
    from squads.scoping import can_log
    if not can_log(board, host_id):
        raise FocusError('Only squad members can schedule sessions')
    if start_at <= timezone.now():
        raise FocusError('Pick a time in the future')
    if not (5 <= int(block_minutes) <= 180) or not (1 <= int(blocks) <= 8):
        raise FocusError('Blocks are 5-180 minutes, 1-8 of them')
    limits.check(board.owner_id, 'focus_sessions_per_week',
                 sessions_this_week(board, board.local_now(start_at).date()))
    s = FocusSession.objects.create(board=board, host_id=host_id, start_at=start_at, block_minutes=block_minutes,
                                    blocks=blocks, break_minutes=break_minutes, title=title[:120] or 'Focus session',
                                    linked_habit=linked_habit)
    if deliver:
        transaction.on_commit(lambda: deliver_all(s, 'REQUEST'))
    track('focus_session_scheduled', host_id, board_id=board.id)
    return s


def edit(session, user_id, **changes):
    from squads.scoping import can_edit
    if session.host_id != user_id and not can_edit(session.board, user_id):
        raise FocusError('Only the host or an admin can change this session')
    if session.status != FocusStatus.SCHEDULED:
        raise FocusError('This session has already started')
    for key in ('start_at', 'block_minutes', 'blocks', 'break_minutes', 'title'):
        if key in changes and changes[key] is not None:
            setattr(session, key, changes[key])
    session.ics_sequence += 1
    session.save()
    transaction.on_commit(lambda: deliver_all(session, 'REQUEST'))
    return session


def cancel(session, user_id):
    from squads.scoping import can_edit
    if session.host_id != user_id and not can_edit(session.board, user_id):
        raise FocusError('Only the host or an admin can cancel this session')
    session.status = FocusStatus.CANCELLED
    session.ics_sequence += 1
    session.save(update_fields=['status', 'ics_sequence'])
    transaction.on_commit(lambda: deliver_all(session, 'CANCEL'))
    return session


# ──────────────────────────────────────
# Live room
# ──────────────────────────────────────

def _block_index(session, moment):
    for i, (a, b) in enumerate(session.block_windows()):
        if a <= moment < b:
            return i
    return None


def heartbeat(session, user_id, now=None, leaving=False):
    """Join or stay in the room. Credits time present inside focus blocks."""
    from squads.scoping import is_member
    now = now or timezone.now()
    if not is_member(session.board, user_id):
        raise FocusError('Not a member of this squad')
    if session.status == FocusStatus.CANCELLED:
        raise FocusError('This session was cancelled')
    if now > session.end_at:
        raise FocusError('This session has ended')
    att = FocusAttendance.objects.filter(session=session, user_id=user_id).first()
    if att is None:
        if now > session.late_join_until:
            raise FocusError('Late join closes when the first block ends')
        att = FocusAttendance.objects.create(session=session, user_id=user_id, joined_at=now, last_seen_at=now,
                                             block_seconds=[0] * session.blocks)
    else:
        gap = (now - att.last_seen_at).total_seconds()
        if att.left_at is None and 0 < gap <= HEARTBEAT_MAX_GAP:
            _credit(session, att, att.last_seen_at, now)
        att.last_seen_at = now
        att.left_at = now if leaving else None
    if session.status == FocusStatus.SCHEDULED and now >= session.start_at:
        FocusSession.objects.filter(pk=session.pk, status=FocusStatus.SCHEDULED).update(status=FocusStatus.LIVE)
    att.save()
    return att


def _credit(session, att, start, end):
    secs = list(att.block_seconds or [0] * session.blocks)
    for i, (a, b) in enumerate(session.block_windows()):
        overlap = (min(b, end) - max(a, start)).total_seconds()
        if overlap > 0:
            secs[i] = secs[i] + int(overlap)
    att.block_seconds = secs
    att.seconds = sum(secs)


def room_state(session, viewer_id=None, now=None):
    now = now or timezone.now()
    present_after = now - timedelta(seconds=HEARTBEAT_MAX_GAP)
    people = []
    for a in session.attendance.select_related('user'):
        if a.user_id is None:
            continue
        people.append({'user_id': a.user_id, 'name': items.display_name(a.user),
                       'present': a.left_at is None and a.last_seen_at >= present_after, 'minutes': a.minutes})
    idx = _block_index(session, now)
    phase, ends = 'before', session.start_at
    if now >= session.end_at:
        phase, ends = 'done', session.end_at
    elif idx is not None:
        phase, ends = 'focus', session.block_windows()[idx][1]
    elif now >= session.start_at:
        nxt = next((a for a, _ in session.block_windows() if a > now), session.end_at)
        phase, ends = 'break', nxt
    return {
        'id': session.id, 'title': session.title, 'board': {'id': session.board_id, 'name': session.board.name,
                                                            'emoji': session.board.emoji},
        'start_at': session.start_at.isoformat(), 'end_at': session.end_at.isoformat(),
        'block_minutes': session.block_minutes, 'blocks': session.blocks, 'break_minutes': session.break_minutes,
        'status': session.status, 'phase': phase, 'phase_ends_at': ends.isoformat(),
        'block': (idx + 1) if idx is not None else None, 'people': people,
        'can_join': session.status != FocusStatus.CANCELLED and now <= session.late_join_until
        or bool(viewer_id and session.attendance.filter(user_id=viewer_id).exists() and now < session.end_at),
        'server_now': now.isoformat(),
    }


# ──────────────────────────────────────
# Outcome
# ──────────────────────────────────────

def completed(session, att):
    """Present for at least 80% of the focus blocks' time (breaks don't count)."""
    return att.seconds >= COMPLETE_SHARE * session.focus_minutes * 60


def close(session, now=None):
    """After the session ends: mark completions, quorum, auto-log linked habits, post to the feed."""
    now = now or timezone.now()
    if session.status in (FocusStatus.DONE, FocusStatus.CANCELLED) or now < session.end_at:
        return session
    completers = []
    for att in session.attendance.all():
        att.completed = completed(session, att)
        att.save(update_fields=['completed'])
        if att.completed and att.user_id:
            completers.append(att.user_id)
    unique = sorted(set(completers))
    session.quorum_met = len(unique) >= 2
    session.status = FocusStatus.DONE
    session.save(update_fields=['quorum_met', 'status'])
    day = session.board.local_now(session.start_at).date()
    if session.linked_habit_id:
        for uid in unique:
            copy = items.linked_copy(session.linked_habit, uid)
            if copy:
                log, _ = HabitLog.objects.get_or_create(habit=copy, date=day)
                if not log.is_done:
                    log.is_done, log.source = True, LogSource.FOCUS
                    log.save()
    attendees = session.attendance.exclude(user__isnull=True).count()
    if session.quorum_met:
        text = f'Focus session done: {len(unique)} completed · {session.blocks} x {session.block_minutes} min'
    elif unique:
        text = 'Solo session — invite someone next time for points'
    else:
        text = 'Focus session ended: nobody completed it'
    FeedItem.objects.create(board=session.board, kind='session', text=text, reactable=session.quorum_met,
                            ref={'session': session.id})
    track('focus_session_done', session.host_id, board_id=session.board_id, attendees=attendees,
          completed=len(unique), quorum=session.quorum_met)
    return session


def serialize(session, viewer_id=None):
    rsvps = {r.user_id: r.response for r in session.rsvps.all()}
    att = list(session.attendance.select_related('user'))
    return {
        'id': session.id, 'title': session.title, 'start_at': session.start_at.isoformat(),
        'end_at': session.end_at.isoformat(), 'block_minutes': session.block_minutes, 'blocks': session.blocks,
        'break_minutes': session.break_minutes, 'status': session.status, 'quorum_met': session.quorum_met,
        'host': items.display_name(session.host) if session.host_id else None, 'host_id': session.host_id,
        'duration_minutes': session.total_minutes,
        'rsvp': {'yes': sum(1 for v in rsvps.values() if v == 'yes'), 'no': sum(1 for v in rsvps.values() if v == 'no'),
                 'mine': rsvps.get(viewer_id)},
        'attendance': [{'user_id': a.user_id, 'name': items.display_name(a.user), 'minutes': a.minutes,
                        'completed': a.completed} for a in att],
        'room_url': f'/squads/focus/{session.id}/room/',
        'linked_habit': session.linked_habit_id,
    }

"""
Resilient days: one resolver that every view and task calls.

A day has a *template* (workday / holiday: which routine blocks exist) and a
*mode* (normal / light / disrupted: how much of the template runs). Both live
on one ``DayPlan`` row per date. No row means the weekday rule plus Normal, so
users who never touch the feature see no change.

``resolve_day(user, date)`` returns the template, the mode, the visible blocks
with their status, and whether the day's bar is met.
"""
from datetime import datetime, time, timedelta

from django.utils import timezone

from board.models import (
    BlockLog, DayMode, DayPlan, RoutineEntry, RoutineType, Tier, UserDetail,
)

MISSED_GRACE_MIN = 30        # a block is missed this long after it ends
ANCHOR_THRESHOLD = 0.5       # share of visible anchors that must be done
DEFAULT_BLOCK_MIN = 60       # end of the last block when it has no duration
CHECKIN_AFTER_START_MIN = 15
VISIBLE_TIERS = {
    DayMode.NORMAL: {Tier.ESSENTIAL, Tier.ANCHOR, Tier.FLEXIBLE},
    DayMode.LIGHT: {Tier.ESSENTIAL, Tier.ANCHOR},
    DayMode.DISRUPTED: {Tier.ESSENTIAL},
}
# Rows written by the system rather than chosen by the user. They hold a slip
# or a reset, so the morning check-in still applies.
SYSTEM_SOURCES = {'slip', 'reset'}


def get_detail(user_or_id):
    user_id = getattr(user_or_id, 'id', user_or_id)
    detail, _ = UserDetail.objects.get_or_create(user_id=user_id)
    return detail


def logical_now(now=None):
    return timezone.localtime(now or timezone.now())


def logical_today(user_or_id, now=None, detail=None):
    """Today's date, where activity before ``day_start`` still belongs to yesterday."""
    detail = detail or get_detail(user_or_id)
    local = logical_now(now)
    if local.time() < detail.day_start:
        return local.date() - timedelta(days=1)
    return local.date()


def default_template(detail, target_date):
    return RoutineType.HOLIDAY if target_date.weekday() in (detail.weekend_days or []) else RoutineType.WORKDAY


def _aware(target_date, t):
    return timezone.make_aware(datetime.combine(target_date, t))


def _block_at(target_date, t, day_start=None):
    """
    When a routine block happens. A block earlier than ``day_start`` belongs to
    the night after the day (01:00 on a day that starts at 04:00 is the next
    calendar date), which is what night shifts need.
    """
    at = _aware(target_date, t)
    if day_start is not None and t < day_start:
        at += timedelta(days=1)
    return at


def _add_minutes(target_date, t, minutes):
    return _aware(target_date, t) + timedelta(minutes=minutes)


def plan_for(user_id, target_date):
    return DayPlan.objects.filter(user_id=user_id, date=target_date).first()


def resolved_plan(detail, plan, target_date):
    """(template, mode, source, is_default) for a date, with or without a row."""
    if plan is None:
        return default_template(detail, target_date), DayMode.NORMAL, 'default', True
    return plan.template, plan.mode, plan.source, False


def needs_checkin(plan):
    return plan is None or plan.source in SYSTEM_SOURCES


def _effective_blocks(entries, shifts, target_date, mode, day_start=None):
    """
    Apply running-late shifts. Returns a list of dicts in time order:
    ``{entry, eff (aware dt), shifted_from (time|None), dropped (bool)}``.

    For blocks after the press time of each shift: essential or fixed blocks do
    not move; anchors move later by the minutes; flexible blocks up to the next
    fixed block are dropped. An anchor whose shifted time would pass the next
    fixed block is dropped as well, never stacked on top of it.
    """
    blocks = [
        {'entry': e, 'eff': _block_at(target_date, e.time, day_start), 'shifted_from': None, 'dropped': False}
        for e in entries
    ]
    blocks.sort(key=lambda b: (b['eff'], b['entry'].id))   # after-midnight blocks come last

    def is_fixed(b):
        return b['entry'].tier == Tier.ESSENTIAL or b['entry'].fixed_time

    for shift in sorted(shifts or [], key=lambda s: s.get('at', '')):
        try:
            press = timezone.localtime(datetime.fromisoformat(shift['at']))
            minutes = int(shift['minutes'])
        except (KeyError, ValueError, TypeError):
            continue
        after = [b for b in blocks if not b['dropped'] and b['eff'] > press]
        first_fixed = next((f for f in after if is_fixed(f)), None)   # next fixed block from the press
        for b in after:
            if is_fixed(b):
                continue
            nxt = next((f for f in after if is_fixed(f) and f['eff'] > b['eff']), None)
            if b['entry'].tier == Tier.FLEXIBLE:
                # Flexible blocks between now and the next fixed block give way.
                if first_fixed is None or b['eff'] < first_fixed['eff']:
                    b['dropped'] = True
                continue
            new_eff = b['eff'] + timedelta(minutes=minutes)
            if nxt is not None and new_eff >= nxt['eff']:
                b['dropped'] = True
                continue
            if b['shifted_from'] is None:
                b['shifted_from'] = b['entry'].time
            b['eff'] = new_eff
    blocks.sort(key=lambda b: (b['eff'], b['entry'].id))
    return blocks


def resolve_day(user, target_date, now=None, closing=False, detail=None):
    """
    Resolve one date for one user.

    ``closing=True`` evaluates the day as if it had ended: every visible block
    without a log is missed. Used by the day-close task.
    """
    user_id = getattr(user, 'id', user)
    detail = detail or get_detail(user_id)
    now_local = logical_now(now)
    today = logical_today(user_id, now, detail)
    plan = plan_for(user_id, target_date)
    template, mode, source, is_default = resolved_plan(detail, plan, target_date)

    entries = list(RoutineEntry.objects.filter(user_id=user_id, routine_type=template).order_by('time', 'id'))
    logs = list(BlockLog.objects.filter(user_id=user_id, date=target_date))
    log_by_entry = {l.entry_id: l for l in logs if l.entry_id}
    orphan_logs = [l for l in logs if not l.entry_id]

    visible = set(VISIBLE_TIERS[mode])
    warning = None
    if mode == DayMode.DISRUPTED and not any(e.tier == Tier.ESSENTIAL for e in entries):
        # Nothing is tagged essential: Disrupted would show nothing. Fall back to the first anchor.
        warning = 'no_essential'
        first_anchor = next((e for e in entries if e.tier == Tier.ANCHOR), None)
        visible_entries = [first_anchor] if first_anchor else []
    else:
        visible_entries = [e for e in entries if e.tier in visible]

    blocks = _effective_blocks(visible_entries, plan.shifts if plan else [], target_date, mode, detail.day_start)

    is_past = closing or target_date < today
    out = []
    for i, b in enumerate(blocks):
        e = b['entry']
        log = log_by_entry.get(e.id)
        if e.duration_min:
            end = b['eff'] + timedelta(minutes=e.duration_min)
        elif i + 1 < len(blocks):
            end = blocks[i + 1]['eff']
        else:
            end = b['eff'] + timedelta(minutes=DEFAULT_BLOCK_MIN)
        added_late = timezone.localtime(e.created_at) > _block_at(target_date, e.time, detail.day_start)

        if log:
            status = log.status
            reason = log.reason
        elif b['dropped']:
            status, reason = 'dropped', 'running_late'
        elif added_late and not closing and target_date >= today:
            # A block added after its own time is not marked missed today.
            status, reason = 'pending', ''
        elif is_past and not added_late:
            status, reason = 'missed', ''
        elif target_date == today and now_local > end + timedelta(minutes=MISSED_GRACE_MIN):
            status, reason = 'missed', ''
        else:
            status, reason = 'pending', ''
        out.append({
            'entry_id': e.id,
            'id': f'routine-{e.id}',
            'title': e.title,
            'time': b['eff'].time().replace(second=0, microsecond=0),
            'timestamp': b['eff'],
            'end': end,
            'tier': e.tier,
            'fixed_time': e.fixed_time,
            'shifted_from': b['shifted_from'],
            'status': status,
            'reason': reason,
            'orphan': False,
        })

    # A deleted block's log stays and still counts for the day (tier snapshot).
    for l in orphan_logs:
        if l.tier in visible:
            out.append({
                'entry_id': None, 'id': f'routine-log-{l.id}', 'title': l.title,
                'time': l.scheduled_time, 'timestamp': _block_at(target_date, l.scheduled_time, detail.day_start),
                'end': _block_at(target_date, l.scheduled_time, detail.day_start), 'tier': l.tier,
                'fixed_time': False, 'shifted_from': None, 'status': l.status,
                'reason': l.reason, 'orphan': True,
            })

    essentials = [b for b in out if b['tier'] == Tier.ESSENTIAL]
    if warning == 'no_essential':
        # The fallback anchor stands in for the missing essential.
        essentials = list(out)
        anchors = []
    else:
        anchors = [b for b in out if b['tier'] == Tier.ANCHOR and b['status'] not in ('skipped', 'dropped')]
    ess_done = sum(1 for b in essentials if b['status'] == 'done')
    anc_done = sum(1 for b in anchors if b['status'] == 'done')
    met = ess_done == len(essentials) and (not anchors or anc_done >= ANCHOR_THRESHOLD * len(anchors))

    return {
        'date': target_date,
        'template': template,
        'mode': mode,
        'source': source,
        'is_default': is_default,
        'plan': plan,
        'blocks': out,
        'warning': warning,
        'required': len(essentials) + len(anchors),
        'required_done': ess_done + anc_done,
        'met': met,
        'banner': ('Easing back in after your off day: a light day' if source == 'ramp'
                   else f'Off day · {plan.reason}' if source == 'travel' and plan and plan.reason else None),
    }


def day_payload(resolved):
    """The ``day`` object returned on the timeline and by ``day_plans``."""
    plan = resolved['plan']
    return {
        'date': resolved['date'].isoformat(),
        'template': resolved['template'],
        'mode': resolved['mode'],
        'source': resolved['source'],
        'is_default': resolved['is_default'],
        'banner': resolved['banner'],
        'warning': resolved['warning'],
        'shifts': plan.shifts if plan else [],
        'reset_done': bool(plan and plan.reset_done_at),
    }


def block_event(block, target_date):
    """A routine block as a timeline item."""
    pending = block['status'] in ('pending', 'missed')
    ts = block['timestamp'].isoformat()
    return {
        'id': block['id'],
        'timestamp': ts,
        'event_type': 'routine',
        'event': block['title'],
        'ends_at': block['end'].isoformat() if block.get('end') else None,
        'reference': {'model': 'RoutineEntry', 'id': block['entry_id']},
        'action': {'block': ['done', 'skipped']} if pending and block['entry_id'] else None,
        'action_response': {'block': block['status']} if block['status'] in ('done', 'skipped') else None,
        'tier': block['tier'],
        'status': block['status'],
        'reason': block['reason'],
        'shifted_from': block['shifted_from'].strftime('%H:%M') if block['shifted_from'] else None,
        'created_at': ts,
        'updated_at': ts,
    }


def checkin_event(resolved, target_date):
    """Morning check-in card, injected at the first essential block."""
    detail_time = None
    entries = [b for b in resolved['blocks'] if b['tier'] == Tier.ESSENTIAL and not b['orphan']]
    if entries:
        detail_time = min(b['timestamp'] for b in entries)
    if detail_time is None:
        detail = get_detail(resolved['plan'].user_id) if resolved['plan'] else None
        start = detail.day_start if detail else time(4, 0)
        detail_time = _add_minutes(target_date, start, CHECKIN_AFTER_START_MIN)
    ts = detail_time.isoformat()
    return {
        'id': f'day-checkin-{target_date}',
        'timestamp': ts,
        'event_type': 'text',
        'event': 'What kind of day is it?',
        'reference': None,
        'action': {'mode': ['normal', 'light', 'disrupted']},
        'action_response': None,
        'created_at': ts,
        'updated_at': ts,
    }

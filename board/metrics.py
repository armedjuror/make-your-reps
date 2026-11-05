"""
Metrics (any number, with fields), their day values, the habit link, and the
journals that hang off them.
"""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from board.days import get_detail, logical_today
from board.models import (
    DailyData, DayMode, DayPlan, Habit, HabitLog, HabitStatus, Journal, JournalEntry,
    Metric, MetricEntry, MetricKind,
)

SLEEP_METRIC_NAME = 'Sleep'
FIELD_TYPES = {'choice', 'scale', 'text'}
TEXT_MAX = 280


# ── Dates and targets ──────────────────────────────────────

def logical_date_of(user_id, moment):
    """The logical day a moment belongs to (before day_start counts as yesterday)."""
    detail = get_detail(user_id)
    local = timezone.localtime(moment)
    return local.date() - timedelta(days=1) if local.time() < detail.day_start else local.date()


def effective_target(metric, user_id, target_date):
    """target_light applies on Light and Disrupted days when set."""
    if metric.target_light is not None:
        plan = DayPlan.objects.filter(user_id=user_id, date=target_date).first()
        if plan and plan.mode in (DayMode.LIGHT, DayMode.DISRUPTED):
            return metric.target_light
    return metric.target


def day_value(metric, target_date):
    qs = MetricEntry.objects.filter(metric=metric, date=target_date)
    if metric.kind == MetricKind.COUNTER:
        return Decimal(qs.count())
    if metric.kind == MetricKind.SINGLE:
        e = qs.order_by('-at').first()
        return e.value if e else Decimal(0)
    return qs.aggregate(t=Sum('value'))['t'] or Decimal(0)


def breached(metric, user_id, target_date):
    """An 'at most' metric over its target for the day."""
    if metric.direction != 'at_most':
        return False
    target = effective_target(metric, user_id, target_date)
    return target is not None and day_value(metric, target_date) > target


# ── Field validation ───────────────────────────────────────

def clean_fields(fields):
    """Validate a metric's field definitions; returns a cleaned list or raises ValueError."""
    if not isinstance(fields, list):
        raise ValueError('fields must be a list')
    out, seen = [], set()
    for f in fields:
        key = str(f.get('key', '')).strip()
        ftype = f.get('type')
        if not key or key in seen or ftype not in FIELD_TYPES:
            raise ValueError(f'invalid field: {f}')
        seen.add(key)
        item = {'key': key, 'label': str(f.get('label', key))[:40], 'type': ftype}
        if ftype == 'choice':
            item['options'] = [str(o)[:40] for o in (f.get('options') or [])][:30]
            item['allow_other'] = bool(f.get('allow_other', True))
        if ftype == 'scale':
            item['max'] = max(2, min(int(f.get('max', 10)), 10))
        out.append(item)
    return out


def clean_data(metric, data):
    """Keep only defined keys and check each against its type."""
    data = data or {}
    out = {}
    for f in metric.fields or []:
        if f['key'] not in data or data[f['key']] in (None, ''):
            continue
        v = data[f['key']]
        if f['type'] == 'scale':
            v = int(v)
            if not 1 <= v <= f.get('max', 10):
                raise ValueError(f"{f['key']} must be 1-{f.get('max', 10)}")
        else:
            v = str(v).strip()[:TEXT_MAX]
            if f['type'] == 'choice' and not f.get('allow_other', True) and v not in f.get('options', []):
                raise ValueError(f"{f['key']} must be one of the options")
        out[f['key']] = v
    return out


def chips(metric, limit_days=90):
    """Choice options per field, most used first, then the rest in defined order."""
    since = timezone.localdate() - timedelta(days=limit_days)
    out = {}
    entries = list(MetricEntry.objects.filter(metric=metric, date__gte=since).values_list('data', flat=True))
    for f in metric.fields or []:
        if f['type'] != 'choice':
            continue
        used = Counter(d.get(f['key']) for d in entries if d.get(f['key']))
        opts = list(f.get('options', []))
        for v in used:
            if v not in opts:
                opts.append(v)
        out[f['key']] = sorted(opts, key=lambda o: (-used.get(o, 0), opts.index(o)))
    return out


# ── Logging ────────────────────────────────────────────────

def log_entry(metric, *, value=None, data=None, note='', at=None):
    """
    Log against a metric. counter: +1 entry. additive: adds ``value`` as a new
    entry. single: one row per day, logging again overwrites it and keeps the
    old value in ``data.previous``. A note or answers to the
    tracker's questions become a JournalEntry.
    """
    user_id = metric.user_id
    at = at or timezone.now()
    day = logical_date_of(user_id, at)
    data = clean_data(metric, data)

    if metric.kind == MetricKind.COUNTER:
        value = Decimal(1)
    else:
        if value is None:
            raise ValueError('value is required')
        value = Decimal(str(value))
        if value < 0:
            raise ValueError('value must not be negative')

    if metric.kind == MetricKind.SINGLE:
        entry = MetricEntry.objects.filter(metric=metric, date=day).order_by('-at').first()
        if entry:
            data['previous'] = float(entry.value)
            entry.value, entry.data, entry.at = value, data, at
            entry.save()
        else:
            entry = MetricEntry.objects.create(metric=metric, date=day, at=at, value=value, data=data)
    else:
        entry = MetricEntry.objects.create(metric=metric, date=day, at=at, value=value, data=data)

    note = (note or '').strip()
    answers = {k: v for k, v in (entry.data or {}).items() if k != 'previous'}
    # A note or an answer to one of the tracker's questions goes in its journal
    if note or answers:
        journal = journal_for_metric(metric)
        # A single-kind note replaces the day's note rather than stacking.
        JournalEntry.objects.filter(metric_entry=entry).delete()
        JournalEntry.objects.create(journal=journal, date=day, at=at, text=note, metric_entry=entry)
    sync_metric_habits(metric, day)
    return entry


def undo_last(metric, target_date):
    """Undo removes the last entry (counter, additive) or clears the value (single)."""
    entry = MetricEntry.objects.filter(metric=metric, date=target_date).order_by('-at', '-id').first()
    if not entry:
        return False
    JournalEntry.objects.filter(metric_entry=entry).delete()
    entry.delete()
    sync_metric_habits(metric, target_date)
    return True


def sync_metric_habits(metric, target_date):
    """
    'At least' habits are marked done automatically when the day's total meets
    the target (and unmarked if an undo drops it below). 'At most' habits are
    settled at day close.
    """
    if metric.direction != 'at_least':
        return
    target = effective_target(metric, metric.user_id, target_date)
    if target is None:
        return
    met = day_value(metric, target_date) >= target
    today = logical_today(metric.user_id)
    for habit in Habit.objects.filter(user_id=metric.user_id, metric=metric,
                                      status=HabitStatus.ACTIVE.value):
        log, _ = HabitLog.objects.get_or_create(habit=habit, date=target_date)
        if log.is_done == met:
            continue
        log.is_done = met
        log.save()
        if target_date == today:
            from board.gamification import award_points, deduct_points, update_daily_streak
            if met:
                update_daily_streak(metric.user_id)
                award_points(metric.user_id, 'habit')
            else:
                deduct_points(metric.user_id, 'habit')


# ── Insights ───────────────────────────────────────────────

def insights(metric, days=30):
    user_id = metric.user_id
    today = logical_today(user_id)
    since = today - timedelta(days=days - 1)
    entries = list(MetricEntry.objects.filter(metric=metric, date__gte=since))
    by_day = {}
    for e in entries:
        by_day.setdefault(e.date, []).append(e)
    daily = []
    for i in range(days):
        d = since + timedelta(days=i)
        daily.append({'date': d.isoformat(), 'value': float(day_value(metric, d)),
                      'target': _f(effective_target(metric, user_id, d))})
    triggers = {}
    for f in metric.fields or []:
        if f['type'] == 'choice':
            triggers[f['key']] = dict(Counter(e.data.get(f['key']) for e in entries if e.data.get(f['key'])))
    hours = [0] * 24
    weekdays = [0] * 7
    for e in entries:
        local = timezone.localtime(e.at)
        hours[local.hour] += 1
        weekdays[e.date.weekday()] += 1
    return {'daily': daily, 'triggers': triggers, 'time_of_day': hours, 'weekday': weekdays}


def _f(v):
    return float(v) if v is not None else None


# ── Sleep metric and journals ──────────────────────────────

def ensure_sleep_metric(user_id):
    metric = Metric.objects.filter(user_id=user_id, is_system=True, name=SLEEP_METRIC_NAME).first()
    if not metric:
        metric = Metric.objects.create(
            user_id=user_id, name=SLEEP_METRIC_NAME, unit='h', kind=MetricKind.SINGLE,
            direction='at_least', quick_steps=[], fields=[], is_system=True,
        )
    return metric


def ensure_default_journal(user_id):
    journal = Journal.objects.filter(user_id=user_id, is_default=True).first()
    if not journal:
        journal = Journal.objects.create(
            user_id=user_id, name='Journal', is_default=True, metric=ensure_sleep_metric(user_id),
        )
    return journal


def journal_for_metric(metric):
    journal = Journal.objects.filter(metric=metric).first()
    if not journal:
        journal = Journal.objects.create(
            user_id=metric.user_id, name=metric.name, metric=metric, is_private=metric.is_private,
        )
    return journal


def sync_sleep(user_id, target_date, hours):
    """The sleep card writes DailyData.sleep_hours; mirror it into the Sleep metric."""
    metric = ensure_sleep_metric(user_id)
    existing = MetricEntry.objects.filter(metric=metric, date=target_date).order_by('-at').first()
    if hours is None:
        if existing:
            existing.delete()
        return
    if existing and existing.value == Decimal(str(hours)):
        return
    at = timezone.make_aware(datetime.combine(target_date, datetime.min.time())) + timedelta(hours=12)
    if existing:
        existing.data = {**existing.data, 'previous': float(existing.value)}
        existing.value, existing.at = Decimal(str(hours)), at
        existing.save()
    else:
        MetricEntry.objects.create(metric=metric, date=target_date, at=at, value=Decimal(str(hours)))


def sync_default_journal(user_id, target_date, text):
    """The journal pane writes DailyData.journal; keep the default journal's entry for the date."""
    journal = ensure_default_journal(user_id)
    entry = JournalEntry.objects.filter(journal=journal, date=target_date, metric_entry__isnull=True).first()
    text = (text or '').strip()
    if not text:
        if entry:
            entry.delete()
        return
    if entry:
        if entry.text != text:
            entry.text = text
            entry.save(update_fields=['text'])
    else:
        at = timezone.make_aware(datetime.combine(target_date, datetime.min.time())) + timedelta(hours=21)
        JournalEntry.objects.create(journal=journal, date=target_date, at=at, text=text)

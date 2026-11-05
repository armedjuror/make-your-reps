"""
Streak engine.

``DaySummary`` is the source of truth: one row per closed day. The global
streak is walked back from yesterday over those rows and cached into
``UserDetail.current_streak`` / ``longest_streak``. Habit streaks are walked
over scheduled days and respect frozen days and Light / Disrupted excusal.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from board.days import get_detail, logical_today, resolve_day
from board.models import (
    DayMode, DayPlan, DaySummary, Habit, HabitLog, HabitStatus, StreakRule, UserDetail,
)

COUNTS = {'met', 'reset', 'legacy'}   # outcomes that add to the streak
MAX_FREEZES = 2
FREEZE_EVERY = 7                      # +1 freeze per this many consecutive counted days
HISTORY_DAYS = 800


# ── Day close ──────────────────────────────────────────────

def had_activity(user_id, target_date):
    """Today's rule: any counted action on the date."""
    from board.models import DailyData, Task
    if HabitLog.objects.filter(habit__user_id=user_id, habit__is_system=False,
                               date=target_date, is_done=True).exists():
        return True
    if Task.objects.filter(user_id=user_id, is_deleted=False, is_done=True,
                           updated_at__date=target_date).exists():
        return True
    return DailyData.objects.filter(user_id=user_id, date=target_date).filter(
        _any_daily_signal()).exists()


def _any_daily_signal():
    from django.db.models import Q
    return Q(journal__gt='') | Q(sleep_hours__isnull=False) | Q(focus_minutes__gt=0)


def _consecutive_counted(user_id, upto_date):
    """Counted days walking back from ``upto_date`` inclusive; frozen days are skipped."""
    rows = dict(DaySummary.objects.filter(
        user_id=user_id, date__lte=upto_date, date__gte=upto_date - timedelta(days=HISTORY_DAYS),
    ).values_list('date', 'outcome'))
    n, d = 0, upto_date
    while d in rows:
        if rows[d] in COUNTS:
            n += 1
        elif rows[d] != 'frozen':
            break
        d -= timedelta(days=1)
    return n


@transaction.atomic
def close_day(user_id, target_date, now=None):
    """Close one date into a DaySummary. Idempotent. Consumes a freeze when it must."""
    existing = DaySummary.objects.filter(user_id=user_id, date=target_date).first()
    if existing:
        return existing
    detail = UserDetail.objects.select_for_update().get(user_id=user_id)
    resolved = resolve_day(user_id, target_date, now=now, closing=True, detail=detail)
    plan = resolved['plan']

    if detail.streak_rule == StreakRule.ROUTINE and resolved['required'] > 0:
        if resolved['met']:
            outcome = 'reset' if (plan and plan.reset_done_at and plan.source == 'reset') else 'met'
        else:
            outcome = 'missed'
    else:
        # Activity rule, or a day with no routine bar to meet.
        outcome = 'legacy' if had_activity(user_id, target_date) else 'missed'

    if outcome == 'missed' and detail.freezes > 0:
        prev = DaySummary.objects.filter(user_id=user_id, date=target_date - timedelta(days=1)).first()
        # Never miss twice: no freeze right after a frozen day.
        if not (prev and prev.outcome == 'frozen'):
            detail.freezes -= 1
            detail.save(update_fields=['freezes'])
            outcome = 'frozen'

    summary = DaySummary.objects.create(
        user_id=user_id, date=target_date, mode=resolved['mode'],
        required=resolved['required'], required_done=resolved['required_done'], outcome=outcome,
    )
    if outcome in COUNTS:
        run = _consecutive_counted(user_id, target_date)
        if run and run % FREEZE_EVERY == 0 and detail.freezes < MAX_FREEZES:
            detail.freezes += 1
            detail.save(update_fields=['freezes'])
    _settle_metric_habits(user_id, target_date)
    return summary


def close_pending_days(user_id, now=None, detail=None):
    """
    Close every unclosed date up to yesterday, in date order, so freezes are
    consumed in order. Covers a Celery task that did not run.
    """
    detail = detail or get_detail(user_id)
    today = logical_today(user_id, now, detail)
    last = DaySummary.objects.filter(user_id=user_id).order_by('-date').values_list('date', flat=True).first()
    start = (last + timedelta(days=1)) if last else today - timedelta(days=1)
    d, closed = start, []
    while d < today:
        closed.append(close_day(user_id, d, now=now))
        d += timedelta(days=1)
    return closed


def _settle_metric_habits(user_id, target_date):
    """At day close, 'at most' habits are done if the day's total stayed within target."""
    from board.metrics import day_value, effective_target
    for habit in Habit.objects.filter(user_id=user_id, status=HabitStatus.ACTIVE.value,
                                      metric__isnull=False, metric__direction='at_most'):
        m = habit.metric
        target = effective_target(m, user_id, target_date)
        if target is None:
            continue
        done = day_value(m, target_date) <= target
        log, _ = HabitLog.objects.get_or_create(habit=habit, date=target_date)
        if log.is_done != done:
            log.is_done = done
            log.save()


# ── Global streak ──────────────────────────────────────────

def compute_global_streak(user_id, now=None, detail=None):
    detail = detail or get_detail(user_id)
    today = logical_today(user_id, now, detail)
    rows = dict(DaySummary.objects.filter(
        user_id=user_id, date__lt=today, date__gte=today - timedelta(days=HISTORY_DAYS),
    ).values_list('date', 'outcome'))
    streak, d = 0, today - timedelta(days=1)
    while d in rows:
        if rows[d] in COUNTS:
            streak += 1
        elif rows[d] != 'frozen':
            break
        d -= timedelta(days=1)
    if today_is_met(user_id, today, detail, now):
        streak += 1
    return streak


def today_is_met(user_id, today, detail, now=None):
    if detail.streak_rule == StreakRule.ROUTINE:
        resolved = resolve_day(user_id, today, now=now, detail=detail)
        if resolved['required'] > 0:
            return resolved['met']
    return had_activity(user_id, today)


def refresh_streak(user_id, now=None):
    """Close pending days, recompute the streak and write the cache. Returns the detail row."""
    detail = get_detail(user_id)
    close_pending_days(user_id, now=now, detail=detail)
    detail.refresh_from_db()
    streak = compute_global_streak(user_id, now=now, detail=detail)
    changed = []
    if detail.current_streak != streak:
        detail.current_streak = streak
        changed.append('current_streak')
    if streak > detail.longest_streak:
        detail.longest_streak = streak
        changed.append('longest_streak')
    if changed:
        detail.save(update_fields=changed)
    return detail


# ── Habit streaks ──────────────────────────────────────────

class StreakContext:
    """Per-user facts a habit streak needs, loaded once per request."""

    def __init__(self, user_id, start=None, today=None):
        detail = get_detail(user_id)
        self.today = today or logical_today(user_id, detail=detail)
        floor = start or (self.today - timedelta(days=HISTORY_DAYS))
        self.modes = dict(DayPlan.objects.filter(user_id=user_id, date__gte=floor)
                          .values_list('date', 'mode'))
        self.frozen = set(DaySummary.objects.filter(user_id=user_id, date__gte=floor, outcome='frozen')
                          .values_list('date', flat=True))


def _excused(habit, ctx, d):
    if d in ctx.frozen:
        return True
    mode = ctx.modes.get(d, DayMode.NORMAL)
    return (mode == DayMode.LIGHT and habit.on_light == 'excused') or \
           (mode == DayMode.DISRUPTED and habit.on_disrupted == 'excused')


def habit_streaks(habit, logs, ctx):
    """
    (current, max) for a habit. ``logs`` is a {date: is_done} dict.

    Walk scheduled days: done adds one. A not-done day that is frozen, or
    excused by the day's mode, neither breaks nor adds. Anything else breaks.
    An unanswered today never breaks the streak.
    """
    freq = habit.frequency or []
    min_date = habit.created_at.date()
    today = ctx.today

    def scheduled(d):
        return not freq or d.weekday() in freq

    # Current: walk back from today.
    current, d = 0, today
    if scheduled(today) and not logs.get(today, False):
        d = today - timedelta(days=1)
    while d >= min_date:
        if not scheduled(d):
            d -= timedelta(days=1)
            continue
        if logs.get(d, False):
            current += 1
        elif not _excused(habit, ctx, d):
            break
        d -= timedelta(days=1)

    # Max: walk forward over the whole history.
    first = min((k for k, v in logs.items() if v), default=None)
    best = run = 0
    if first:
        d = first
        while d <= today:
            if scheduled(d):
                if logs.get(d, False):
                    run += 1
                    best = max(best, run)
                elif d == today:
                    pass
                elif not _excused(habit, ctx, d):
                    run = 0
            d += timedelta(days=1)
    return current, max(best, current)

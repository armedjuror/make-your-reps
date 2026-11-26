"""Pomodoro focus mode on the shared player: start, state, park a thought, distraction, finish."""
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from board.days import logical_today
from board.models import DailyData, Habit, HabitLog, RoutineEntry, Task, UserDetail
from fitness.steps import build_focus_steps
from focus.models import FocusSession, FocusStatus

PAUSE_TIMEOUT = timedelta(minutes=30)
XP_PER_CYCLE = 10
MIN_SHARE = 0.5


class FocusError(Exception):
    pass


def default_plan(user_id):
    d = UserDetail.objects.filter(user_id=user_id).first()
    return {'focus_min': d.pomodoro_focus if d else 25, 'break_min': d.pomodoro_break if d else 5,
            'long_break_min': d.pomodoro_long_break if d else 15, 'cycles': d.pomodoro_cycles if d else 4}


def clean_plan(user_id, data):
    plan = default_plan(user_id)
    for k, lo, hi in (('focus_min', 1, 180), ('break_min', 1, 60), ('long_break_min', 1, 90), ('cycles', 1, 12)):
        if data.get(k) not in (None, ''):
            try:
                plan[k] = max(lo, min(int(data[k]), hi))
            except (TypeError, ValueError):
                raise FocusError(f'{k} must be a number')
    return plan


def expire_stale(user_id, now=None):
    now = now or timezone.now()
    today = logical_today(user_id)
    for s in FocusSession.objects.filter(user_id=user_id, status=FocusStatus.IN_PROGRESS):
        if s.date < today or (s.paused_at and now - s.paused_at > PAUSE_TIMEOUT):
            s.status, s.ended_at = FocusStatus.ABANDONED, s.paused_at or now
            s.save(update_fields=['status', 'ended_at'])


def active(user_id):
    expire_stale(user_id)
    return FocusSession.objects.filter(user_id=user_id, status=FocusStatus.IN_PROGRESS).first()


@transaction.atomic
def start(user_id, data, now=None):
    now = now or timezone.now()
    existing = active(user_id)
    if existing:
        return existing, True
    plan = clean_plan(user_id, data)
    task = Task.objects.filter(id=data.get('task'), user_id=user_id, is_deleted=False).first() if data.get('task') else None
    habit = Habit.objects.filter(id=data.get('habit'), user_id=user_id).first() if data.get('habit') else None
    entry = RoutineEntry.objects.filter(id=data.get('routine_entry'), user_id=user_id).first() if data.get('routine_entry') else None
    title = (task.task_name if task else habit.habit if habit else entry.title if entry else str(data.get('title') or ''))[:255]
    steps = build_focus_steps(plan['focus_min'], plan['break_min'], plan['cycles'], plan['long_break_min'])
    s = FocusSession.objects.create(
        user_id=user_id, task=task, habit=habit, routine_entry=entry, title=title, date=logical_today(user_id),
        plan=plan, steps=steps, state={'index': 0, 'step_started_at': now.isoformat(), 'paused_seconds': 0},
        started_at=now,
    )
    return s, False


def save_state(s, index=None, paused=None, now=None):
    now = now or timezone.now()
    if s.status != FocusStatus.IN_PROGRESS:
        raise FocusError('This session has ended')
    state = dict(s.state or {})
    if index is not None:
        index = max(0, min(int(index), len(s.steps)))
        if index != state.get('index'):
            # Every focus step passed counts as a completed cycle
            state['index'], state['step_started_at'] = index, now.isoformat()
            s.completed_cycles = max(s.completed_cycles, sum(1 for st in s.steps[:index] if st['kind'] == 'focus'))
    if paused is True and not s.paused_at:
        s.paused_at = now
    elif paused is False and s.paused_at:
        state['paused_seconds'] = state.get('paused_seconds', 0) + int((now - s.paused_at).total_seconds())
        s.paused_at = None
    s.state = state
    s.save()
    return s


def park(s, text):
    """'Park a thought': a one-line todo in the inbox, without leaving the screen."""
    text = (text or '').strip()
    if not text:
        raise FocusError('Write the thought first')
    t = Task.objects.create(user_id=s.user_id, task_name=text[:500])
    s.parked = (s.parked or []) + [t.id]
    s.save(update_fields=['parked'])
    return t


def distracted(s):
    FocusSession.objects.filter(pk=s.pk).update(interruptions=F('interruptions') + 1)
    s.refresh_from_db()
    return s


@transaction.atomic
def finish(s, tick=False, now=None):
    """
    Completed cycles earn XP (10 each) once the elapsed time covers at least half
    of their focus time. Focus minutes go to the day's focus total like the widget's.
    """
    if s.status != FocusStatus.IN_PROGRESS:
        raise FocusError('This session has already ended')
    now = now or timezone.now()
    if s.paused_at:
        s.state['paused_seconds'] = s.state.get('paused_seconds', 0) + int((now - s.paused_at).total_seconds())
        s.paused_at = None
    idx = int(s.state.get('index', 0))
    cycles = sum(1 for st in s.steps[:idx] if st['kind'] == 'focus')
    # The focus step being played counts too if it ran to (nearly) its end
    if idx < len(s.steps) and s.steps[idx]['kind'] == 'focus' and s.state.get('step_started_at'):
        from datetime import datetime
        ran = (now - datetime.fromisoformat(s.state['step_started_at'])).total_seconds()
        if ran >= s.steps[idx]['est_seconds'] - 5:
            cycles += 1
    s.completed_cycles = max(s.completed_cycles, cycles)
    s.ended_at = now
    elapsed = (now - s.started_at).total_seconds()
    focus_seconds = s.completed_cycles * s.plan.get('focus_min', 25) * 60
    trusted = elapsed >= MIN_SHARE * focus_seconds
    s.focus_minutes = s.completed_cycles * s.plan.get('focus_min', 25) if trusted else 0
    s.xp = XP_PER_CYCLE * s.completed_cycles if trusted else 0
    s.status = FocusStatus.COMPLETED
    s.save()
    if s.focus_minutes:
        dd, _ = DailyData.objects.get_or_create(user_id=s.user_id, date=timezone.localdate())
        DailyData.objects.filter(pk=dd.pk).update(focus_minutes=F('focus_minutes') + s.focus_minutes)
    if s.xp:
        from board.gamification import award_points, update_daily_streak
        update_daily_streak(s.user_id)
        award_points(s.user_id, 'xp', multiplier=s.xp)
    if tick:
        tick_linked(s)
    return s


def tick_linked(s):
    """Tick the task or habit the session was for (only after the user confirms on the summary)."""
    if s.status != FocusStatus.COMPLETED:
        raise FocusError('Finish the session first')
    if s.task_id:
        Task.objects.filter(pk=s.task_id).update(is_done=True)
    elif s.habit_id:
        log, _ = HabitLog.objects.get_or_create(habit_id=s.habit_id, date=s.date)
        if not log.is_done:
            log.is_done = True
            log.save()
            from board.gamification import award_points, update_daily_streak
            update_daily_streak(s.user_id)
            award_points(s.user_id, 'habit')
    elif s.routine_entry_id:
        from board.models import BlockLog, BlockStatus
        e = s.routine_entry
        BlockLog.objects.update_or_create(user_id=s.user_id, date=s.date, entry=e, defaults=dict(
            title=e.title, scheduled_time=e.time, tier=e.tier, status=BlockStatus.DONE))

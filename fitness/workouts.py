"""
Workout sessions: start / resume, set logging, finish with the trust and
partial-credit rules, progression suggestions, PRs, and logging without the
player. Pure server logic; views in fitness.workout_views.
"""
import re
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from board.days import logical_today
from board.models import HabitKind, HabitStepLog
from fitness.models import (
    DayKind, Exercise, FitnessProfile, SessionStatus, SetLog, WorkoutSession,
)
from fitness.program import active_program, fitness_habits, program_day, refresh
from fitness.steps import build_workout_steps, est_total, planned_sets

PAUSE_TIMEOUT = timedelta(minutes=30)
MIN_DURATION_SHARE = 0.5      # ended - started must be >= 50% of the summed est_seconds
MIN_SETS_SHARE = 0.5          # >= 50% of planned sets done counts as completed
XP_BASE, XP_PER_SET = 20, 2
MANUAL_DAYS_BACK = 7
BANDS = ['yellow band', 'red band', 'green band', 'blue band', 'black band', 'silver band', 'gold band']
DEFAULT_KG = 70.0


class WorkoutError(Exception):
    pass


# ── Loads ──────────────────────────────────────────────────

def _kg(load):
    m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*kg\s*$', load or '', re.I)
    return float(m.group(1)) if m else None


def load_rank(load):
    """Comparable rank for a load: bands by colour order, kg by weight; None if unknown."""
    load = (load or '').strip().lower()
    if load in BANDS:
        return (0, BANDS.index(load))
    kg = _kg(load)
    return (1, kg) if kg is not None else None


def next_load(load):
    load = (load or '').strip().lower()
    if load in BANDS:
        i = BANDS.index(load)
        return BANDS[i + 1] if i + 1 < len(BANDS) else None
    kg = _kg(load)
    return f'{kg + 2:g} kg' if kg is not None else None


def prev_load(load):
    load = (load or '').strip().lower()
    if load in BANDS:
        i = BANDS.index(load)
        return BANDS[i - 1] if i > 0 else None
    kg = _kg(load)
    return f'{max(kg - 2, 0):g} kg' if kg else None


# ── Lookups ────────────────────────────────────────────────

def activity_habit(user_id):
    return fitness_habits(user_id).filter(kind=HabitKind.ACTIVITY).first()


def body_kg(user_id):
    from board.models import MetricEntry
    e = MetricEntry.objects.filter(metric__user_id=user_id, metric__fitness_key='weight').order_by('-date', '-at').first()
    if e:
        return float(e.value)
    p = FitnessProfile.objects.filter(user_id=user_id).first()
    return float(p.weight_kg) if p and p.weight_kg else DEFAULT_KG


def library_for(steps_or_ids):
    ids = {s.get('exercise_id') if isinstance(s, dict) else s for s in steps_or_ids}
    return Exercise.objects.in_bulk([i for i in ids if i])


def expire_stale(user_id, now=None):
    """Sessions paused 30+ minutes, or left open from an earlier day, become abandoned."""
    now = now or timezone.now()
    today = logical_today(user_id)
    for s in WorkoutSession.objects.filter(user_id=user_id, status=SessionStatus.IN_PROGRESS):
        if s.date < today or (s.paused_at and now - s.paused_at > PAUSE_TIMEOUT):
            s.status = SessionStatus.ABANDONED
            s.ended_at = s.paused_at or now
            s.save(update_fields=['status', 'ended_at'])


def active_session(user_id):
    expire_stale(user_id)
    return WorkoutSession.objects.filter(user_id=user_id, status=SessionStatus.IN_PROGRESS).first()


def today_session_day(user_id, target_date):
    habit = activity_habit(user_id)
    program = active_program(habit) if habit else None
    if not program:
        return habit, None, None, None
    phase, day = program_day(program, target_date)
    return habit, program, phase, day


def program_steps(program, day):
    """The step list for a session day, with the program's swaps applied and dropped moves removed."""
    overrides = program.overrides or {}
    dropped = {k for k, v in overrides.items() if v is None}
    lib = library_for([i.get('exercise') for b in day.blocks for i in b.get('items', [])]
                      + [v for v in overrides.values() if v])
    from fitness.steps import _finish
    steps = build_workout_steps(day, lib, overrides={k: v for k, v in overrides.items() if v})
    if dropped:
        steps = [s for s in steps if s.get('exercise_id') not in dropped]
        # no two rests in a row, no rest first or last
        out = []
        for s in steps:
            if s['kind'] == 'rest' and (not out or out[-1]['kind'] == 'rest'):
                continue
            out.append(s)
        while out and out[-1]['kind'] == 'rest':
            out.pop()
        steps = _finish(out, lib)
    return steps


# ── Start ──────────────────────────────────────────────────

@transaction.atomic
def start_session(user_id, now=None):
    """Resume today's open session, or start one from today's DayTemplate."""
    now = now or timezone.now()
    existing = active_session(user_id)
    if existing:
        if existing.paused_at:
            existing.state = {**existing.state, 'paused_seconds': existing.state.get('paused_seconds', 0)
                              + int((now - existing.paused_at).total_seconds())}
            existing.paused_at = None
            existing.save(update_fields=['state', 'paused_at'])
        return existing, True
    today = logical_today(user_id)
    habit, program, phase, day = today_session_day(user_id, today)
    if not day or day.kind != DayKind.SESSION:
        raise WorkoutError('No workout planned today')
    from fitness.program import is_disrupted
    if is_disrupted(user_id, today):
        raise WorkoutError('Today is a disrupted day: a 20 min walk replaces the workout')
    steps = program_steps(program, day)
    session = WorkoutSession.objects.create(
        user_id=user_id, program=program, habit=habit, date=today, name=day.name or 'Workout',
        steps=steps, state={'index': 0, 'step_started_at': now.isoformat(), 'paused_seconds': 0},
        started_at=now, est_seconds=est_total(steps),
    )
    return session, False


# ── State ──────────────────────────────────────────────────

def save_state(session, index=None, paused=None, steps=None, extra=None, now=None):
    """Called on every step change, pause and resume, so a closed tab resumes on any device."""
    now = now or timezone.now()
    if session.status != SessionStatus.IN_PROGRESS:
        raise WorkoutError('This session has ended')
    state = dict(session.state or {})
    if index is not None:
        index = max(0, min(int(index), len(session.steps)))
        if index != state.get('index'):
            state['index'] = index
            state['step_started_at'] = now.isoformat()
    if steps is not None:
        # The player may only rewrite what is still ahead (switch to an easier move, drop a round, finish lighter)
        cut = state.get('index', 0) + 1
        session.steps = session.steps[:cut] + [s for s in steps[cut:] if isinstance(s, dict)]
        for i, s in enumerate(session.steps):
            s['index'] = i
        session.est_seconds = est_total(session.steps)
    if extra:
        for k in ('rest_extensions', 'struggle', 'coach'):
            if k in extra:
                state[k] = extra[k]
    if paused is True and not session.paused_at:
        session.paused_at = now
    elif paused is False and session.paused_at:
        state['paused_seconds'] = state.get('paused_seconds', 0) + int((now - session.paused_at).total_seconds())
        session.paused_at = None
    session.state = state
    session.save()
    return session


# ── Sets, PRs, auto-tick ───────────────────────────────────

def _previous_sets(user_id, exercise_id, exclude_session):
    return SetLog.objects.filter(session__user_id=user_id, exercise_id=exercise_id, skipped=False) \
        .exclude(session=exclude_session).exclude(session__status=SessionStatus.SKIPPED)


def detect_pr(user_id, log):
    """'First time at red band' / 'Most reps at red band: 14' against earlier sessions."""
    if log.skipped or not log.reps_done:
        return None
    prev = list(_previous_sets(user_id, log.exercise_id, log.session_id).values_list('load', 'reps_done'))
    if not prev:
        return None
    name = log.exercise.name
    rank = load_rank(log.load)
    prev_ranks = [load_rank(l) for l, _ in prev if load_rank(l) is not None]
    if rank and prev_ranks and all(r[0] == rank[0] for r in prev_ranks) and rank > max(prev_ranks):
        return f'{name}: first time at {log.load}'
    at_load = [r for l, r in prev if (l or '').lower() == (log.load or '').lower() and r]
    if at_load and log.reps_done > max(at_load):
        return f'{name}: most reps at {log.load or "this load"} ({log.reps_done})'
    return None


def _units_done(session, exercise_id):
    return set(SetLog.objects.filter(session=session, exercise_id=exercise_id, skipped=False)
               .values_list('set_index', flat=True))


def sync_exercise_subtask(session, exercise_id):
    """Exercise subtasks auto-tick from SetLog once every planned set is done."""
    if not session.habit_id:
        return
    planned = {i for e, i in planned_sets(session.steps) if e == exercise_id}
    if not planned:
        return
    done = planned <= _units_done(session, exercise_id)
    from board.models import HabitStep
    step = HabitStep.objects.filter(habit_id=session.habit_id, key=f'ex:{exercise_id}').first()
    if not step:
        refresh(session.habit, session.date, settle=False)
        step = HabitStep.objects.filter(habit_id=session.habit_id, key=f'ex:{exercise_id}').first()
        if not step:
            return
    log = HabitStepLog.objects.filter(step=step, date=session.date).first()
    if done and not (log and log.done):
        log = log or HabitStepLog(step=step, date=session.date)
        log.done, log.source = True, 'workout'
        log.save()
        refresh(session.habit, session.date)
    elif not done and log and log.done and log.source == 'workout':
        log.done = False
        log.save(update_fields=['done'])
        refresh(session.habit, session.date)


@transaction.atomic
def log_set(session, data):
    """Upsert one set. Returns (SetLog, pr_text_or_None)."""
    if session.status not in (SessionStatus.IN_PROGRESS,):
        raise WorkoutError('This session has ended')
    ex_id = data.get('exercise') or data.get('exercise_id')
    ex = Exercise.objects.filter(id=ex_id).first()
    if not ex:
        raise WorkoutError('Unknown exercise')
    try:
        set_index = int(data.get('set_index') or 1)
        reps = data.get('reps_done')
        reps = None if reps in (None, '') else max(0, min(int(reps), 500))
        secs = data.get('seconds_done')
        secs = None if secs in (None, '') else max(0, min(int(secs), 3600))
        rir = data.get('rir')
        rir = None if rir in (None, '') else max(0, min(int(rir), 10))
    except (TypeError, ValueError):
        raise WorkoutError('reps, seconds and rir must be numbers')
    side = data.get('side') or ''
    if side not in ('', 'right', 'left'):
        raise WorkoutError('side must be right or left')
    step = next((s for s in session.steps if s.get('exercise_id') == ex_id and s.get('set_index') == set_index
                 and (s.get('side') or '') == side), None)
    log, _ = SetLog.objects.update_or_create(
        session=session, exercise=ex, set_index=set_index, side=side,
        defaults=dict(target=(step or {}).get('target') or {}, reps_done=reps, seconds_done=secs,
                      load=str(data.get('load') or '')[:24].strip().lower(), rir=rir,
                      skipped=bool(data.get('skipped'))),
    )
    pr = detect_pr(session.user_id, log)
    if pr:
        prs = session.summary.get('prs', [])
        if pr not in prs:
            session.summary = {**session.summary, 'prs': prs + [pr]}
            session.save(update_fields=['summary'])
    sync_exercise_subtask(session, ex_id)
    return log, pr


def last_performance(user_id, exercise_ids, exclude_session=None):
    """{exercise_id: {reps, load, at}} from the latest non-skipped set of an earlier session."""
    out = {}
    for ex_id in set(exercise_ids):
        qs = SetLog.objects.filter(session__user_id=user_id, exercise_id=ex_id, skipped=False,
                                   reps_done__isnull=False)
        if exclude_session:
            qs = qs.exclude(session=exclude_session)
        last = qs.order_by('-session__started_at', '-set_index').first()
        if last:
            out[ex_id] = {'reps': last.reps_done, 'load': last.load, 'date': last.session.date.isoformat()}
    return out


# ── Progression ────────────────────────────────────────────

def _session_sets(user_id, exercise_id, limit=2):
    """Per-session lists of non-skipped sets, newest first."""
    sessions = list(WorkoutSession.objects.filter(
        user_id=user_id, sets__exercise_id=exercise_id, sets__skipped=False,
        status__in=[SessionStatus.COMPLETED, SessionStatus.PARTIAL, SessionStatus.IN_PROGRESS],
    ).distinct().order_by('-started_at')[:limit])
    return [list(s.sets.filter(exercise_id=exercise_id, skipped=False)) for s in sessions]


def progression_for(user_id, exercise):
    """
    Up: every set hit reps_max with rir >= 2 (or, with no rir logged, reps_max
    hit two sessions running) -> next load / progression move.
    Down: reps_min missed on 2+ sets for 2 sessions running -> previous load / regression.
    Never applied silently: returned as a suggestion for the next session.
    """
    hist = _session_sets(user_id, exercise.id)
    if not hist or not hist[0]:
        return None
    latest = hist[0]

    def top(sets):
        out = []
        for s in sets:
            hi = (s.target.get('reps') or [None, None])[-1]
            out.append(hi is not None and s.reps_done is not None and s.reps_done >= hi)
        return bool(out) and all(out)

    def missed(sets):
        n = 0
        for s in sets:
            lo = (s.target.get('reps') or [None])[0]
            if lo is not None and s.reps_done is not None and s.reps_done < lo:
                n += 1
        return n >= 2

    load = next((s.load for s in reversed(latest) if s.load), '')
    rirs = [s.rir for s in latest if s.rir is not None]
    up = top(latest) and ((rirs and len(rirs) == len(latest) and min(rirs) >= 2) or
                          (not rirs and len(hist) > 1 and top(hist[1])))
    if up:
        nxt = next_load(load)
        if nxt:
            return {'type': 'up', 'exercise': exercise.id, 'load': nxt, 'text': f'Go heavier: {nxt}'}
        if exercise.progression_id:
            return {'type': 'up', 'exercise': exercise.id, 'to_exercise': exercise.progression_id,
                    'text': f'Ready for {exercise.progression.name}'}
        return None
    if missed(latest) and len(hist) > 1 and missed(hist[1]):
        prv = prev_load(load)
        if prv:
            return {'type': 'down', 'exercise': exercise.id, 'load': prv, 'text': f'Try {prv} next time'}
        if exercise.regression_id:
            return {'type': 'down', 'exercise': exercise.id, 'to_exercise': exercise.regression_id,
                    'text': f'Try {exercise.regression.name} next time'}
    return None


def suggestions_for(user_id, exercise_ids):
    exs = Exercise.objects.select_related('progression', 'regression').in_bulk(list(set(exercise_ids)))
    out = {}
    for ex_id, ex in exs.items():
        s = progression_for(user_id, ex)
        if s:
            out[ex_id] = s
    return out


# ── Finish ─────────────────────────────────────────────────

def _tick_finish(session, done):
    if not session.habit_id:
        return
    from board.models import HabitStep
    refresh(session.habit, session.date, settle=False)
    step = HabitStep.objects.filter(habit_id=session.habit_id, key='finish').first()
    if not step:
        return
    log = HabitStepLog.objects.filter(step=step, date=session.date).first()
    if done and not (log and log.done):
        log = log or HabitStepLog(step=step, date=session.date)
        log.done, log.source = True, 'workout'
        log.save()
    refresh(session.habit, session.date)


def _notify_partners(session):
    """'Ajwad finished Upper body' through the accountability-partner feature."""
    if not session.habit_id:
        return
    from board.models import AccountabilityPartner, AccountabilityPartnerStatus, TimelineEvent, TimelineEventType
    owner = session.user.get_full_name() or session.user.first_name or session.user.username
    for ap in AccountabilityPartner.objects.filter(habit_id=session.habit_id, partner__isnull=False,
                                                   status=AccountabilityPartnerStatus.ACTIVE):
        TimelineEvent.objects.create(
            user=ap.partner, timestamp=session.ended_at or timezone.now(), event_type=TimelineEventType.TEXT,
            event=f'{owner} finished {session.name}',
            reference={'model': 'WorkoutSession', 'id': session.id, 'type': 'partner'},
        )


def summarize(session):
    sets = list(session.sets.select_related('exercise'))
    planned = planned_sets(session.steps)
    done_units = {(s.exercise_id, s.set_index) for s in sets if not s.skipped}
    done = len(done_units & planned)
    reps = sum(s.reps_done or 0 for s in sets if not s.skipped)
    return {'sets_done': done, 'sets_planned': len(planned), 'total_reps': reps,
            'exercises': sorted({s.exercise.name for s in sets if not s.skipped})}


def estimate_kcal(session, seconds):
    lib = library_for(session.steps)
    work = [s for s in session.steps if s.get('exercise_id')]
    total = sum(s.get('est_seconds', 0) for s in work) or 1
    met = sum((lib[s['exercise_id']].met if s['exercise_id'] in lib else 3.5) * s.get('est_seconds', 0)
              for s in work) / total if work else 3.5
    return int(round(met * body_kg(session.user_id) * (seconds / 3600)))


@transaction.atomic
def finish_session(session, mode='finish', now=None, duration_seconds=None):
    """
    mode: finish (end now with what's done) / end (End anyway).
    Completed = >= 50% of planned sets AND (ended - started) >= 50% of est time.
    Below that the session is saved as partial: no streak, no XP, sets still feed progression.
    """
    if session.status != SessionStatus.IN_PROGRESS:
        raise WorkoutError('This session has already ended')
    now = now or timezone.now()
    if session.paused_at:
        session.state['paused_seconds'] = session.state.get('paused_seconds', 0) + int((now - session.paused_at).total_seconds())
        session.paused_at = None
    session.ended_at = now
    elapsed = duration_seconds if duration_seconds is not None else (now - session.started_at).total_seconds()
    totals = summarize(session)
    planned = totals['sets_planned'] or 1
    duration_ok = elapsed >= MIN_DURATION_SHARE * (session.est_seconds or 0)
    sets_ok = totals['sets_done'] / planned >= MIN_SETS_SHARE
    completed = duration_ok and sets_ok
    session.status = SessionStatus.COMPLETED if completed else SessionStatus.PARTIAL
    active = max(0, elapsed - session.state.get('paused_seconds', 0)) if duration_seconds is None else elapsed
    session.est_kcal = estimate_kcal(session, active)
    session.xp = XP_BASE + XP_PER_SET * totals['sets_done'] if completed else 0
    ex_ids = [s['exercise_id'] for s in session.steps if s.get('exercise_id') and not s.get('warmup')]
    session.summary = {
        **session.summary, **totals, 'duration_seconds': int(elapsed), 'active_seconds': int(active),
        'duration_ok': duration_ok, 'mode': mode, 'est_kcal': session.est_kcal,
        'suggestions': suggestions_for(session.user_id, ex_ids),
    }
    session.save()
    if completed:
        from board.gamification import award_points, update_daily_streak
        if session.date == logical_today(session.user_id):
            update_daily_streak(session.user_id)
        award_points(session.user_id, 'xp', multiplier=session.xp)
        _tick_finish(session, True)
        _notify_partners(session)
    session.summary['streak'] = session.habit.current_streak if session.habit_id else 0
    session.save(update_fields=['summary'])
    return session


def skip_today(user_id):
    today = logical_today(user_id)
    habit, program, _, day = today_session_day(user_id, today)
    if not day or day.kind != DayKind.SESSION:
        raise WorkoutError('No workout planned today')
    now = timezone.now()
    s, _ = WorkoutSession.objects.get_or_create(
        user_id=user_id, date=today, status=SessionStatus.SKIPPED,
        defaults=dict(program=program, habit=habit, name=day.name, source='timeline', started_at=now, ended_at=now))
    return s


# ── Log without the player ─────────────────────────────────

def planned_session(user_id, target_date):
    """(habit, program, day, steps) for a past or present session day."""
    habit, program, _, day = today_session_day(user_id, target_date)
    if not day or day.kind != DayKind.SESSION:
        raise WorkoutError('No workout was planned that day')
    return habit, program, day, program_steps(program, day)


@transaction.atomic
def manual_log(user_id, target_date, as_planned=True, sets=None, start_time=None, duration_min=None):
    """
    One-screen log: "Did it as planned" logs every set at its target (reps_max), or
    per-set rows. Creates the same WorkoutSession + SetLog rows (source="manual").
    """
    today = logical_today(user_id)
    if target_date > today:
        raise WorkoutError('That date is in the future')
    if target_date < today - timedelta(days=MANUAL_DAYS_BACK):
        raise WorkoutError(f'You can log up to {MANUAL_DAYS_BACK} days back')
    if WorkoutSession.objects.filter(user_id=user_id, date=target_date, status=SessionStatus.COMPLETED).exists():
        raise WorkoutError('That workout is already logged')
    habit, program, day, steps = planned_session(user_id, target_date)
    est = est_total(steps)
    try:
        duration = int(duration_min) * 60 if duration_min not in (None, '') else est
        if start_time:
            h, m = (int(x) for x in str(start_time)[:5].split(':'))
        else:
            h, m = 18, 0
    except (TypeError, ValueError):
        raise WorkoutError('Start time must be HH:MM and duration a number of minutes')
    started = timezone.make_aware(datetime.combine(target_date, datetime.min.time())) + timedelta(hours=h, minutes=m)
    # An open player session for that day is replaced by the manual log
    WorkoutSession.objects.filter(user_id=user_id, date=target_date, status=SessionStatus.IN_PROGRESS) \
        .update(status=SessionStatus.ABANDONED, ended_at=timezone.now())
    session = WorkoutSession.objects.create(
        user_id=user_id, program=program, habit=habit, date=target_date, name=day.name or 'Workout',
        source='manual', steps=steps, state={'index': len(steps)}, started_at=started, est_seconds=est,
    )
    work = [s for s in steps if s['kind'] in ('exercise_set', 'exercise_timed') and not s.get('warmup')]
    rows = {}
    if as_planned:
        for s in work:
            t = s['target']
            rows[(s['exercise_id'], s['set_index'], s.get('side') or '')] = {
                'reps_done': t['reps'][1] if 'reps' in t else None,
                'seconds_done': t.get('seconds'), 'load': '', 'skipped': False}
    for r in sets or []:
        key = (r.get('exercise'), int(r.get('set_index') or 1), r.get('side') or '')
        rows[key] = {**rows.get(key, {}), **{k: r.get(k) for k in ('reps_done', 'seconds_done', 'load', 'skipped', 'rir') if k in r}}
    for (ex_id, idx, side), r in rows.items():
        log_set(session, {'exercise': ex_id, 'set_index': idx, 'side': side, **r})
    return finish_session(session, mode='manual', now=started + timedelta(seconds=duration), duration_seconds=duration)


def contraindicate(user_id, joint):
    """'Something hurts': add the joint to the profile and swap or drop affected moves in the program."""
    profile, _ = FitnessProfile.objects.get_or_create(user_id=user_id)
    flags = list(profile.health_flags or [])
    if joint not in flags:
        flags.append(joint)
        profile.health_flags = flags
        profile.save(update_fields=['health_flags'])
    habit = activity_habit(user_id)
    program = active_program(habit) if habit else None
    if not program:
        return {}
    ids = {i.get('exercise') for ph in program.phases.all() for d in ph.days.all()
           for b in d.blocks for i in b.get('items', []) if i.get('exercise')}
    changes = {}
    for ex in Exercise.objects.filter(id__in=ids):
        if joint not in (ex.contraindications or []):
            continue
        sub = ex.regression
        while sub and joint in (sub.contraindications or []):
            sub = sub.regression
        changes[ex.id] = sub.id if sub else None
    program.overrides = {**(program.overrides or {}), **changes}
    program.save(update_fields=['overrides'])
    return changes

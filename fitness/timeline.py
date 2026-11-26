"""
Fitness items on the Today timeline, computed (never stored) from the Program,
targets and the onboarding times. They are timeline items, not routine blocks,
so they never move the user's own routine. Ticking here or in the Fitness tab
ticks the same trackers and subtasks.
"""
from datetime import datetime, time, timedelta
from django.utils import timezone

from board import metrics as mx
from board.models import HabitKind, HabitStepLog, MetricEntry
from fitness.models import DayKind, FitnessProfile, FitnessTick, SessionStatus, WorkoutSession
from fitness.program import active_program, expand, fitness_habits, is_disrupted, program_day

DEFAULT_TIMES = {'wake': '06:00', 'workout': '18:00', 'weigh_in_day': 0,
                 'meals': {'breakfast': '08:00', 'lunch': '13:00', 'snack': '17:00', 'dinner': '20:30'}}
MEAL_LABELS = {'breakfast': 'Breakfast', 'lunch': 'Lunch', 'snack': 'Evening snack', 'dinner': 'Dinner'}
SLEEP_HOURS = 7.5
SNACK_BEFORE_MIN = 75
WATER_EVERY_H = 2


def times_for(profile):
    t = {**DEFAULT_TIMES, **((profile.times if profile else {}) or {})}
    t['meals'] = {**DEFAULT_TIMES['meals'], **(t.get('meals') or {})}
    return t


def _t(value):
    try:
        h, m = (int(x) for x in str(value)[:5].split(':'))
        return time(h, m)
    except (TypeError, ValueError):
        return None


def _at(d, t, minutes=0):
    return timezone.make_aware(datetime.combine(d, t)) + timedelta(minutes=minutes)


def _event(key, d, ts, text, kind, icon, action=None, done=False, notify=False, **extra):
    iso = ts.isoformat()
    return {'id': f'fit-{key}-{d}', 'timestamp': iso, 'event_type': 'fitness', 'event': text,
            'reference': {'model': 'Fitness', 'kind': kind}, 'action': None if done else action,
            'action_response': {'done': True} if done else None, 'created_at': iso, 'updated_at': iso,
            'icon': icon, 'notify': notify, 'completable': bool(action), 'fit': {'kind': kind, **extra}}


def _fmt(v):
    v = float(v)
    return f'{v:,.1f}'.rstrip('0').rstrip('.') if v != int(v) else f'{int(v):,}'


def fitness_events(user_id, d, hidden_habits=(), hidden_metrics=()):
    habits = {h.kind: h for h in fitness_habits(user_id) if h.id not in hidden_habits}
    if not habits:
        return []
    profile = FitnessProfile.objects.filter(user_id=user_id).first()
    times = times_for(profile)
    targets = (profile.targets if profile else {}) or {}
    metrics = {m.fitness_key: m for m in mx.Metric.objects.filter(user_id=user_id, domain='fitness')
               .exclude(id__in=hidden_metrics)}
    wake = _t(times['wake']) or time(6)
    bed_dt = _at(d, wake) + timedelta(days=1) - timedelta(hours=SLEEP_HOURS)   # tonight's bedtime
    out = []

    activity = habits.get(HabitKind.ACTIVITY)
    kind, day, program = None, None, None
    if activity:
        program = active_program(activity)
        if program:
            _, day = program_day(program, d)
            kind = day.kind if day else None
    disrupted = is_disrupted(user_id, d)
    session_day = kind == DayKind.SESSION and not disrupted

    # Workout + pre-workout snack
    if session_day:
        from fitness.workouts import program_steps
        steps = program_steps(program, day)
        est = sum(s['est_seconds'] for s in steps)
        n = len({s['exercise_id'] for s in steps if s.get('exercise_id') and not s.get('warmup')})
        wt = _t(times['workout']) or time(18)
        sess = WorkoutSession.objects.filter(user_id=user_id, date=d).exclude(status=SessionStatus.ABANDONED) \
            .order_by('-started_at').first()
        status = sess.status if sess else None
        done = status in (SessionStatus.COMPLETED, SessionStatus.SKIPPED)
        ev = _event('workout', d, _at(d, wt), f'{day.name or "Workout"} · {n} exercises · ~{max(1, round(est / 60))} min',
                    'workout', 'fas fa-dumbbell', action={'start': True, 'log': True, 'skip': True}, done=done,
                    notify=True, status=status, minutes=round(est / 60))
        ev['ends_at'] = (_at(d, wt) + timedelta(seconds=est)).isoformat()
        out.append(ev)
        snack_done = FitnessTick.objects.filter(user_id=user_id, date=d, key='snack').exists()
        out.append(_event('snack', d, _at(d, wt, -SNACK_BEFORE_MIN), 'Eat something light before your workout',
                          'snack', 'fas fa-apple-alt', action={'done': True}, done=snack_done or done))

    # Meals with a protein goal each
    protein = metrics.get('protein')
    if protein:
        goal = targets.get('protein_g') or (protein.target and float(protein.target)) or 0
        per = round(goal / 4) if goal else None
        today_g = mx.day_value(protein, d)
        for key, label in MEAL_LABELS.items():
            mt = _t(times['meals'].get(key))
            if not mt:
                continue
            text = f'{label} · aim for {per} g protein' if per else label
            out.append(_event(f'meal-{key}', d, _at(d, mt), text, 'meal', 'fas fa-utensils',
                              action={'protein': [10, 20, 30]}, metric=protein.id,
                              progress=f'{_fmt(today_g)} / {_fmt(goal)} g today' if goal else None))
            out[-1]['completable'] = False      # meals carry a quick log, never an undone item

    # Water every 2 h from wake to 2 h before bed
    water = metrics.get('water')
    if water:
        target = mx.effective_target(water, user_id, d)
        target = float(target) if target is not None else None
        if target and session_day:
            target += 500                                     # +0.5 L on workout days
        value = float(mx.day_value(water, d))
        slots, t = [], _at(d, wake)
        while t <= bed_dt - timedelta(hours=2):
            slots.append(t)
            t += timedelta(hours=WATER_EVERY_H)
        for i, ts in enumerate(slots):
            pace = target * (i + 1) / len(slots) if target else None
            done = bool(pace and value >= pace)
            out.append(_event(f'water-{i}', d, ts, 'Water', 'water', 'fas fa-tint',
                              action={'water': [250, 500]}, done=done, notify=True, metric=water.id,
                              progress=f'{_fmt(value / 1000)} / {_fmt(target / 1000)} L' if target else None))

    # Walk (every planned day, or the 20-minute walk on a disrupted day)
    if activity and kind:
        items = {i.key: i for i in expand(activity, d)}
        key = 'walk20' if 'walk20' in items else 'walk'
        if key in items:
            from board.models import HabitStep
            step = HabitStep.objects.filter(habit=activity, key=key).first()
            done = bool(step and HabitStepLog.objects.filter(step=step, date=d, done=True).exists())
            lunch = _t(times['meals'].get('lunch')) or time(13)
            steps_m = metrics.get('steps')
            prog = None
            if steps_m and key == 'walk':
                st = mx.effective_target(steps_m, user_id, d)
                prog = f'{_fmt(mx.day_value(steps_m, d))} / {_fmt(st)} steps' if st else None
            out.append(_event('walk', d, _at(d, lunch, 30), items[key].name, 'walk', 'fas fa-walking',
                              action={'done': True}, done=done, step=step.id if step else None,
                              metric=steps_m.id if steps_m and key == 'walk' else None, progress=prog))
        elif kind == DayKind.REST:
            # Rest day: a walk is welcome but optional, so nothing to tick
            lunch = _t(times['meals'].get('lunch')) or time(13)
            steps_m = metrics.get('steps')
            prog = None
            if steps_m:
                st = mx.effective_target(steps_m, user_id, d)
                prog = f'{_fmt(mx.day_value(steps_m, d))} / {_fmt(st)} steps' if st else None
            out.append(_event('walk', d, _at(d, lunch, 30), 'Easy walk (optional on a rest day)', 'walk',
                              'fas fa-walking', progress=prog))

    # Weigh-in day, right after waking
    weight = metrics.get('weight')
    if weight and d.weekday() == int(times.get('weigh_in_day', 0)):
        logged = MetricEntry.objects.filter(metric=weight, date=d).exists()
        last_w = MetricEntry.objects.filter(metric=weight).order_by('-date', '-at').first()
        waist = metrics.get('waist')
        last_c = MetricEntry.objects.filter(metric=waist).order_by('-date', '-at').first() if waist else None
        bits = [f'last {_fmt(last_w.value)} kg' if last_w else None, f'waist {_fmt(last_c.value)} cm' if last_c else None]
        text = 'Weigh-in' + (f' · {", ".join(b for b in bits if b)}' if any(bits) else '')
        out.append(_event('weighin', d, _at(d, wake, 10), text, 'weighin', 'fas fa-weight',
                          action={'log': True}, done=logged, metric=weight.id, waist=waist.id if waist else None))

    # Bedtime: wake time minus 7.5 h (the Sleep tracker logs the night in the morning)
    bed = bed_dt if bed_dt.date() == d else _at(d, time(23, 59))
    out.append(_event('bedtime', d, bed, 'Bedtime · aim for 7–8 h of sleep', 'bedtime', 'fas fa-bed',
                      time=bed_dt.strftime('%H:%M')))
    return out

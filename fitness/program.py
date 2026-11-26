"""
Program expansion: what the Health and Activity habits ask of the user on a date.

Nothing is generated ahead of time. ``expand(habit, date)`` reads the active
Program (Activity) or the fitness profile (Health) and returns the day's
subtasks; ``refresh(habit, date)`` turns them into HabitStep rows (one row per
stable key, reused across days), applies the linked-tracker rules and settles
the habit. A program edit therefore takes effect on the next read.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from board.models import (
    FITNESS_HABIT_KINDS, DayMode, DayPlan, Habit, HabitKind, HabitStep, HabitStepLog, Metric,
)

WARMUP_BLOCKS = ('warmup', 'cooldown')
DISRUPTED_WALK_MIN = 20
WORKOUT_DAY_WATER_ML = 500


@dataclass
class Item:
    key: str
    name: str
    target: str = ''
    how_to: str = ''
    metric_key: str = ''          # fitness_key of a fitness tracker, or 'sleep'
    rule: dict = None
    optional: bool = False
    auto_done: bool = False       # rest day: done by definition
    extra: dict = field(default_factory=dict)


# ── Program lookups ────────────────────────────────────────

def active_program(habit):
    from fitness.models import Program, ProgramStatus
    return (Program.objects.filter(habit=habit, status=ProgramStatus.ACTIVE)
            .prefetch_related('phases__days').first())


def week_anchor(program):
    """Program weeks are calendar weeks (Mon-Sun); week 1 is the one containing start_date."""
    return program.start_date - timedelta(days=program.start_date.weekday())


def week_of(program, target_date):
    """1-based program week for a date, or None before the start."""
    if target_date < program.start_date:
        return None
    return (target_date - week_anchor(program)).days // 7 + 1


def program_day(program, target_date):
    """(phase, day_template) for a date, or (None, None) outside the program."""
    week = week_of(program, target_date)
    if week is None:
        return None, None
    for phase in program.phases.all():
        if phase.week_from <= week <= phase.week_to:
            day = next((d for d in phase.days.all() if d.weekday == target_date.weekday()), None)
            return phase, day
    return None, None


def program_end(program):
    last = max((p.week_to for p in program.phases.all()), default=0)
    return week_anchor(program) + timedelta(days=7 * last - 1) if last else None


def session_exercises(day):
    """[(exercise_id, sets, item)] for the main (non warm-up / cool-down) items, in order, merged by id."""
    out, index = [], {}
    for block in day.blocks or []:
        if block.get('block') in WARMUP_BLOCKS:
            continue
        rounds = int(block.get('rounds', 1) or 1)
        for item in block.get('items', []):
            ex_id = item.get('exercise')
            if not ex_id:
                continue
            if ex_id in index:
                out[index[ex_id]][1] += rounds
            else:
                index[ex_id] = len(out)
                out.append([ex_id, rounds, item])
    return [tuple(x) for x in out]


def is_session_day(user_id, target_date):
    """A planned workout that is going ahead (not swapped for a walk on a disrupted day)."""
    from fitness.models import DayKind
    habit = Habit.objects.filter(user_id=user_id, kind=HabitKind.ACTIVITY).first()
    program = active_program(habit) if habit else None
    if not program:
        return False
    _, day = program_day(program, target_date)
    return bool(day and day.kind == DayKind.SESSION and not is_disrupted(user_id, target_date))


def is_disrupted(user_id, target_date):
    return DayPlan.objects.filter(user_id=user_id, date=target_date, mode=DayMode.DISRUPTED).exists()


# ── Expansion ──────────────────────────────────────────────

def fitness_metric(user_id, key):
    if key == 'sleep':
        from board.metrics import ensure_sleep_metric
        return ensure_sleep_metric(user_id)
    return Metric.objects.filter(user_id=user_id, domain='fitness', fitness_key=key).first()


def _num(x):
    x = float(x)
    return int(x) if x == int(x) else x


def walk_item(user_id):
    steps = fitness_metric(user_id, 'steps')
    goal = _num(steps.target) if steps and steps.target is not None else 7000
    return Item('walk', f'Walk {goal:,} steps', metric_key='steps',
                rule={'cmp': 'gte', 'value': 'target'})


def expand_activity(habit, target_date):
    from fitness.models import DayKind, Exercise
    program = active_program(habit)
    if not program:
        return []
    phase, day = program_day(program, target_date)
    if day is None:
        return []
    if day.kind == DayKind.REST:
        return [Item('rest', 'Rest day', how_to='Recovery is part of the plan.', auto_done=True)]
    if day.kind == DayKind.WALK:
        return [walk_item(habit.user_id)]
    # Session day
    if is_disrupted(habit.user_id, target_date):
        return [Item('walk20', f'Walk {DISRUPTED_WALK_MIN} min',
                     how_to='Disrupted day: a short walk keeps the habit going.')]
    exs = session_exercises(day)
    library = Exercise.objects.in_bulk([e for e, _, _ in exs])
    overrides = program.overrides or {}
    items = [walk_item(habit.user_id)]
    for ex_id, sets, spec in exs:
        ex_id = overrides.get(ex_id, ex_id)
        if ex_id is None:          # dropped ("something hurts" with no safe regression)
            continue
        ex = library.get(ex_id) or Exercise.objects.filter(id=ex_id).first()
        name = ex.name if ex else ex_id.replace('_', ' ').capitalize()
        target = ex.dose_label(sets, spec.get('reps'), spec.get('seconds')) if ex else f'{sets} sets'
        how_to = ' '.join(ex.steps) if ex else ''
        items.append(Item(f'ex:{ex_id}', name, target=target, how_to=how_to,
                          extra={'exercise': ex_id, 'sets': sets, 'reps': spec.get('reps'),
                                 'seconds': spec.get('seconds')}))
    items.append(Item('finish', "Finish today's workout",
                      how_to='Ticked when you finish the workout in the player or log it.'))
    return items


def expand_health(habit, target_date):
    from fitness.models import FitnessProfile
    profile = FitnessProfile.objects.filter(user_id=habit.user_id).first()
    targets = (profile.targets if profile else {}) or {}
    weigh_day = int(((profile.times if profile else {}) or {}).get('weigh_in_day', 0))
    items = []
    water = targets.get('water_ml')
    plus = WORKOUT_DAY_WATER_ML if is_session_day(habit.user_id, target_date) else 0
    rule = {'cmp': 'gte', 'value': 'target', **({'plus': plus} if plus else {})}
    items.append(Item('water', f'Drink {_num(round((water + plus) / 1000, 1))} L water' if water else 'Drink water',
                      metric_key='water', rule=rule))
    protein = targets.get('protein_g')
    items.append(Item('protein', f'Hit {protein} g protein' if protein else 'Hit protein',
                      metric_key='protein', rule={'cmp': 'gte', 'value': 'target'}))
    if profile and profile.track_calories:
        items.append(Item('kcal', 'Stay within calories', metric_key='kcal',
                          rule={'cmp': 'within_pct', 'value': 'target', 'pct': 10}))
    items.append(Item('sleep', 'Sleep 7–8 h', metric_key='sleep', rule={'cmp': 'gte', 'value': 7}))
    if target_date.weekday() == weigh_day:
        items.append(Item('weighin', 'Weekly weigh-in', how_to='Weigh in after waking, before food.',
                          metric_key='weight', rule={'cmp': 'logged', 'window': 'week'}))
    return items


def expand(habit, target_date):
    if habit.kind == HabitKind.ACTIVITY:
        return expand_activity(habit, target_date)
    if habit.kind == HabitKind.HEALTH:
        return expand_health(habit, target_date)
    return []


# ── Materialise, evaluate, settle ──────────────────────────

def materialize(habit, items):
    """HabitStep rows for the items (created or updated by key), in item order."""
    existing = {s.key: s for s in habit.steps.exclude(key='')}
    metrics = {}
    out = []
    for order, it in enumerate(items):
        if it.metric_key and it.metric_key not in metrics:
            metrics[it.metric_key] = fitness_metric(habit.user_id, it.metric_key)
        metric = metrics.get(it.metric_key)
        values = dict(name=it.name[:120], target=it.target[:60], how_to=it.how_to, order=order,
                      metric=metric, rule=it.rule, optional=it.optional)
        step = existing.get(it.key)
        if step is None:
            step = HabitStep.objects.create(habit=habit, key=it.key, **values)
        elif any(getattr(step, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(step, k, v)
            step.save()
        out.append((step, it))
    return out


def steps_for(habit, target_date):
    """Today's HabitStep rows for a fitness habit (materialised), else None."""
    if habit.kind not in FITNESS_HABIT_KINDS:
        return None
    return [s for s, _ in materialize(habit, expand(habit, target_date))]


def refresh(habit, target_date, settle=True):
    """Expand, materialise, apply rules and (optionally) settle. Returns [(step, item)]."""
    from fitness.links import apply_rules
    pairs = materialize(habit, expand(habit, target_date))
    apply_rules(habit, target_date, pairs)
    if settle:
        from board.day_views import settle_habit
        settle_habit(habit, target_date, steps=[s for s, _ in pairs])
    return pairs


def fitness_habits(user_id):
    from board.models import HabitStatus
    return Habit.objects.filter(user_id=user_id, kind__in=FITNESS_HABIT_KINDS,
                                status=HabitStatus.ACTIVE.value)


def refresh_user(user_id, target_date):
    for habit in fitness_habits(user_id):
        refresh(habit, target_date)


def preview(habit, start, days=7):
    """[(date, [Item])] for the next ``days`` days without writing anything."""
    return [(start + timedelta(days=i), expand(habit, start + timedelta(days=i))) for i in range(days)]


def done_keys(habit, target_date):
    return set(HabitStepLog.objects.filter(step__habit=habit, date=target_date, done=True)
               .values_list('step__key', flat=True))

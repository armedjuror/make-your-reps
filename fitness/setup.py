"""
Create (or update) a user's fitness objects: the Health and Activity habits,
the fitness trackers and the Program. Used by onboarding and by seed_my_plan.
Idempotent: running it again updates targets and never duplicates.
"""
from decimal import Decimal

from django.db import transaction

from board.models import Habit, HabitKind, HabitStatus, Metric, MetricKind, UserDetail

# fitness_key -> (name, unit, kind, target key in profile.targets, quick buttons, default private)
TRACKERS = {
    'water':   ('Water', 'ml', MetricKind.ADDITIVE, 'water_ml', [250, 500], False),
    'protein': ('Protein', 'g', MetricKind.ADDITIVE, 'protein_g', [10, 20, 30], False),
    'kcal':    ('Calories', 'kcal', MetricKind.ADDITIVE, 'kcal', [100, 250, 500], False),
    'steps':   ('Steps', 'steps', MetricKind.SINGLE, 'steps', [], False),
    'weight':  ('Body weight', 'kg', MetricKind.SINGLE, None, [], True),
    'waist':   ('Waist', 'cm', MetricKind.SINGLE, None, [], True),
}
HABITS = {
    HabitKind.HEALTH: ('Health', 'someone who looks after their body'),
    HabitKind.ACTIVITY: ('Activity', 'someone who trains'),
}


def _private_by_default(user_id):
    """Body data defaults to private, but only when there is a PIN to unlock it with."""
    return bool(UserDetail.objects.filter(user_id=user_id).exclude(private_pin_hash='').exists())


def ensure_trackers(user_id, targets, track_calories=False):
    private_ok = _private_by_default(user_id)
    out = {}
    for key, (name, unit, kind, tkey, quick, private) in TRACKERS.items():
        metric = Metric.objects.filter(user_id=user_id, domain='fitness', fitness_key=key).first()
        if key == 'kcal' and not track_calories:
            out[key] = metric      # kept if it existed (history), never created unasked
            continue
        target = targets.get(tkey) if tkey else None
        target = Decimal(str(target)) if target is not None else None
        if metric is None:
            metric = Metric.objects.create(
                user_id=user_id, name=name, unit=unit, kind=kind, direction='at_least',
                target=target, quick_steps=[Decimal(str(q)) for q in quick],
                domain='fitness', fitness_key=key, is_private=private and private_ok,
            )
        elif metric.target != target:
            metric.target = target
            metric.save(update_fields=['target'])
        out[key] = metric
    return out


def ensure_habit(user_id, kind):
    habit = Habit.objects.filter(user_id=user_id, kind=kind).exclude(status=HabitStatus.DELETED.value).first()
    if habit is None:
        name, identity = HABITS[kind]
        habit = Habit.objects.create(
            user_id=user_id, habit=name, identity=identity, kind=kind, frequency=[],
            complete_when='all', detail='Part of your fitness plan. Managed in the Fitness tab.',
            is_private=(kind == HabitKind.HEALTH and _private_by_default(user_id)),
        )
    return habit


@transaction.atomic
def ensure_fitness(user_id, targets, track_calories=False):
    """Trackers + both habits. Returns (health_habit, activity_habit, trackers)."""
    trackers = ensure_trackers(user_id, targets, track_calories)
    return ensure_habit(user_id, HabitKind.HEALTH), ensure_habit(user_id, HabitKind.ACTIVITY), trackers


@transaction.atomic
def install_program(habit, template, start_date, name=None, phases=None):
    """Copy a concrete template (exercise ids, no open slots) into a Program for the habit.
    ``phases`` overrides template.phases (the builder's resolved output)."""
    from fitness.models import DayTemplate, Phase, Program, ProgramStatus
    Program.objects.filter(habit=habit).delete()
    program = Program.objects.create(
        user_id=habit.user_id, habit=habit, template=template, name=name or template.name,
        start_date=start_date, status=ProgramStatus.ACTIVE,
    )
    for order, ph in enumerate(phases if phases is not None else template.phases):
        phase = Phase.objects.create(program=program, order=order, name=ph['name'],
                                     week_from=ph['weeks'][0], week_to=ph['weeks'][1])
        for weekday, day in sorted(ph['days'].items(), key=lambda kv: int(kv[0])):
            for block in day.get('blocks', []):
                for item in block.get('items', []):
                    if 'slot' in item and 'exercise' not in item:
                        raise ValueError(f'{template.slug}: unfilled slot {item["slot"]}; run the builder first')
            DayTemplate.objects.create(phase=phase, weekday=int(weekday), kind=day['kind'],
                                       name=day.get('name', ''), blocks=day.get('blocks', []))
    return program

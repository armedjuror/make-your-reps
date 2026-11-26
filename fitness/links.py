"""
Linked trackers: a fitness subtask with a metric and a rule ticks itself from
that metric. Every MetricEntry write (any source) re-evaluates the linked
subtasks for the day; a manual tick stays unless the rule itself had set it.

Rules: {"cmp": "gte", "value": "target" | n}
       {"cmp": "within_pct", "value": "target", "pct": 10}
       {"cmp": "logged", "window": "week"}     # any entry Mon-Sun of that week
"""
from datetime import timedelta
from decimal import Decimal

from board.models import FITNESS_HABIT_KINDS, HabitStep, HabitStepLog, MetricEntry


def _threshold(step, target_date):
    from board.metrics import effective_target
    value = (step.rule or {}).get('value', 'target')
    if value == 'target':
        return effective_target(step.metric, step.metric.user_id, target_date)
    return Decimal(str(value))


def rule_met(step, target_date):
    """True / False when the step has a metric rule, None otherwise."""
    if not step.metric_id or not step.rule:
        return None
    from board.metrics import day_value
    rule = step.rule
    cmp = rule.get('cmp', 'gte')
    if rule.get('window') == 'week' or cmp == 'logged':
        start = target_date - timedelta(days=target_date.weekday())
        qs = MetricEntry.objects.filter(metric_id=step.metric_id, date__gte=start,
                                        date__lte=start + timedelta(days=6))
        if cmp == 'logged':
            return qs.exists()
    value = day_value(step.metric, target_date)
    threshold = _threshold(step, target_date)
    if threshold is None:
        return False
    if cmp == 'gte':
        return value >= threshold
    if cmp == 'within_pct':
        pct = Decimal(str(rule.get('pct', 10))) / 100
        return value > 0 and abs(value - threshold) <= threshold * pct
    return False


def apply_rules(habit, target_date, pairs):
    """Tick or untick linked / auto steps for the date. ``pairs`` = [(step, item)]."""
    for step, item in pairs:
        met = True if getattr(item, 'auto_done', False) else rule_met(step, target_date)
        if met is None:
            continue
        log = HabitStepLog.objects.filter(step=step, date=target_date).first()
        if met:
            if not (log and log.done):
                log = log or HabitStepLog(step=step, date=target_date)
                log.done, log.source = True, 'auto'
                log.save()
        elif log and log.done and log.source == 'auto':
            log.done = False
            log.save(update_fields=['done'])


def on_metric_change(metric, target_date):
    """Called after any MetricEntry write or undo for ``metric``."""
    from board.models import Habit
    from fitness.models import FitnessProfile
    from fitness.program import fitness_habits, refresh
    if metric.domain == 'fitness' or metric.system_key == 'sleep':
        # Steps are created lazily, so refresh even if today's checklist was never opened
        habits = list(fitness_habits(metric.user_id))
    else:
        habits = list(Habit.objects.filter(
            id__in=HabitStep.objects.filter(metric=metric, habit__kind__in=FITNESS_HABIT_KINDS)
            .exclude(rule=None).values('habit_id')))
    for habit in habits:
        refresh(habit, target_date)
    # Week-window rule (weigh-in): a log later in the week also completes that week's weigh-in day
    if metric.fitness_key == 'weight':
        profile = FitnessProfile.objects.filter(user_id=metric.user_id).first()
        weigh_day = int(((profile.times if profile else {}) or {}).get('weigh_in_day', 0))
        d = target_date - timedelta(days=target_date.weekday() - weigh_day)
        if d < target_date:
            for habit in habits:
                if habit.kind == 'health' and d >= habit.created_at.date():
                    refresh(habit, d)

"""
Server-side feature events for PostHog.

One event per meaningful user action, sent after the transaction commits. Properties
never include user-written text (habit names, todo text, journal entries): only kinds,
statuses and flags, so the analytics store holds nothing a user would call private.
"""
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from board.models import (
    AccountabilityPartner, BlockLog, DayPlan, Feedback, Friend, FriendRequest,
    GoogleCalendarToken, Habit, HabitLog, HabitStep, HabitStepLog, Journal, JournalEntry,
    Metric, MetricEntry, ReadingListItem, RoutineEntry, Task, TaskGroup, UserAchievement,
)
from main import analytics


def _send(user_id, event, props=None):
    if not analytics.enabled() or not user_id:
        return
    client = analytics.current_client.get()

    def go():
        token = analytics.current_client.set(client)
        try:
            analytics.capture(user_id, event, props)
        finally:
            analytics.current_client.reset(token)

    transaction.on_commit(go)


# model -> (event, user_id getter, properties getter); fired on create only
CREATE_EVENTS = {
    Habit: ('habit_created', lambda o: o.user_id,
            lambda o: {'is_private': o.is_private, 'days_per_week': len(o.frequency or []) or 7,
                       'has_reminder': bool(o.notify_at), 'has_metric': bool(o.metric_id)}),
    HabitStep: ('habit_step_created', lambda o: o.habit.user_id, lambda o: {}),
    HabitStepLog: ('habit_step_logged', lambda o: o.step.habit.user_id, lambda o: {'done': o.done}),
    Task: ('todo_created', lambda o: o.user_id,
           lambda o: {'has_deadline': bool(o.deadline), 'has_group': bool(o.group_id)}),
    TaskGroup: ('todo_group_created', lambda o: o.user_id, lambda o: {}),
    RoutineEntry: ('routine_block_created', lambda o: o.user_id,
                   lambda o: {'routine_type': o.routine_type, 'tier': o.tier}),
    BlockLog: ('routine_block_logged', lambda o: o.user_id, lambda o: {'status': o.status, 'tier': o.tier}),
    Metric: ('tracker_created', lambda o: o.user_id,
             lambda o: {'kind': o.kind, 'is_private': o.is_private, 'system': o.is_system,
                        'has_target': o.target is not None, 'detail_fields': len(o.fields or [])}),
    MetricEntry: ('tracker_logged', lambda o: o.metric.user_id,
                  lambda o: {'kind': o.metric.kind, 'system_key': o.metric.system_key or None,
                             'has_details': bool(o.data)}),
    Journal: ('journal_created', lambda o: o.user_id,
              lambda o: {'is_private': o.is_private, 'linked_tracker': bool(o.metric_id)}),
    JournalEntry: ('journal_entry_written', lambda o: o.journal.user_id,
                   lambda o: {'default_journal': o.journal.is_default, 'words_bucket': _bucket(len(o.text.split()))}),
    ReadingListItem: ('bookmark_added', lambda o: o.user_id, lambda o: {'featured': o.is_featured}),
    AccountabilityPartner: ('accountability_partner_invited', lambda o: o.habit.user_id, lambda o: {}),
    FriendRequest: ('friend_request_sent', lambda o: o.from_user_id, lambda o: {'by_email': not o.to_user_id}),
    Friend: ('friend_added', lambda o: getattr(o, 'user_id', None), lambda o: {}),
    GoogleCalendarToken: ('calendar_connected', lambda o: o.user_id, lambda o: {}),
    UserAchievement: ('achievement_unlocked', lambda o: o.user_id, lambda o: {'achievement': o.achievement.key}),
    Feedback: ('feedback_sent', lambda o: o.user_id, lambda o: {'type': o.type}),
}

# Seed rows created at signup are bulk_create()d, so they never reach these signals.
SKIP = {
    Habit: lambda o: o.is_system,
}


def _bucket(n):
    for edge in (10, 50, 150, 400):
        if n <= edge:
            return f'<={edge}'
    return '>400'


def _on_create(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    event, get_user, get_props = CREATE_EVENTS[sender]
    skip = SKIP.get(sender)
    if skip and skip(instance):
        return
    try:
        user_id, props = get_user(instance), get_props(instance)
    except Exception:
        return
    _send(user_id, event, props)


for _model in CREATE_EVENTS:
    post_save.connect(_on_create, sender=_model, dispatch_uid=f'analytics_create_{_model.__name__}')


# ── State changes worth their own event ──

@receiver(pre_save, sender=Task, dispatch_uid='analytics_task_pre')
def _task_pre(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk or not analytics.enabled():
        return
    instance._was_done = Task.objects.filter(pk=instance.pk).values_list('is_done', flat=True).first()


@receiver(post_save, sender=Task, dispatch_uid='analytics_task_post')
def _task_post(sender, instance, created, raw=False, **kwargs):
    if raw or created:
        return
    was = getattr(instance, '_was_done', None)
    if was is False and instance.is_done:
        _send(instance.user_id, 'todo_completed', {'had_deadline': bool(instance.deadline)})


@receiver(pre_save, sender=HabitLog, dispatch_uid='analytics_habitlog_pre')
def _habitlog_pre(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk or not analytics.enabled():
        return
    instance._was_done = HabitLog.objects.filter(pk=instance.pk).values_list('is_done', flat=True).first()


@receiver(post_save, sender=HabitLog, dispatch_uid='analytics_habitlog_post')
def _habitlog_post(sender, instance, created, raw=False, **kwargs):
    # Rows are often get_or_create()d as pending and ticked after, so fire on the tick
    if raw or not instance.is_done:
        return
    if created or getattr(instance, '_was_done', None) is False:
        if instance.habit.is_system:
            return
        _send(instance.habit.user_id, 'habit_logged', {'is_private': instance.habit.is_private})


@receiver(pre_save, sender=DayPlan, dispatch_uid='analytics_dayplan_pre')
def _dayplan_pre(sender, instance, raw=False, **kwargs):
    if raw or not instance.pk or not analytics.enabled():
        return
    instance._was_mode = DayPlan.objects.filter(pk=instance.pk).values_list('mode', flat=True).first()


@receiver(post_save, sender=DayPlan, dispatch_uid='analytics_dayplan_post')
def _dayplan_post(sender, instance, created, raw=False, **kwargs):
    # Plans are made 'normal' on first view; the event is the user switching the day type
    if raw:
        return
    was = 'normal' if created else getattr(instance, '_was_mode', None)
    if was is not None and instance.mode != was:
        _send(instance.user_id, 'day_mode_set', {'mode': instance.mode, 'from': was, 'source': instance.source})


@receiver(post_save, sender=User, dispatch_uid='analytics_user_signed_up')
def _user_created(sender, instance, created, raw=False, **kwargs):
    if raw or not analytics.enabled():
        return
    client = analytics.current_client.get()

    def go():
        analytics.identify(instance)
        if created:
            token = analytics.current_client.set(client)
            try:
                analytics.capture(instance.pk, 'user_signed_up', {})
            finally:
                analytics.current_client.reset(token)

    transaction.on_commit(go)

from datetime import datetime, time, timedelta

from celery import shared_task
from django.contrib.auth.models import User
from django.utils import timezone

from board.models import (
    Habit, HabitStatus, Task, RoutineEntry, TimelineEvent,
    TimelineEventType, UserDetail
)


@shared_task
def generate_daily_timeline(user_id=None):
    """
    Generate timeline events for today for all users (or a specific user).
    Runs daily at 00:01 via Celery Beat.
    """
    if user_id:
        users = User.objects.filter(id=user_id)
    else:
        users = User.objects.filter(is_active=True)

    today = timezone.now().date()
    weekday = today.weekday()  # 0=Monday, 6=Sunday

    for user in users:
        _generate_habit_events(user, today, weekday)
        _generate_todo_events(user, today)
        _generate_routine_events(user, today, weekday)
        _generate_system_reminders(user, today)


def _generate_habit_events(user, today, weekday):
    """Create timeline events for habits scheduled today with notify_at set."""
    habits = Habit.objects.filter(
        user=user,
        status=HabitStatus.ACTIVE.value,
    )
    for habit in habits:
        # Check if today is a scheduled day
        if habit.frequency and weekday not in habit.frequency:
            continue

        # Only create event if notify_at is set
        if not habit.notify_at:
            continue

        timestamp = timezone.make_aware(
            datetime.combine(today, habit.notify_at)
        )

        # Avoid duplicates
        exists = TimelineEvent.objects.filter(
            user=user,
            event_type=TimelineEventType.HABIT,
            reference__model='Habit',
            reference__id=habit.id,
            timestamp__date=today
        ).exists()

        if not exists:
            TimelineEvent.objects.create(
                user=user,
                timestamp=timestamp,
                event_type=TimelineEventType.HABIT,
                event=f"Time to: {habit.habit} ({habit.detail})",
                reference={'model': 'Habit', 'id': habit.id},
                action={'mark_done': [True, False]},
            )


def _generate_todo_events(user, today):
    """Create timeline events for todos due today or overdue."""
    # Due today
    for todo in Task.objects.filter(user=user, is_deleted=False, is_done=False, deadline__date=today):
        exists = TimelineEvent.objects.filter(
            user=user,
            event_type=TimelineEventType.TODO,
            reference__model='Task',
            reference__id=todo.id,
            timestamp__date=today
        ).exists()
        if not exists:
            TimelineEvent.objects.create(
                user=user,
                timestamp=todo.deadline,
                event_type=TimelineEventType.TODO,
                event=f"Due today: {todo.task_name}",
                reference={'model': 'Task', 'id': todo.id},
                action={'mark_done': [True, False]},
            )

    # Overdue (deadline before today, still pending)
    for todo in Task.objects.filter(user=user, is_deleted=False, is_done=False, deadline__date__lt=today):
        days = (today - todo.deadline.date()).days
        label = f"{days} day" if days == 1 else f"{days} days"
        exists = TimelineEvent.objects.filter(
            user=user,
            event_type=TimelineEventType.TODO,
            reference__model='Task',
            reference__id=todo.id,
            timestamp__date=today
        ).exists()
        if not exists:
            TimelineEvent.objects.create(
                user=user,
                timestamp=timezone.make_aware(datetime.combine(today, time(9, 0))),
                event_type=TimelineEventType.TODO,
                event=f"Overdue by {label}: {todo.task_name}",
                reference={'model': 'Task', 'id': todo.id},
                action={'mark_done': [True, False]},
            )


def _generate_routine_events(user, today, weekday):
    """Create timeline events from routine entries."""
    # Determine routine type: weekday (Mon-Fri) = workday, weekend = holiday
    is_weekend = weekday in [5, 6]
    routine_type = 'holiday' if is_weekend else 'workday'

    entries = RoutineEntry.objects.filter(
        user=user,
        routine_type=routine_type,
    )

    for entry in entries:
        timestamp = timezone.make_aware(
            datetime.combine(today, entry.time)
        )

        exists = TimelineEvent.objects.filter(
            user=user,
            event_type=TimelineEventType.ROUTINE,
            reference__model='RoutineEntry',
            reference__id=entry.id,
            timestamp__date=today
        ).exists()

        if not exists:
            TimelineEvent.objects.create(
                user=user,
                timestamp=timestamp,
                event_type=TimelineEventType.ROUTINE,
                event=entry.title,
                reference={'model': 'RoutineEntry', 'id': entry.id},
                action=None,  # Routine events have no action
            )


def _generate_system_reminders(user, today):
    """
    Create system reminders:
    - Sleep tracker reminder at 7:00 AM (log last night's sleep)
    - Journal reminder at (sleep_time - 30min) or 9:00 PM if no sleep_time
    - Sleep notification at sleep_time
    """
    user_detail = UserDetail.objects.filter(user=user).first()

    # ── Sleep tracker reminder at 7:00 AM ──
    sleep_track_time = timezone.make_aware(
        datetime.combine(today, time(7, 0))
    )
    if not TimelineEvent.objects.filter(
        user=user,
        event_type=TimelineEventType.SLEEP_TRACKER,
        timestamp__date=today
    ).exists():
        TimelineEvent.objects.create(
            user=user,
            timestamp=sleep_track_time,
            event_type=TimelineEventType.SLEEP_TRACKER,
            event="Good morning! How many hours did you sleep last night?",
            reference=None,
            action={'log_sleep': [True, False]},
        )

    # ── Journal reminder ──
    if user_detail and user_detail.sleep_time:
        # 30 minutes before sleep time
        sleep_dt = datetime.combine(today, user_detail.sleep_time)
        journal_dt = sleep_dt - timedelta(minutes=30)
        journal_time = journal_dt.time()
    else:
        journal_time = time(21, 0)  # 9:00 PM default

    journal_timestamp = timezone.make_aware(
        datetime.combine(today, journal_time)
    )
    if not TimelineEvent.objects.filter(
        user=user,
        event_type=TimelineEventType.JOURNAL,
        timestamp__date=today
    ).exists():
        TimelineEvent.objects.create(
            user=user,
            timestamp=journal_timestamp,
            event_type=TimelineEventType.JOURNAL,
            event="Time to reflect! Write a few lines in your journal.",
            reference=None,
            action={'open_journal': [True, False]},
        )

    # ── Sleep notification at sleep_time ──
    if user_detail and user_detail.sleep_time:
        sleep_timestamp = timezone.make_aware(
            datetime.combine(today, user_detail.sleep_time)
        )
        if not TimelineEvent.objects.filter(
            user=user,
            event_type=TimelineEventType.TEXT,
            timestamp=sleep_timestamp,
            event__contains='time to sleep'
        ).exists():
            TimelineEvent.objects.create(
                user=user,
                timestamp=sleep_timestamp,
                event_type=TimelineEventType.TEXT,
                event="It's time to sleep. Good night! 🌙",
                reference=None,
                action=None,
            )


@shared_task
def generate_timeline_for_new_item(item_type, item_id):
    """
    Called when a habit/todo/routine is created mid-day to inject
    into today's timeline if applicable.
    """
    today = timezone.now().date()
    weekday = today.weekday()
    now = timezone.now()

    if item_type == 'habit':
        try:
            habit = Habit.objects.get(pk=item_id, status=HabitStatus.ACTIVE.value)
        except Habit.DoesNotExist:
            return

        if habit.frequency and weekday not in habit.frequency:
            return
        if not habit.notify_at:
            return

        timestamp = timezone.make_aware(datetime.combine(today, habit.notify_at))
        TimelineEvent.objects.get_or_create(
            user=habit.user,
            event_type=TimelineEventType.HABIT,
            reference={'model': 'Habit', 'id': habit.id},
            timestamp__date=today,
            defaults={
                'timestamp': timestamp,
                'event': f"Time to: {habit.habit} ({habit.detail})",
                'action': {'mark_done': [True, False]},
            }
        )

    elif item_type == 'todo':
        try:
            todo = Task.objects.get(pk=item_id, is_deleted=False)
        except Task.DoesNotExist:
            return

        if not todo.deadline or todo.is_done:
            return

        deadline_date = todo.deadline.date()
        if deadline_date == today:
            TimelineEvent.objects.get_or_create(
                user=todo.user,
                event_type=TimelineEventType.TODO,
                reference={'model': 'Task', 'id': todo.id},
                timestamp__date=today,
                defaults={
                    'timestamp': todo.deadline,
                    'event': f"Due today: {todo.task_name}",
                    'action': {'mark_done': [True, False]},
                }
            )
        elif deadline_date < today:
            days = (today - deadline_date).days
            label = f"{days} day" if days == 1 else f"{days} days"
            TimelineEvent.objects.get_or_create(
                user=todo.user,
                event_type=TimelineEventType.TODO,
                reference={'model': 'Task', 'id': todo.id},
                timestamp__date=today,
                defaults={
                    'timestamp': timezone.make_aware(datetime.combine(today, time(9, 0))),
                    'event': f"Overdue by {label}: {todo.task_name}",
                    'action': {'mark_done': [True, False]},
                }
            )

    elif item_type == 'routine':
        try:
            entry = RoutineEntry.objects.get(pk=item_id)
        except RoutineEntry.DoesNotExist:
            return

        is_weekend = weekday in [5, 6]
        expected_type = 'holiday' if is_weekend else 'workday'
        if entry.routine_type != expected_type:
            return

        timestamp = timezone.make_aware(datetime.combine(today, entry.time))
        TimelineEvent.objects.get_or_create(
            user=entry.user,
            event_type=TimelineEventType.ROUTINE,
            reference={'model': 'RoutineEntry', 'id': entry.id},
            timestamp__date=today,
            defaults={
                'timestamp': timestamp,
                'event': entry.title,
                'action': None,
            }
        )
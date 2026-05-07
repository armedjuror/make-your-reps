from datetime import datetime, time, timedelta

from celery import shared_task
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings

from board.models import (
    Habit, HabitLog, HabitStatus, Task, DailyData, RoutineEntry, TimelineEvent,
    TimelineEventType, UserDetail,
    AccountabilityPartner, AccountabilityPartnerStatus,
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

    today = timezone.localdate()
    weekday = today.weekday()  # 0=Monday, 6=Sunday

    for user in users:
        _generate_habit_events(user, today, weekday)
        _generate_todo_events(user, today)
        _generate_system_reminders(user, today)
        _generate_accountability_partner_events(user, today)
        _sync_calendar_events(user, today)


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


def _sync_calendar_events(user, today):
    """Pull Google Calendar events for today and upsert into TimelineEvent."""
    try:
        from board.calendar_views import sync_calendar_events_for_user_date
        sync_calendar_events_for_user_date(user, today)
    except Exception:
        pass


def _generate_system_reminders(user, today):
    """
    Create system reminders:
    - Sleep tracker reminder at 7:00 AM (log last night's sleep)
    - Journal reminder at (sleep_time - 30min) or 9:00 PM if no sleep_time
    - Sleep notification at sleep_time
    """
    user_detail = UserDetail.objects.filter(user=user).first()





def _generate_accountability_partner_events(user, today):
    """Create daily monitoring entries for each active accountability partnership where user is the partner."""
    partnerships = AccountabilityPartner.objects.filter(
        partner=user,
        status=AccountabilityPartnerStatus.ACTIVE,
    ).select_related('habit__user')

    for ap in partnerships:
        owner_name = ap.habit.user.get_full_name() or ap.habit.user.username
        timestamp = timezone.make_aware(datetime.combine(today, time(8, 0)))
        exists = TimelineEvent.objects.filter(
            user=user,
            event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
            reference__model='AccountabilityPartner',
            reference__id=ap.id,
            reference__type='monitor',
            timestamp__date=today,
        ).exists()
        if not exists:
            TimelineEvent.objects.create(
                user=user,
                timestamp=timestamp,
                event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
                event=f"Check on {owner_name}'s habit: {ap.habit.habit}",
                reference={'model': 'AccountabilityPartner', 'id': ap.id, 'type': 'monitor'},
                action={'check': [True, False], 'remind': [True, False]},
            )


@shared_task
def send_timeline_push_notifications():
    """
    Runs every 5 minutes. Finds timeline events due in the next 5 minutes
    that haven't been push-notified yet and sends a push to each user's
    subscribed devices.
    """
    from board.push import send_push_to_user

    now = timezone.now()
    window_end = now + timedelta(minutes=5)

    events = (
        TimelineEvent.objects
        .filter(timestamp__gte=now, timestamp__lt=window_end, push_notified=False)
        .select_related('user')
    )

    type_titles = {
        'habit': 'Habit Reminder',
        'todo': 'Task Due',
        'routine': 'Routine',
        'sleep_tracker': 'Sleep Tracker',
        'journal': 'Journal Time',
        'text': 'Reminder',
        'meeting': 'Meeting',
        'friend_request': 'Friend Request',
        'accountability_invite': 'Accountability Invite',
        'accountability_habit': 'Accountability Check',
    }

    ids_to_mark = []
    for event in events:
        title = type_titles.get(event.event_type, 'Steps')
        try:
            send_push_to_user(event.user, title, event.event)
        except Exception:
            pass
        ids_to_mark.append(event.pk)

    if ids_to_mark:
        TimelineEvent.objects.filter(pk__in=ids_to_mark).update(push_notified=True)

    return f'Push notifications sent for {len(ids_to_mark)} events.'


@shared_task
def cleanup_old_timeline_events():
    """
    Delete timeline events older than 30 days.
    Runs daily via Celery Beat.
    """
    cutoff = timezone.now() - timedelta(days=30)
    deleted, _ = TimelineEvent.objects.filter(timestamp__lt=cutoff).delete()
    return f"Deleted {deleted} timeline events older than 30 days."


@shared_task
def generate_timeline_for_new_item(item_type, item_id):
    """
    Called when a habit/todo/routine is created mid-day to inject
    into today's timeline if applicable.
    """
    today = timezone.localdate()
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

        exists = TimelineEvent.objects.filter(
            user=habit.user,
            event_type=TimelineEventType.HABIT,
            reference={'model': 'Habit', 'id': habit.id},
            timestamp__date=today,
        ).exists()
        if not exists:
            timestamp = timezone.make_aware(datetime.combine(today, habit.notify_at))
            TimelineEvent.objects.create(
                user=habit.user,
                timestamp=timestamp,
                event_type=TimelineEventType.HABIT,
                event=f"Time to: {habit.habit} ({habit.detail})",
                reference={'model': 'Habit', 'id': habit.id},
                action={'mark_done': [True, False]},
            )

    elif item_type == 'todo':
        try:
            todo = Task.objects.get(pk=item_id, is_deleted=False)
        except Task.DoesNotExist:
            return

        if not todo.deadline or todo.is_done:
            return

        deadline_date = todo.deadline.date()
        exists = TimelineEvent.objects.filter(
            user=todo.user,
            event_type=TimelineEventType.TODO,
            reference={'model': 'Task', 'id': todo.id},
            timestamp__date=today,
        ).exists()
        if not exists:
            if deadline_date == today:
                TimelineEvent.objects.create(
                    user=todo.user,
                    timestamp=todo.deadline,
                    event_type=TimelineEventType.TODO,
                    event=f"Due today: {todo.task_name}",
                    reference={'model': 'Task', 'id': todo.id},
                    action={'mark_done': [True, False]},
                )
            elif deadline_date < today:
                days = (today - deadline_date).days
                label = f"{days} day" if days == 1 else f"{days} days"
                TimelineEvent.objects.create(
                    user=todo.user,
                    timestamp=timezone.make_aware(datetime.combine(today, time(9, 0))),
                    event_type=TimelineEventType.TODO,
                    event=f"Overdue by {label}: {todo.task_name}",
                    reference={'model': 'Task', 'id': todo.id},
                    action={'mark_done': [True, False]},
                )

    # Routine events are no longer stored in the DB.
    # They are computed at the application layer in TimelineEventViewSet.list.


@shared_task
def send_reengagement_emails():
    """
    Daily task: send a re-engagement email to every active user who has not
    performed any meaningful action (habit log, journal, sleep entry, todo
    completion) in the last 7 days and has not opted out of marketing emails.
    """
    from main.models import EmailPreference  # avoid circular import
    from django.db.models import Max, Q

    cutoff = timezone.localdate() - timedelta(days=7)
    site_url = 'https://makeyourreps.com'
    login_url = f'{site_url}/login'
    year = timezone.now().year

    # Users active via a completed habit log
    habit_active_ids = set(
        HabitLog.objects
        .filter(is_done=True, date__gte=cutoff)
        .values_list('habit__user_id', flat=True)
        .distinct()
    )

    # Users active via a sleep or journal entry
    daily_active_ids = set(
        DailyData.objects
        .filter(date__gte=cutoff)
        .filter(Q(sleep_hours__isnull=False) | Q(journal__gt=''))
        .values_list('user_id', flat=True)
        .distinct()
    )

    # Users active via a completed todo
    task_active_ids = set(
        Task.objects
        .filter(is_done=True, updated_at__date__gte=cutoff)
        .values_list('user_id', flat=True)
        .distinct()
    )

    recently_active_ids = habit_active_ids | daily_active_ids | task_active_ids

    inactive_users = (
        User.objects
        .filter(is_active=True)
        .exclude(id__in=recently_active_ids)
        .exclude(email='')
    )

    # Fetch most recent activity date per inactive user across all three sources
    today = timezone.localdate()

    habit_last = dict(
        HabitLog.objects
        .filter(habit__user__in=inactive_users, is_done=True)
        .values('habit__user_id')
        .annotate(last=Max('date'))
        .values_list('habit__user_id', 'last')
    )

    daily_last = dict(
        DailyData.objects
        .filter(user__in=inactive_users)
        .filter(Q(sleep_hours__isnull=False) | Q(journal__gt=''))
        .values('user_id')
        .annotate(last=Max('date'))
        .values_list('user_id', 'last')
    )

    task_last = dict(
        Task.objects
        .filter(user__in=inactive_users, is_done=True)
        .values('user_id')
        .annotate(last=Max('updated_at'))
        .values_list('user_id', 'last')
    )

    reengagement_cutoff = today - timedelta(days=7)

    sent = 0
    for user in inactive_users:
        pref, _ = EmailPreference.objects.get_or_create(user=user)
        if not pref.marketing_emails:
            continue
        if pref.last_reengagement_sent and pref.last_reengagement_sent >= reengagement_cutoff:
            continue

        candidates = []
        if user.id in habit_last:
            candidates.append(habit_last[user.id])
        if user.id in daily_last:
            candidates.append(daily_last[user.id])
        if user.id in task_last:
            candidates.append(task_last[user.id].date())
        if candidates:
            days_away = (today - max(candidates)).days
        else:
            days_away = (today - user.date_joined.date()).days

        first_name = user.first_name or user.username
        unsubscribe_url = f'{site_url}/unsubscribe/{pref.token}/'
        html_body = render_to_string('emails/reengagement.html', {
            'first_name': first_name,
            'days_away': days_away,
            'login_url': login_url,
            'site_url': site_url,
            'unsubscribe_url': unsubscribe_url,
            'year': year,
        })
        send_mail(
            subject="Your habits are waiting — come back and make your reps",
            message=(
                f"Hey {first_name},\n\n"
                "It's been a while since you last checked in. Your habits and your board "
                "are still here, waiting for you.\n\n"
                f"Jump back in: {login_url}\n\n"
                "— The Make Your Reps team\n\n"
                f"Manage email preferences: {unsubscribe_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_body,
            fail_silently=True,
        )
        pref.last_reengagement_sent = today
        pref.save(update_fields=['last_reengagement_sent'])
        sent += 1

    return f"Re-engagement emails sent to {sent} inactive users."
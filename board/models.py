from datetime import date, timedelta

from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.db import models


class Theme(models.TextChoices):
    DARK = 'dark'
    LIGHT = 'light'


class ClockFormat(models.TextChoices):
    TWELVE = '12h'
    TWENTY_FOUR = '24h'


class SearchEngineChoices(models.TextChoices):
    GOOGLE = 'google'
    DUCKDUCKGO = 'duckduckgo'
    BING = 'bing'
    YOUTUBE = 'youtube'
    CHATGPT = 'chatgpt'
    CLAUDE = 'claude'


class UserDetail(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    workday_routine = models.TextField(default='')  # Legacy, kept for migration
    holiday_routine = models.TextField(default='')  # Legacy, kept for migration
    default_theme = models.CharField(
        max_length=16,
        choices=Theme.choices,
        default=Theme.LIGHT
    )
    # Search
    default_search_engine = models.CharField(
        max_length=32,
        choices=SearchEngineChoices.choices,
        default=SearchEngineChoices.GOOGLE
    )
    # Pomodoro
    pomodoro_focus = models.IntegerField(default=25)
    pomodoro_break = models.IntegerField(default=5)
    pomodoro_long_break = models.IntegerField(default=15)
    pomodoro_cycles = models.IntegerField(default=4)
    # Font
    font_family = models.CharField(max_length=64, default='Montserrat')
    # Sound
    sound_pomodoro = models.BooleanField(default=True)
    sound_notifications = models.BooleanField(default=True)
    # Sleep
    sleep_time = models.TimeField(null=True, blank=True, default=None)
    # Clock
    clock_format = models.CharField(
        max_length=4,
        choices=ClockFormat.choices,
        default=ClockFormat.TWELVE
    )

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Friend(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='user')
    friend = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friend')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'friend')


class TaskGroup(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_groups')
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = ('user', 'name')

    def __str__(self):
        return f'{self.user} - {self.name}'


class Task(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    group = models.ForeignKey(TaskGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    task_name = models.TextField()
    deadline = models.DateTimeField(null=True, blank=True)
    is_done = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user} - {self.task_name}'

    class Meta:
        ordering = ['-created_at']


class DailyData(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    journal = models.TextField(null=True, blank=True, default='')
    sleep_hours = models.DecimalField(max_digits=5, decimal_places=2, default=None, null=True)
    focus_minutes = models.IntegerField(default=0)

    class Meta:
        ordering = ['date']
        unique_together = ('user', 'date')


class HabitStatus(models.TextChoices):
    ACTIVE = 'active'
    DELETED = 'deleted'
    COMPLETED = 'completed'


class Habit(models.Model):
    id = models.AutoField(primary_key=True)
    habit = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    detail = models.TextField(blank=True)
    identity = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    frequency = ArrayField(models.IntegerField(), size=7, default=list)
    notify_at = models.TimeField(null=True, blank=True, default=None)
    status = models.CharField(
        max_length=10,
        choices=HabitStatus.choices,
        default=HabitStatus.ACTIVE.value
    )

    @property
    def current_streak(self):
        logs = {x.date.isoformat(): x.is_done for x in self.habitlog_set.all()}
        current_streak = 0
        today = date.today()
        min_date = self.created_at.date()

        today_weekday = today.weekday()
        today_is_scheduled = not self.frequency or today_weekday in self.frequency
        today_is_done = logs.get(today.isoformat(), False)

        if today_is_scheduled and not today_is_done:
            current_date = today - timedelta(days=1)
        else:
            current_date = today

        while current_date >= min_date:
            weekday = current_date.weekday()
            if self.frequency and (weekday not in self.frequency):
                current_date -= timedelta(days=1)
                continue

            if logs.get(current_date.isoformat(), False):
                current_streak += 1
                current_date -= timedelta(days=1)
            else:
                break
        return current_streak

    @property
    def max_streak(self):
        logs = list(self.habitlog_set.filter(
            is_done=True
        ).order_by('date').values_list('date', flat=True))

        if not logs:
            return 0

        max_streak = 0
        current_streak = 1
        for i in range(1, len(logs)):
            prev_date = logs[i - 1]
            curr_date = logs[i]
            next_scheduled = prev_date + timedelta(days=1)
            while self.frequency and (next_scheduled.weekday() not in self.frequency):
                next_scheduled += timedelta(days=1)
            if curr_date == next_scheduled:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 1

        return max(max_streak, current_streak)


class LogStatus(models.TextChoices):
    DONE = 'done'
    PENDING = 'pending'


class HabitLog(models.Model):
    id = models.AutoField(primary_key=True)
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE)
    date = models.DateField()
    is_done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('habit', 'date')


class AccountabilityPartner(models.Model):
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE)
    partner = models.ForeignKey(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['habit', 'partner']


# ──────────────────────────────────────
# New Models
# ──────────────────────────────────────

class RoutineType(models.TextChoices):
    WORKDAY = 'workday'
    HOLIDAY = 'holiday'


class RoutineEntry(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='routine_entries')
    routine_type = models.CharField(max_length=10, choices=RoutineType.choices)
    title = models.CharField(max_length=255)
    time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['time', 'id']
        unique_together = ('user', 'routine_type', 'time', 'title')

    def __str__(self):
        return f'{self.user} - {self.routine_type} - {self.time} {self.title}'


class ReadingListItem(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reading_list')
    name = models.CharField(max_length=255)
    url = models.URLField()
    icon = models.URLField(null=True, blank=True)  # Favicon URL, null = auto-generate on frontend
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} - {self.name}'


class TimelineEventType(models.TextChoices):
    HABIT = 'habit'
    TODO = 'todo'
    ROUTINE = 'routine'
    SLEEP_TRACKER = 'sleep_tracker'
    JOURNAL = 'journal'
    TEXT = 'text'
    MEETING = 'meeting'


class TimelineEvent(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='timeline_events')
    timestamp = models.DateTimeField()
    event_type = models.CharField(max_length=16, choices=TimelineEventType.choices)
    event = models.TextField()  # Human readable description
    reference = models.JSONField(null=True, blank=True)  # {"model": "Habit", "id": 5}
    action = models.JSONField(null=True, blank=True)  # {"mark_done": [true, false]} or {"status": ["pending","done"]}
    action_response = models.JSONField(null=True, blank=True)  # {"mark_done": true}
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['user', 'event_type', 'timestamp']),
        ]

    def __str__(self):
        return f'{self.user} - {self.event_type} - {self.event[:50]}'


class SearchEngine(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=64)
    key = models.CharField(max_length=32, unique=True)
    url_template = models.CharField(max_length=500)  # e.g. https://www.google.com/search?q={query}
    icon = models.CharField(max_length=64)  # FA icon class
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
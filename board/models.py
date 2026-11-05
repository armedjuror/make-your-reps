import uuid
from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.db import models


class Theme(models.TextChoices):
    INK = 'ink'
    TERMINAL = 'terminal'
    TECH = 'tech'
    AURORA = 'aurora'
    SENSEI = 'sensei'
    COACH = 'coach'
    GARDEN = 'garden'
    ORBIT = 'orbit'
    QUEST = 'quest'
    # Legacy names, kept so existing rows stay valid. The UI maps
    # 'dark' to 'ink' and 'light', 'paper' and 'plain' to 'aurora'.
    PAPER = 'paper'
    PLAIN = 'plain'
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


def default_weekend():
    return [5, 6]


class StreakRule(models.TextChoices):
    ACTIVITY = 'activity'   # today's rule: any counted action keeps the streak
    ROUTINE = 'routine'     # the day must meet its routine bar


class UserDetail(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    workday_routine = models.TextField(default='')  # Legacy, kept for migration
    holiday_routine = models.TextField(default='')  # Legacy, kept for migration
    default_theme = models.CharField(
        max_length=16,
        choices=Theme.choices,
        default=Theme.DARK
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

    # Gamification
    total_points = models.IntegerField(default=0)
    level = models.IntegerField(default=1)
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    last_active_date = models.DateField(null=True, blank=True, default=None)

    is_onboarded = models.BooleanField(default=False)

    # Resilient days
    weekend_days = ArrayField(models.IntegerField(), default=default_weekend)  # Monday = 0
    day_start = models.TimeField(default=time(4, 0))  # activity before this belongs to yesterday
    freezes = models.PositiveSmallIntegerField(default=1)
    travel_ramp_days = models.PositiveSmallIntegerField(default=1)
    streak_rule = models.CharField(max_length=8, choices=StreakRule.choices, default=StreakRule.ACTIVITY)
    slip_metric = models.ForeignKey(
        'Metric', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    # Writing the day's journal marks this habit done
    journal_habit = models.ForeignKey(
        'Habit', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    # Privacy mode (PIN hides private items; it is not encryption)
    private_pin_hash = models.CharField(max_length=128, blank=True, default='')
    private_unlock_minutes = models.PositiveSmallIntegerField(default=10)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Friend(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friendships')
    friend = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friend_of')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'friend')


class FriendRequestStatus(models.TextChoices):
    PENDING = 'pending'
    ACCEPTED = 'accepted'
    DECLINED = 'declined'


class FriendRequest(models.Model):
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_friend_requests')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='received_friend_requests')
    invited_email = models.EmailField(null=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    status = models.CharField(max_length=10, choices=FriendRequestStatus.choices, default=FriendRequestStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('from_user', 'to_user')
        ordering = ['-created_at']


class TaskGroup(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_groups')
    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

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
    # Resilient days: how this habit behaves on Light / Disrupted days
    on_light = models.CharField(max_length=8, default='required')       # required / excused
    on_disrupted = models.CharField(max_length=8, default='excused')    # required / excused
    # Metrics, checklists, privacy
    metric = models.ForeignKey('Metric', null=True, blank=True, on_delete=models.SET_NULL, related_name='habits')
    current_stage = models.PositiveSmallIntegerField(default=1)
    complete_when = models.CharField(max_length=8, default='all')       # all / any
    is_private = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)                      # hidden system habit (Reset)
    private_reminder = models.BooleanField(default=False)               # locked: show a bare 'Reminder' instead of nothing

    def _streaks(self):
        """(current, max), cached on the instance. Views may set ``_streak_ctx`` to share one context."""
        cached = getattr(self, '_streak_cache', None)
        if cached is None:
            from board.streaks import StreakContext, habit_streaks
            ctx = getattr(self, '_streak_ctx', None) or StreakContext(self.user_id)
            logs = {x.date: x.is_done for x in self.habitlog_set.all()}
            cached = self._streak_cache = habit_streaks(self, logs, ctx)
        return cached

    @property
    def current_streak(self):
        return self._streaks()[0]

    @property
    def max_streak(self):
        return self._streaks()[1]


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

class AccountabilityPartnerStatus(models.TextChoices):
    REQUEST_SENT = 'request-sent'
    ACTIVE = 'active'
    INACTIVE = 'inactive'


class AccountabilityPartner(models.Model):
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name='accountability_partners')
    partner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='accountability_partnerships')
    invited_email = models.EmailField(null=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True)
    status = models.CharField(max_length=20, choices=AccountabilityPartnerStatus.choices, default=AccountabilityPartnerStatus.REQUEST_SENT)
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


class Tier(models.TextChoices):
    ESSENTIAL = 'essential'   # shown in every mode; never shifted
    ANCHOR = 'anchor'         # Normal + Light
    FLEXIBLE = 'flexible'     # Normal only; first to be dropped


class RoutineEntry(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='routine_entries')
    routine_type = models.CharField(max_length=10, choices=RoutineType.choices)
    title = models.CharField(max_length=255)
    time = models.TimeField()
    tier = models.CharField(max_length=10, choices=Tier.choices, default=Tier.ANCHOR)
    fixed_time = models.BooleanField(default=False)  # True: running late never shifts it
    duration_min = models.PositiveSmallIntegerField(null=True, blank=True)  # null: ends at next block
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
    FRIEND_REQUEST = 'friend_request'
    ACCOUNTABILITY_INVITE = 'accountability_invite'
    ACCOUNTABILITY_HABIT = 'accountability_habit'


class TimelineEvent(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='timeline_events')
    timestamp = models.DateTimeField()
    event_type = models.CharField(max_length=32, choices=TimelineEventType.choices)
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


# ──────────────────────────────────────
# Gamification
# ──────────────────────────────────────

class Achievement(models.Model):
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=255)
    icon = models.CharField(max_length=64)  # FA icon class
    category = models.CharField(max_length=32, default='general')

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name


class UserAchievement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'achievement')
        ordering = ['-unlocked_at']


# ──────────────────────────────────────
# Google Calendar Integration
# ──────────────────────────────────────

class GoogleCalendarToken(models.Model):
    """Stores OAuth tokens for one Google account linked by a user.
    A user can connect multiple Google accounts (one row per account)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='google_calendar_tokens')
    google_email = models.EmailField()
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'google_email')

    def __str__(self):
        return f'{self.user} — {self.google_email}'


class LinkedCalendar(models.Model):
    """A single Google Calendar within a connected Google account."""
    token = models.ForeignKey(GoogleCalendarToken, on_delete=models.CASCADE, related_name='calendars')
    calendar_id = models.CharField(max_length=500)        # Google Calendar ID (e.g. primary or email)
    name = models.CharField(max_length=255)
    color = models.CharField(max_length=32, blank=True)
    is_enabled = models.BooleanField(default=False)       # Show events in timeline
    sync_habits = models.BooleanField(default=False)      # Push habit reminders to this calendar
    sync_tasks = models.BooleanField(default=False)       # Push task deadlines to this calendar
    # Webhook channel for real-time updates
    webhook_channel_id = models.CharField(max_length=255, blank=True)
    webhook_resource_id = models.CharField(max_length=255, blank=True)
    webhook_expiry = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('token', 'calendar_id')

    def __str__(self):
        return f'{self.token.google_email} — {self.name}'


class Feedback(models.Model):
    TYPES = [
        ('general', 'General'),
        ('bug', 'Bug Report'),
        ('feature', 'Feature Request'),
    ]
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    type = models.CharField(max_length=20, choices=TYPES, default='general')
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_type_display()}: {self.subject}"


# ──────────────────────────────────────
# Resilient days: day plans, block logs, summaries
# ──────────────────────────────────────

class DayMode(models.TextChoices):
    NORMAL = 'normal'
    LIGHT = 'light'
    DISRUPTED = 'disrupted'


class DayPlan(models.Model):
    """One row per user per date. No row means: weekday rule + Normal."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='day_plans')
    date = models.DateField()
    template = models.CharField(max_length=10, choices=RoutineType.choices)
    mode = models.CharField(max_length=10, choices=DayMode.choices, default=DayMode.NORMAL)
    # manual / checkin / travel / ramp / reset / slip
    source = models.CharField(max_length=10, default='manual')
    shifts = models.JSONField(default=list)  # running late: [{"at": iso, "minutes": 30}, ...]
    slips = models.JSONField(default=list)   # private: [{"at": iso, "note": "..."}]
    reset_done_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=160, blank=True, default='')  # off day: 'Night shift: ward 3'

    class Meta:
        unique_together = ('user', 'date')

    def __str__(self):
        return f'{self.user} {self.date} {self.template}/{self.mode}'


class BlockStatus(models.TextChoices):
    DONE = 'done'
    SKIPPED = 'skipped'
    DROPPED = 'dropped'   # 'missed' is derived, never stored


class BlockLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='block_logs')
    date = models.DateField()
    entry = models.ForeignKey(RoutineEntry, null=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=255)        # snapshot, survives entry deletion
    scheduled_time = models.TimeField()             # snapshot
    tier = models.CharField(max_length=10, choices=Tier.choices, default=Tier.ANCHOR)  # snapshot
    status = models.CharField(max_length=8, choices=BlockStatus.choices)
    reason = models.CharField(max_length=120, blank=True)
    logged_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'date', 'entry')


class DaySummary(models.Model):
    """One row per closed day; the streak source of truth."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='day_summaries')
    date = models.DateField()
    mode = models.CharField(max_length=10)
    required = models.PositiveSmallIntegerField(default=0)
    required_done = models.PositiveSmallIntegerField(default=0)
    outcome = models.CharField(max_length=8)  # met / reset / frozen / missed / legacy

    class Meta:
        unique_together = ('user', 'date')


# ──────────────────────────────────────
# Metrics, checklists, journals
# ──────────────────────────────────────

class MetricKind(models.TextChoices):
    COUNTER = 'counter'
    ADDITIVE = 'additive'
    SINGLE = 'single'


class Metric(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='metrics')
    name = models.CharField(max_length=64)          # Walk, Coffee, Water, Sleep
    unit = models.CharField(max_length=16, blank=True)
    kind = models.CharField(max_length=8, choices=MetricKind.choices, default=MetricKind.ADDITIVE)
    direction = models.CharField(max_length=8, default='at_least')  # at_least / at_most
    target = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    target_light = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    quick_steps = ArrayField(models.DecimalField(max_digits=8, decimal_places=2), default=list)
    fields = models.JSONField(default=list)  # [{key, label, type: choice|scale|text, options?, allow_other?, max?}]
    is_private = models.BooleanField(default=False)
    is_system = models.BooleanField(default=False)  # built-in, cannot be deleted
    system_key = models.CharField(max_length=8, blank=True, default='')  # 'sleep' or 'slip'
    remind_at = models.TimeField(null=True, blank=True)  # daily reminder on the timeline
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.user} - {self.name}'


class MetricEntry(models.Model):
    metric = models.ForeignKey(Metric, on_delete=models.CASCADE, related_name='entries')
    date = models.DateField()        # follows day_start
    at = models.DateTimeField()      # auto now, editable for back-logging
    value = models.DecimalField(max_digits=8, decimal_places=2)
    data = models.JSONField(default=dict)  # {trigger: 'after meal', urge: 4}; single: {previous: 6.5}

    class Meta:
        ordering = ['at', 'id']
        indexes = [models.Index(fields=['metric', 'date'])]


class HabitStep(models.Model):
    habit = models.ForeignKey(Habit, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)               # Glute bridges
    target = models.CharField(max_length=60, blank=True)  # 2 x 10-12, 20 s hold
    how_to = models.TextField(blank=True)                 # push through heels, don't arch
    stage = models.PositiveSmallIntegerField(default=1)   # shown when habit.current_stage >= stage
    metric = models.ForeignKey(Metric, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['order', 'id']


class HabitStepLog(models.Model):
    step = models.ForeignKey(HabitStep, on_delete=models.CASCADE, related_name='logs')
    date = models.DateField()
    done = models.BooleanField(default=False)
    value = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('step', 'date')


class Journal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='journals')
    name = models.CharField(max_length=64)
    metric = models.OneToOneField(Metric, null=True, blank=True, on_delete=models.SET_NULL, related_name='journal')
    is_default = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)


class JournalEntry(models.Model):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name='entries')
    date = models.DateField()
    at = models.DateTimeField()
    text = models.TextField()
    metric_entry = models.OneToOneField(MetricEntry, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-at', '-id']

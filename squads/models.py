"""
Squads: shared boards for habits, todos, trackers and focus sessions.

Every shareable item (Habit, Task, Metric, FocusSession) belongs to a Board.
A user's own items live on their personal board; a squad or challenge is just
another board type. Members take part through *linked* personal items: the
squad habit is the shared definition, each member logs their own linked copy
in Today, and the ledger (``Contribution``) turns those logs into squad stats.
"""
import secrets
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.utils import timezone as dj_tz


def _tz_default():
    return settings.TIME_ZONE


def _now():
    return dj_tz.now()


# ──────────────────────────────────────
# Boards and membership
# ──────────────────────────────────────

class BoardType(models.TextChoices):
    PERSONAL = 'personal'
    SQUAD = 'squad'
    CHALLENGE = 'challenge'


class BoardTemplate(models.TextChoices):
    STUDY = 'study'
    FITNESS = 'fitness'
    FAMILY = 'family'
    CUSTOM = 'custom'


class BoardStatus(models.TextChoices):
    ACTIVE = 'active'
    ARCHIVED = 'archived'      # read-only, chosen by an admin
    READ_ONLY = 'read_only'    # read-only, forced by a plan downgrade


DEFAULT_BOARD_SETTINGS = {
    'streak_threshold_pct': None,   # None: 100 for 2-member squads, 70 for 3+
    'late_log_cutoff_hour': 10,     # logs for a day close at 10:00 next day
    'at_risk_hour': 20,
}


class Board(models.Model):
    type = models.CharField(max_length=10, choices=BoardType.choices, default=BoardType.PERSONAL)
    name = models.CharField(max_length=80, blank=True, default='')
    emoji = models.CharField(max_length=16, blank=True, default='')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_boards')
    timezone = models.CharField(max_length=64, default=_tz_default)
    template = models.CharField(max_length=10, choices=BoardTemplate.choices, default=BoardTemplate.CUSTOM)
    settings = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=BoardStatus.choices, default=BoardStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['owner'], condition=Q(type='personal'),
                                    name='one_personal_board_per_user'),
        ]

    def __str__(self):
        return f'{self.type}:{self.name or self.owner_id}'

    # -- settings and time --
    def setting(self, key):
        return (self.settings or {}).get(key, DEFAULT_BOARD_SETTINGS.get(key))

    @property
    def tz(self):
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo(settings.TIME_ZONE)

    def local_now(self, now=None):
        return (now or dj_tz.now()).astimezone(self.tz)

    def local_today(self, now=None):
        return self.local_now(now).date()

    def local_datetime(self, day, t):
        return datetime.combine(day, t, tzinfo=self.tz)

    def cutoff_for(self, day):
        """Logs for ``day`` may be added or edited until this moment."""
        return self.local_datetime(day + timedelta(days=1), time(int(self.setting('late_log_cutoff_hour')), 0))

    @property
    def is_writable(self):
        return self.status == BoardStatus.ACTIVE

    def active_memberships(self):
        return self.memberships.filter(status=MembershipStatus.ACTIVE)

    def threshold_pct(self, member_count):
        configured = self.setting('streak_threshold_pct')
        if configured:
            return int(configured)
        return 100 if member_count <= 2 else 70

    @classmethod
    def personal_for(cls, user_or_id):
        """The user's personal board, created on first use."""
        user_id = getattr(user_or_id, 'id', user_or_id)
        board = cls.objects.filter(owner_id=user_id, type=BoardType.PERSONAL).first()
        if board is None:
            board, _ = cls.objects.get_or_create(owner_id=user_id, type=BoardType.PERSONAL)
        return board


class Role(models.TextChoices):
    OWNER = 'owner'
    ADMIN = 'admin'
    MEMBER = 'member'


class MembershipStatus(models.TextChoices):
    ACTIVE = 'active'
    LEFT = 'left'
    REMOVED = 'removed'


class BoardMembership(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='board_memberships')
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(max_length=8, choices=MembershipStatus.choices, default=MembershipStatus.ACTIVE)
    joined_at = models.DateTimeField(default=_now)
    left_at = models.DateTimeField(null=True, blank=True)
    added_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    added_directly = models.BooleanField(default=False)       # shows the Stay / Leave notice
    add_acknowledged = models.BooleanField(default=True)
    muted = models.BooleanField(default=False)
    away_from = models.DateField(null=True, blank=True)
    away_until = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ('board', 'user')

    def __str__(self):
        return f'{self.user_id}@{self.board_id} ({self.role}/{self.status})'

    @property
    def is_admin(self):
        return self.status == MembershipStatus.ACTIVE and self.role in (Role.OWNER, Role.ADMIN)

    def joined_day(self):
        return self.board.local_now(self.joined_at).date()

    def is_away_on(self, day):
        if not self.away_until or day > self.away_until:
            return False
        return self.away_from is None or day >= self.away_from


def _invite_token():
    return secrets.token_urlsafe(12)


def _invite_expiry():
    return dj_tz.now() + timedelta(days=7)


class Invite(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='invites')
    token = models.CharField(max_length=32, unique=True, default=_invite_token)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    expires_at = models.DateTimeField(default=_invite_expiry)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    uses = models.PositiveIntegerField(default=0)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_valid(self):
        if self.revoked or self.expires_at <= dj_tz.now():
            return False
        return self.max_uses is None or self.uses < self.max_uses


class MemberSuggestion(models.Model):
    """A member suggests a friend; an admin approves (B4)."""
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='suggestions')
    suggested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    status = models.CharField(max_length=10, default='pending')  # pending / approved / declined
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('board', 'user')


class ItemOptOut(models.Model):
    """A member opted out of an optional squad habit (core habits can't be opted out)."""
    habit = models.ForeignKey('board.Habit', on_delete=models.CASCADE, related_name='opt_outs')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('habit', 'user')


# ──────────────────────────────────────
# Scoring and goals
# ──────────────────────────────────────

class ContributionReason(models.TextChoices):
    CHECKIN = 'checkin'                 # a log on a linked habit (ledger only, 0 points)
    VALUE = 'value'                     # a tracker log feeding a goal (ledger only)
    CORE_DONE = 'core_done'             # 10: own core check-ins done for the day
    DAY_SURVIVED = 'day_survived'       # +5 each member who was in
    STREAK_SAVER = 'streak_saver'       # +5 the check-in that crossed the threshold
    FOCUS = 'focus'                     # 15 each, quorum met
    FOCUS_HOST = 'focus_host'           # +5 host
    NUDGE = 'nudge'                     # +3 nudge converted within 2 h
    GOAL = 'goal'                       # proportional, capped per member per day


class Contribution(models.Model):
    """Append-only ledger. Edits append a reversal row, never update in place."""
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='contributions')
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='contributions')
    member_label = models.CharField(max_length=80, blank=True, default='')   # 'Former member' once anonymised
    source_type = models.CharField(max_length=24)        # habitlog / metricentry / day / focus / nudge
    source_id = models.BigIntegerField(null=True, blank=True)
    goal = models.ForeignKey('SquadGoal', null=True, blank=True, on_delete=models.SET_NULL, related_name='contributions')
    points = models.IntegerField(default=0)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reason = models.CharField(max_length=16, choices=ContributionReason.choices)
    day = models.DateField()
    late = models.BooleanField(default=False)
    reversal_of = models.OneToOneField('self', null=True, blank=True, on_delete=models.CASCADE, related_name='reversed_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['board', 'day']),
            models.Index(fields=['board', 'user', 'day']),
            models.Index(fields=['source_type', 'source_id']),
        ]


class GoalAggregation(models.TextChoices):
    SUM = 'sum'
    COUNT = 'count'
    AVG = 'avg'


class SquadGoal(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='goals')
    title = models.CharField(max_length=120, blank=True, default='')
    tracker = models.ForeignKey('board.Metric', null=True, blank=True, on_delete=models.CASCADE, related_name='squad_goals')
    habit = models.ForeignKey('board.Habit', null=True, blank=True, on_delete=models.CASCADE, related_name='squad_goals')
    aggregation = models.CharField(max_length=5, choices=GoalAggregation.choices, default=GoalAggregation.SUM)
    unit = models.CharField(max_length=16, blank=True, default='')       # locked at creation
    target = models.DecimalField(max_digits=12, decimal_places=2)
    period_start = models.DateField()
    period_end = models.DateField()
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['period_end', 'id']


class SquadStreak(models.Model):
    board = models.OneToOneField(Board, on_delete=models.CASCADE, related_name='streak')
    current = models.PositiveIntegerField(default=0)
    best = models.PositiveIntegerField(default=0)
    last_evaluated_date = models.DateField(null=True, blank=True)


class DayStatus(models.TextChoices):
    SURVIVED = 'survived'
    BROKEN = 'broken'     # missed, and it ended a running streak
    BELOW = 'below'       # missed, no streak to break
    OFF = 'off'           # nobody counted (all away / off)
    REST = 'rest'         # no core habit scheduled


class DayResult(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='day_results')
    day = models.DateField()
    members_in = models.PositiveSmallIntegerField(default=0)
    members_counted = models.PositiveSmallIntegerField(default=0)
    threshold_pct = models.PositiveSmallIntegerField(default=100)
    survived = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=DayStatus.choices, default=DayStatus.BELOW)
    details = models.JSONField(default=dict)   # {user_id: 'in' | 'out' | 'away' | 'off' | 'first_day' | 'none'}
    evaluated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('board', 'day')
        ordering = ['day']

    @property
    def pct_in(self):
        return round(100 * self.members_in / self.members_counted) if self.members_counted else 0


class LeaderboardWeek(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='leaderboard_weeks')
    week_start = models.DateField()
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    points = models.IntegerField(default=0)
    is_mvp = models.BooleanField(default=False)

    class Meta:
        unique_together = ('board', 'week_start', 'user')


class Nudge(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='nudges')
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='nudges_sent')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='nudges_received')
    day = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    converted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('from_user', 'to_user', 'day')   # max one per pair per day


# ──────────────────────────────────────
# Focus sessions
# ──────────────────────────────────────

class FocusStatus(models.TextChoices):
    SCHEDULED = 'scheduled'
    LIVE = 'live'
    DONE = 'done'
    CANCELLED = 'cancelled'


def _ics_uid():
    return f'{uuid.uuid4()}@makeyourreps.com'


class FocusSession(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='focus_sessions')
    host = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='hosted_focus_sessions')
    title = models.CharField(max_length=120, blank=True, default='Focus session')
    start_at = models.DateTimeField()
    block_minutes = models.PositiveSmallIntegerField(default=50)
    blocks = models.PositiveSmallIntegerField(default=1)
    break_minutes = models.PositiveSmallIntegerField(default=10)
    ics_uid = models.CharField(max_length=80, unique=True, default=_ics_uid)
    ics_sequence = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=FocusStatus.choices, default=FocusStatus.SCHEDULED)
    linked_habit = models.ForeignKey('board.Habit', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    quorum_met = models.BooleanField(default=False)
    reminded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_at']

    @property
    def total_minutes(self):
        return self.block_minutes * self.blocks + self.break_minutes * max(0, self.blocks - 1)

    @property
    def focus_minutes(self):
        return self.block_minutes * self.blocks

    @property
    def end_at(self):
        return self.start_at + timedelta(minutes=self.total_minutes)

    @property
    def late_join_until(self):
        return self.start_at + timedelta(minutes=self.block_minutes)

    def block_windows(self):
        """[(start, end), ...] for each focus block."""
        out, t = [], self.start_at
        for i in range(self.blocks):
            out.append((t, t + timedelta(minutes=self.block_minutes)))
            t += timedelta(minutes=self.block_minutes + self.break_minutes)
        return out


class FocusRSVP(models.Model):
    session = models.ForeignKey(FocusSession, on_delete=models.CASCADE, related_name='rsvps')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    response = models.CharField(max_length=5, null=True, blank=True)   # yes / no / maybe
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'user')


class FocusAttendance(models.Model):
    session = models.ForeignKey(FocusSession, on_delete=models.CASCADE, related_name='attendance')
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    joined_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    left_at = models.DateTimeField(null=True, blank=True)
    seconds = models.PositiveIntegerField(default=0)
    block_seconds = models.JSONField(default=list)    # seconds present in each focus block
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('session', 'user')   # one person on two devices counts once

    @property
    def minutes(self):
        return self.seconds // 60


class CalendarDelivery(models.Model):
    session = models.ForeignKey(FocusSession, on_delete=models.CASCADE, related_name='deliveries')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    channel = models.CharField(max_length=10)        # google / ics_email
    external_id = models.CharField(max_length=255, blank=True, default='')
    calendar_token = models.ForeignKey('board.GoogleCalendarToken', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, default='sent')   # sent / failed / cancelled
    sequence = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'user')


# ──────────────────────────────────────
# Challenges
# ──────────────────────────────────────

class ChallengeKind(models.TextChoices):
    STREAK = 'streak'      # do the item every day
    TARGET = 'target'      # hit a tracker value every day
    LADDER = 'ladder'      # the daily target climbs by a step each day
    VERSUS = 'versus'      # squads compete on team score


class ChallengeVisibility(models.TextChoices):
    SQUAD = 'squad'
    LINK = 'link'
    PUBLIC = 'public'


class Challenge(models.Model):
    board = models.OneToOneField(Board, on_delete=models.CASCADE, related_name='challenge')
    parent_board = models.ForeignKey(Board, null=True, blank=True, on_delete=models.SET_NULL, related_name='child_challenges')
    host = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='hosted_challenges')
    kind = models.CharField(max_length=8, choices=ChallengeKind.choices, default=ChallengeKind.STREAK)
    visibility = models.CharField(max_length=8, choices=ChallengeVisibility.choices, default=ChallengeVisibility.SQUAD)
    title = models.CharField(max_length=120)
    slug = models.CharField(max_length=32, unique=True, default=_invite_token)
    start_date = models.DateField()
    end_date = models.DateField()
    join_deadline = models.DateField(null=True, blank=True)
    # {item_template: {name, unit}, daily_target, ladder_step, skip_tokens,
    #  scoring: points|completion, team_mode: sum|completion, late_join: prorate|ineligible}
    rules = models.JSONField(default=dict)
    rules_locked_at = models.DateTimeField(null=True, blank=True)
    participant_cap = models.PositiveIntegerField(null=True, blank=True)
    ended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_date', 'id']

    def rule(self, key, default=None):
        return (self.rules or {}).get(key, default)

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1

    def target_for_day(self, day_number):
        base = float(self.rule('daily_target') or 1)
        if self.kind == ChallengeKind.LADDER:
            return base + float(self.rule('ladder_step') or 1) * (day_number - 1)
        return base

    def phase(self, today=None):
        today = today or dj_tz.localdate()
        if self.ended or today > self.end_date:
            return 'ended'
        return 'active' if today >= self.start_date else 'upcoming'


class ParticipantStatus(models.TextChoices):
    ACTIVE = 'active'
    COMPLETED = 'completed'
    DROPPED = 'dropped'
    UNOFFICIAL = 'unofficial'   # dropped (or ineligible late join), carries on for themselves
    REMOVED = 'removed'         # removed by the host


class ChallengeParticipant(models.Model):
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='challenge_participations')
    team_board = models.ForeignKey(Board, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    status = models.CharField(max_length=10, choices=ParticipantStatus.choices, default=ParticipantStatus.ACTIVE)
    timezone = models.CharField(max_length=64, default=_tz_default)
    habit = models.ForeignKey('board.Habit', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    metric = models.ForeignKey('board.Metric', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    skips_used = models.PositiveSmallIntegerField(default=0)
    days_done = models.PositiveSmallIntegerField(default=0)
    progress_cache = models.JSONField(default=dict)
    joined_at = models.DateTimeField(default=_now)
    eligible = models.BooleanField(default=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('challenge', 'user')

    @property
    def tz(self):
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo(settings.TIME_ZONE)

    def local_today(self, now=None):
        return (now or dj_tz.now()).astimezone(self.tz).date()


class ChallengeDay(models.Model):
    participant = models.ForeignKey(ChallengeParticipant, on_delete=models.CASCADE, related_name='days')
    day = models.DateField()
    outcome = models.CharField(max_length=6)   # done / skip / miss
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        unique_together = ('participant', 'day')


# ──────────────────────────────────────
# Feed and reactions
# ──────────────────────────────────────

class FeedItem(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='feed')
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField(max_length=20)    # checkin / todo_done / session / milestone / joined / left / day
    text = models.CharField(max_length=255)
    ref = models.JSONField(default=dict, blank=True)
    late = models.BooleanField(default=False)
    reactable = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


REACTION_EMOJIS = ['👏', '🔥', '💪', '🎉', '❤️']


class Reaction(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    target_type = models.CharField(max_length=16, default='feed')
    target_id = models.BigIntegerField()
    emoji = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'target_type', 'target_id')   # one reaction per user per item


# ──────────────────────────────────────
# Safety
# ──────────────────────────────────────

class Block(models.Model):
    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocks_made')
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blocks_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('blocker', 'blocked')


class Report(models.Model):
    reporter = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    target_type = models.CharField(max_length=16)     # user / squad / challenge
    target_id = models.BigIntegerField()
    reason = models.TextField()
    status = models.CharField(max_length=10, default='open')   # open / actioned / dismissed
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


# ──────────────────────────────────────
# Notifications
# ──────────────────────────────────────

class PushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.TextField(unique=True)
    keys = models.JSONField(default=dict)
    channel = models.CharField(max_length=8, default='webpush')   # webpush / fcm
    created_at = models.DateTimeField(auto_now_add=True)


class NotificationPrefs(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_prefs')
    timezone = models.CharField(max_length=64, default=_tz_default)
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)
    daily_cap = models.PositiveSmallIntegerField(default=6)


class NotificationLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_logs')
    board = models.ForeignKey(Board, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField(max_length=24)
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=400, blank=True, default='')
    url = models.CharField(max_length=400, blank=True, default='')
    channels = models.JSONField(default=list)
    status = models.CharField(max_length=10, default='sent')   # sent / queued / dropped / muted
    reason = models.CharField(max_length=40, blank=True, default='')
    deliver_after = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


# ──────────────────────────────────────
# Plans and instrumentation
# ──────────────────────────────────────

class UserPlan(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='plan_state')
    plan = models.CharField(max_length=16, default='free')
    paid_until = models.DateTimeField(null=True, blank=True)
    verified_host = models.BooleanField(default=False)
    upgrade_trigger = models.CharField(max_length=40, blank=True, default='')   # last limit that blocked
    updated_at = models.DateTimeField(auto_now=True)


class Event(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    name = models.CharField(max_length=40, db_index=True)
    props = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

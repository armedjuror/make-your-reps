"""
Fitness: the exercise library, programs and the user's fitness profile.

A Program belongs to the user's Activity habit and is shaped
Program → Phase (week range) → DayTemplate (weekday) → blocks (JSON).
Today's Activity subtasks are the expansion of today's DayTemplate
(``fitness.program.expand``); nothing is generated ahead of time.
"""
from django.contrib.auth.models import User
from django.db import models


class Pattern(models.TextChoices):
    SQUAT = 'squat'
    HINGE = 'hinge'
    LUNGE = 'lunge'
    HORIZONTAL_PUSH = 'horizontal_push'
    VERTICAL_PUSH = 'vertical_push'
    HORIZONTAL_PULL = 'horizontal_pull'
    VERTICAL_PULL = 'vertical_pull'
    CORE_ANTI_EXTENSION = 'core_anti_extension'
    CORE_ANTI_ROTATION = 'core_anti_rotation'
    CORE_FLEXION = 'core_flexion'
    CORE_LATERAL = 'core_lateral'
    ISOLATION_UPPER = 'isolation_upper'
    ISOLATION_LOWER = 'isolation_lower'
    CARDIO = 'cardio'
    WARMUP = 'warmup'
    MOBILITY = 'mobility'
    STRETCH = 'stretch'


class Intensity(models.TextChoices):
    HEAVY = 'heavy'
    MODERATE = 'moderate'
    LIGHT = 'light'


class Measure(models.TextChoices):
    REPS = 'reps'
    TIME = 'time'


# ── Shared catalogue (no user FK) ──────────────────────────

class Exercise(models.Model):
    """Imported from exercises.json by ``import_exercises``; never edited by users."""
    id = models.SlugField(primary_key=True, max_length=64)        # band_squat
    name = models.CharField(max_length=120)
    aliases = models.JSONField(default=list)
    pattern = models.CharField(max_length=24, choices=Pattern.choices)
    primary_muscles = models.JSONField(default=list)
    secondary_muscles = models.JSONField(default=list)
    equipment = models.JSONField(default=list)
    settings = models.JSONField(default=list)                     # ["home", "gym"]
    level = models.PositiveSmallIntegerField(default=1)           # 1-3
    intensity = models.CharField(max_length=10, choices=Intensity.choices, default=Intensity.MODERATE)
    measure = models.CharField(max_length=5, choices=Measure.choices, default=Measure.REPS)
    default_reps = models.JSONField(null=True, blank=True)        # [10, 12]
    default_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    sec_per_rep = models.FloatField(default=3.0)
    unilateral = models.BooleanField(default=False)
    met = models.FloatField(default=3.5)
    contraindications = models.JSONField(default=list)            # knee, lower_back, shoulder...
    regression = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    progression = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    steps = models.JSONField(default=list)
    avoid = models.JSONField(default=list)
    breathing = models.CharField(max_length=255, blank=True, default='')
    video_query = models.CharField(max_length=160, blank=True, default='')
    animation = models.JSONField(default=dict)                    # {clip, loop_ms, camera, peak, still}
    library_version = models.PositiveIntegerField(default=1)
    retired = models.BooleanField(default=False)                  # dropped from the file; kept for old logs
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def dose_label(self, sets, reps=None, seconds=None):
        """'2 × 10–12', '3 × 40 s', with ' each side' for unilateral moves."""
        if seconds:
            body = f'{sets} × {seconds} s'
        else:
            reps = reps or self.default_reps or [10, 12]
            lo, hi = (reps[0], reps[-1]) if isinstance(reps, (list, tuple)) else (reps, reps)
            body = f'{sets} × {lo}–{hi}' if lo != hi else f'{sets} × {lo}'
        return body + (' each side' if self.unilateral else '')


class ProgramTemplate(models.Model):
    """
    Expert-written plan shape. ``phases`` is a list of
    {name, weeks: [from, to], days: {"0": {kind, name, blocks}, ...}}
    where block items name either a ``slot`` (filled by the builder) or an
    ``exercise`` id (hand-written templates).
    """
    slug = models.SlugField(unique=True, max_length=64)
    name = models.CharField(max_length=120)
    goal = models.CharField(max_length=16, default='general')     # fat_loss / recomp / lean_gain / general / strength
    setting = models.CharField(max_length=8, default='home')      # home / gym
    equipment_required = models.JSONField(default=list)
    level = models.PositiveSmallIntegerField(default=1)
    days_per_week = models.PositiveSmallIntegerField(default=3)
    session_minutes = models.PositiveSmallIntegerField(default=30)
    gentle = models.BooleanField(default=False)
    is_personal = models.BooleanField(default=False)              # hand-entered for one user, never offered
    phases = models.JSONField(default=list)

    def __str__(self):
        return self.name


# ── Per user ───────────────────────────────────────────────

class ProgramStatus(models.TextChoices):
    ACTIVE = 'active'
    PAUSED = 'paused'
    DONE = 'done'


class Program(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fitness_programs')
    habit = models.OneToOneField('board.Habit', on_delete=models.CASCADE, related_name='program')
    template = models.ForeignKey(ProgramTemplate, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    start_date = models.DateField()       # week 1 starts here; "repeat this week" shifts it by 7 days
    status = models.CharField(max_length=8, choices=ProgramStatus.choices, default=ProgramStatus.ACTIVE)
    overrides = models.JSONField(default=dict)   # user swaps that survive rebuilds: {"band_row": "band_seated_row"}
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user} - {self.name}'


class Phase(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='phases')
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)
    week_from = models.PositiveSmallIntegerField()    # 1-based, inclusive
    week_to = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['order', 'week_from']


class DayKind(models.TextChoices):
    SESSION = 'session'
    WALK = 'walk'
    REST = 'rest'


class DayTemplate(models.Model):
    """
    One weekday in a phase. ``blocks`` for a session:
    [{"block": "warmup"|"pair"|"circuit"|"single"|"cooldown", "rounds": 2,
      "rest_between": 30, "rest_after": 60,
      "items": [{"exercise": "band_squat", "reps": [10, 12]} | {"exercise": "arm_circles", "seconds": 40}]}]
    """
    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name='days')
    weekday = models.PositiveSmallIntegerField()      # Monday = 0
    kind = models.CharField(max_length=8, choices=DayKind.choices, default=DayKind.REST)
    name = models.CharField(max_length=60, blank=True, default='')   # "Full body", "Upper body"
    blocks = models.JSONField(default=list)

    class Meta:
        unique_together = ('phase', 'weekday')
        ordering = ['weekday']


class FitnessProfile(models.Model):
    """The onboarding answers and the targets computed from them (never typed by hand)."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='fitness_profile')
    answers = models.JSONField(default=list)          # versions: [{"v": 1, "at": iso, "answers": {...}}]
    health_flags = models.JSONField(default=list)     # ["knee", "heart"...]
    equipment = models.JSONField(default=list)
    setting = models.CharField(max_length=8, default='home')
    weight_kg = models.FloatField(null=True, blank=True)
    height_cm = models.FloatField(null=True, blank=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    sex = models.CharField(max_length=8, blank=True, default='')
    activity_level = models.CharField(max_length=8, blank=True, default='')   # sitting / some / most
    goal = models.CharField(max_length=16, blank=True, default='')
    why = models.CharField(max_length=200, blank=True, default='')            # shown at workout start
    targets = models.JSONField(default=dict)          # kcal, protein_g, water_ml, steps, sleep_h
    explanation = models.JSONField(default=dict)      # plain-English line per target
    track_calories = models.BooleanField(default=False)
    times = models.JSONField(default=dict)            # workout, wake, meals {breakfast...}, weigh_in_day
    rules_version = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def latest_answers(self):
        return (self.answers[-1] or {}).get('answers', {}) if self.answers else {}

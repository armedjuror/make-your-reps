"""Pomodoro focus mode: one run of the shared FocusPlayer in focus mode."""
from django.contrib.auth.models import User
from django.db import models


class FocusStatus(models.TextChoices):
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    ABANDONED = 'abandoned'


class FocusSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='focus_sessions')
    task = models.ForeignKey('board.Task', null=True, blank=True, on_delete=models.SET_NULL)
    habit = models.ForeignKey('board.Habit', null=True, blank=True, on_delete=models.SET_NULL)
    routine_entry = models.ForeignKey('board.RoutineEntry', null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=255, blank=True, default='')
    date = models.DateField()
    plan = models.JSONField(default=dict)             # {focus_min, break_min, long_break_min, cycles}
    steps = models.JSONField(default=list)
    state = models.JSONField(default=dict)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    completed_cycles = models.PositiveSmallIntegerField(default=0)
    interruptions = models.PositiveSmallIntegerField(default=0)
    parked = models.JSONField(default=list)           # thoughts parked to the inbox: [task ids]
    focus_minutes = models.PositiveIntegerField(default=0)
    xp = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=FocusStatus.choices, default=FocusStatus.IN_PROGRESS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_at']

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from board.models import Habit, HabitKind, UserDetail
from fitness.library import import_file
from fitness.models import FitnessProfile, ProgramTemplate
from fitness.plans import PERSONAL_TEMPLATES
from fitness.setup import ensure_fitness, install_program

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'exercises.json'
START = date(2026, 12, 1)                 # a Tuesday
WED = date(2026, 12, 2)                   # week 1 full body
TARGETS = {'kcal': 2350, 'protein_g': 122, 'water_ml': 2400, 'steps': 7000, 'sleep_h': [7, 8]}


def aware(d, h=10, m=0):
    return timezone.make_aware(datetime.combine(d, time(h, m)))


class FitnessBase(TestCase):
    today = WED

    def setUp(self):
        self.set_today(self.today)
        self.user = User.objects.create_user('ajwad', 'a@example.com', 'pw')
        self.detail = UserDetail.objects.create(user=self.user)
        self.client.force_login(self.user)
        import_file(FIXTURE)

    def set_today(self, d):
        if hasattr(self, '_now_patch'):
            self._now_patch.stop()
        self._now_patch = mock.patch('django.utils.timezone.now', return_value=aware(d))
        self._now_patch.start()
        self.addCleanup(lambda: self._now_patch.stop() if self._now_patch else None)
        self.today = d

    def install_plan(self, track_calories=False, start=START):
        spec = dict(PERSONAL_TEMPLATES['ajwad-bands-month'])
        phases = spec.pop('phases')()
        tpl = ProgramTemplate.objects.create(slug='ajwad-bands-month', phases=phases, is_personal=True, **spec)
        FitnessProfile.objects.create(user=self.user, targets=TARGETS, track_calories=track_calories,
                                      times={'weigh_in_day': 0})
        self.health, self.activity, self.trackers = ensure_fitness(self.user.id, TARGETS, track_calories)
        # Habits normally predate the day under test
        Habit.objects.filter(kind__in=[HabitKind.HEALTH, HabitKind.ACTIVITY]).update(
            created_at=aware(START - timedelta(days=7)))
        self.health.refresh_from_db()
        self.activity.refresh_from_db()
        self.program = install_program(self.activity, tpl, start)
        return self.program

    def steps(self, habit, d=None):
        r = self.client.get(f'/board/api/habits/{habit.id}/steps/' + (f'?date={d}' if d else ''))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['data']['steps']

    def tick(self, step_id, done=True, d=None):
        body = {'done': done}
        if d:
            body['date'] = d.isoformat()
        return self.client.put(f'/board/api/habit_steps/{step_id}/log/', json.dumps(body),
                               content_type='application/json')

    def log_metric(self, key, value):
        from board import metrics as mx
        return mx.log_entry(self.trackers[key] if key != 'sleep' else mx.ensure_sleep_metric(self.user.id),
                            value=value)

"""Rotating Activity subtasks: the expansion of today's DayTemplate in the active phase."""
from datetime import date, timedelta

from board.models import DayMode, DayPlan, HabitStep, HabitStepLog
from fitness.models import DayTemplate
from fitness.program import expand, preview, week_of

from .base import START, WED, FitnessBase


def names(items):
    return [i.name for i in items]


class ExpansionTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.install_plan()

    def test_before_start_and_after_end_are_empty(self):
        self.assertEqual(expand(self.activity, START - timedelta(days=1)), [])
        self.assertEqual(expand(self.activity, date(2027, 1, 4)), [])

    def test_weeks_are_calendar_weeks(self):
        self.assertEqual(week_of(self.program, START), 1)               # Tue 1 Dec
        self.assertEqual(week_of(self.program, date(2026, 12, 6)), 1)   # Sun
        self.assertEqual(week_of(self.program, date(2026, 12, 7)), 2)   # Mon

    def test_week_one_full_body(self):
        items = expand(self.activity, WED)
        self.assertEqual(names(items), [
            'Walk 7,000 steps', 'Band Squat', 'Band Face Pull', 'Band Chest Press', 'Dead Bug',
            'Band Romanian Deadlift', 'Band Row', "Finish today's workout"])
        self.assertEqual({i.target for i in items if i.key.startswith('ex:')}, {'2 × 10–12'})
        self.assertNotIn('ex:arm_circles', [i.key for i in items])   # warm-up is not a subtask

    def test_week_two_raises_reps(self):
        items = expand(self.activity, date(2026, 12, 7))
        self.assertEqual(items[1].target, '2 × 12–15')

    def test_weeks_three_and_four_split_upper_lower(self):
        upper = expand(self.activity, date(2026, 12, 14))
        lower = expand(self.activity, date(2026, 12, 15))
        self.assertIn('Band Lat Pulldown', names(upper))
        self.assertNotIn('Band Squat', names(upper))
        self.assertIn('Split Squat', names(lower))
        self.assertEqual(next(i for i in lower if i.key == 'ex:split_squat').target, '3 × 10–12 each side')
        self.assertEqual(expand(self.activity, date(2026, 12, 21))[1].target, '3 × 12–15')
        self.assertEqual(expand(self.activity, date(2026, 12, 28))[1].target, '3 × 12–15')   # week 5

    def test_walk_and_rest_days(self):
        self.assertEqual(names(expand(self.activity, START)), ['Walk 7,000 steps'])
        rest = expand(self.activity, date(2026, 12, 6))
        self.assertEqual([i.key for i in rest], ['rest'])
        self.assertTrue(rest[0].auto_done)

    def test_disrupted_session_day_becomes_a_short_walk(self):
        DayPlan.objects.create(user=self.user, date=WED, template='workday', mode=DayMode.DISRUPTED)
        self.assertEqual(names(expand(self.activity, WED)), ['Walk 20 min'])

    def test_steps_are_reused_across_days_by_key(self):
        self.steps(self.activity)                                   # Wed 2 Dec
        squat = HabitStep.objects.get(habit=self.activity, key='ex:band_squat')
        self.set_today(date(2026, 12, 15))
        data = self.steps(self.activity)
        self.assertEqual(next(s for s in data if s['key'] == 'ex:band_squat')['id'], squat.id)
        self.assertEqual(next(s for s in data if s['key'] == 'ex:band_squat')['target'], '3 × 10–12')
        self.assertEqual(HabitStep.objects.filter(habit=self.activity, key='ex:band_squat').count(), 1)

    def test_program_edit_takes_effect_immediately(self):
        day = DayTemplate.objects.get(phase__program=self.program, phase__week_from=1, weekday=2)
        day.blocks = [{'block': 'single', 'rounds': 3, 'items': [{'exercise': 'glute_bridge', 'reps': [12, 15]}]}]
        day.save()
        self.assertEqual(names(expand(self.activity, WED))[1:], ['Glute Bridge', "Finish today's workout"])

    def test_override_swaps_an_exercise(self):
        self.program.overrides = {'band_row': 'band_lat_pulldown'}
        self.program.save()
        keys = [i.key for i in expand(self.activity, WED)]
        self.assertIn('ex:band_lat_pulldown', keys)
        self.assertNotIn('ex:band_row', keys)

    def test_preview_writes_nothing(self):
        before = HabitStep.objects.count()
        days = preview(self.activity, START, 7)
        self.assertEqual(len(days), 7)
        self.assertEqual(HabitStep.objects.count(), before)

    def test_future_date_is_a_preview(self):
        r = self.client.get(f'/board/api/habits/{self.activity.id}/steps/?date=2026-12-04').json()['data']
        self.assertTrue(r['preview'])
        self.assertFalse(HabitStepLog.objects.exists())

    def test_generated_steps_cannot_be_edited(self):
        step_id = self.steps(self.activity)[0]['id']
        self.assertEqual(self.client.delete(f'/board/api/habit_steps/{step_id}/').status_code, 400)
        r = self.client.post(f'/board/api/habits/{self.activity.id}/steps/', {'name': 'x'})
        self.assertEqual(r.status_code, 400)

    def test_cannot_tick_a_step_from_another_day(self):
        self.steps(self.activity)                                    # creates the exercise steps
        self.set_today(date(2026, 12, 3))                            # walk day
        squat = HabitStep.objects.get(habit=self.activity, key='ex:band_squat')
        self.assertEqual(self.tick(squat.id).status_code, 400)

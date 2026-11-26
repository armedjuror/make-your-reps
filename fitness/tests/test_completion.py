"""Completion rules: linked trackers tick Health subtasks; a habit is done when every required subtask is."""
from datetime import date, timedelta

from board.models import HabitLog, HabitStepLog, UserDetail
from board.streaks import close_day, had_activity

from .base import WED, FitnessBase


def done(habit, d):
    log = HabitLog.objects.filter(habit=habit, date=d).first()
    return bool(log and log.is_done)


class HealthRulesTest(FitnessBase):
    today = date(2026, 12, 8)      # a Tuesday: no weigh-in subtask

    def setUp(self):
        super().setUp()
        self.install_plan()

    def by_key(self, habit):
        return {s['key']: s for s in self.steps(habit)}

    def test_health_subtasks_for_the_day(self):
        self.assertEqual(list(self.by_key(self.health)), ['water', 'protein', 'sleep'])
        self.set_today(date(2026, 12, 7))      # Monday adds the weigh-in
        self.assertEqual(list(self.by_key(self.health)), ['water', 'protein', 'sleep', 'weighin'])

    def test_water_ticks_at_target_and_unticks_on_undo(self):
        from board import metrics as mx
        self.log_metric('water', 2000)
        self.assertFalse(self.by_key(self.health)['water']['done'])
        self.log_metric('water', 500)
        step = self.by_key(self.health)['water']
        self.assertTrue(step['done'])
        self.assertTrue(step['auto'])
        mx.undo_last(self.trackers['water'], self.today)
        self.assertFalse(self.by_key(self.health)['water']['done'])

    def test_whole_habit_done_when_all_linked_rules_met(self):
        self.log_metric('water', 2400)
        self.log_metric('protein', 60)
        self.assertFalse(done(self.health, self.today))
        self.log_metric('protein', 62)
        self.log_metric('sleep', 7.5)
        self.assertTrue(done(self.health, self.today))

    def test_xp_awarded_once_when_done_today(self):
        before = UserDetail.objects.get(user=self.user).total_points
        self.log_metric('water', 2400)
        self.log_metric('protein', 122)
        self.log_metric('sleep', 8)
        self.log_metric('water', 250)          # already done: no second award
        self.assertGreater(UserDetail.objects.get(user=self.user).total_points, before)
        after = UserDetail.objects.get(user=self.user).total_points
        self.log_metric('protein', 10)
        self.assertEqual(UserDetail.objects.get(user=self.user).total_points, after)

    def test_sleep_below_seven_is_not_met(self):
        self.log_metric('sleep', 6.5)
        self.assertFalse(self.by_key(self.health)['sleep']['done'])

    def test_sleep_card_path_also_ticks(self):
        from board import metrics as mx
        mx.sync_sleep(self.user.id, self.today, 7)
        self.assertTrue(self.by_key(self.health)['sleep']['done'])

    def test_manual_tick_survives_rule_reevaluation(self):
        water = self.by_key(self.health)['water']
        self.assertEqual(self.tick(water['id']).status_code, 200)
        self.log_metric('water', 100)          # below target: the manual tick stays
        self.assertTrue(self.by_key(self.health)['water']['done'])

    def test_weigh_in_counts_any_log_that_week(self):
        self.set_today(date(2026, 12, 7))      # Monday
        self.assertFalse(self.by_key(self.health)['weighin']['done'])
        self.set_today(date(2026, 12, 9))      # weigh in on Wednesday instead
        self.log_metric('weight', 67.5)
        log = HabitStepLog.objects.get(step__habit=self.health, step__key='weighin', date=date(2026, 12, 7))
        self.assertTrue(log.done)

    def test_calories_within_ten_percent(self):
        self.health.delete()
        self.activity.delete()
        from board.models import Metric
        from fitness.models import FitnessProfile, ProgramTemplate
        Metric.objects.filter(domain='fitness').delete()
        FitnessProfile.objects.all().delete()
        ProgramTemplate.objects.all().delete()
        self.install_plan(track_calories=True)
        self.assertIn('kcal', self.by_key(self.health))
        self.log_metric('kcal', 1900)          # 19% under
        self.assertFalse(self.by_key(self.health)['kcal']['done'])
        self.log_metric('kcal', 300)           # 2,200: within 10% of 2,350
        self.assertTrue(self.by_key(self.health)['kcal']['done'])
        self.log_metric('kcal', 500)           # 2,700: 15% over
        self.assertFalse(self.by_key(self.health)['kcal']['done'])


class ActivityRulesTest(FitnessBase):
    today = WED

    def setUp(self):
        super().setUp()
        self.install_plan()

    def test_session_day_done_when_every_subtask_ticked(self):
        steps = self.steps(self.activity)
        self.log_metric('steps', 7200)                 # ticks the walk
        for s in steps:
            if s['key'] != 'walk':
                self.assertFalse(done(self.activity, WED))
                self.assertEqual(self.tick(s['id']).status_code, 200)
        self.assertTrue(done(self.activity, WED))
        self.tick(steps[1]['id'], done=False)
        self.assertFalse(done(self.activity, WED))

    def test_steps_tracker_is_overwritable_single_value(self):
        self.log_metric('steps', 5000)
        self.log_metric('steps', 7100)                 # one value per day, replaced
        walk = next(s for s in self.steps(self.activity) if s['key'] == 'walk')
        self.assertTrue(walk['done'])

    def test_rest_day_counts_as_done_even_unvisited(self):
        sunday = date(2026, 12, 6)
        self.set_today(sunday + timedelta(days=1))
        close_day(self.user.id, sunday)                # nightly close, app never opened on Sunday
        self.assertTrue(done(self.activity, sunday))
        # ...but a rest day alone is not activity for the global day streak
        self.assertFalse(had_activity(self.user.id, sunday))

    def test_walk_day_needs_the_walk(self):
        self.set_today(date(2026, 12, 3))
        self.assertEqual([s['key'] for s in self.steps(self.activity)], ['walk'])
        self.assertFalse(done(self.activity, self.today))
        self.log_metric('steps', 7000)
        self.assertTrue(done(self.activity, self.today))


class VisibilityTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.install_plan()

    def test_fitness_habits_hidden_from_habits_page(self):
        from board.models import Habit
        Habit.objects.create(user=self.user, habit='Read', identity='reader', frequency=[])
        names = [h['habit'] for h in self.client.get('/board/api/habits/').json()['data']]
        self.assertEqual(names, ['Read'])

    def test_fitness_trackers_hidden_from_trackers_page(self):
        names = {m['name'] for m in self.client.get('/board/api/metrics/').json()['data']}
        self.assertFalse(names & {'Water', 'Protein', 'Steps', 'Body weight', 'Waist'})
        fit = {m['name'] for m in self.client.get('/board/api/metrics/?domain=fitness').json()['data']}
        self.assertEqual(fit, {'Water', 'Protein', 'Steps', 'Body weight', 'Waist'})

    def test_overview(self):
        d = self.client.get('/board/api/fitness/overview/').json()['data']
        self.assertEqual(d['program']['week'], 1)
        self.assertEqual(d['activity']['day']['kind'], 'session')
        self.assertEqual(d['activity']['session']['exercise_count'], 6)
        self.assertEqual(len(d['preview']), 6)
        self.assertEqual(len(d['trackers']), 5)

    def test_calendar(self):
        days = self.client.get('/board/api/fitness/calendar/?month=2026-12').json()['data']['days']
        self.assertEqual(len(days), 31)
        self.assertEqual([d['kind'] for d in days[:7]],
                         ['walk', 'session', 'walk', 'session', 'walk', 'rest', 'session'])

    def test_exercise_detail(self):
        d = self.client.get('/board/api/fitness/exercises/band_squat/').json()['data']
        self.assertTrue(d['still'].endswith('fitness/stills/band_squat.png'))
        self.assertIsNone(d['animation']['clip_url'])          # clip not delivered yet
        self.assertEqual(d['animation']['side'], 'both')
        self.assertIn('youtube.com', d['video_url'])

    def test_other_users_cannot_see_steps(self):
        from django.contrib.auth.models import User
        other = User.objects.create_user('o', 'o@example.com', 'pw')
        UserDetail.objects.create(user=other)
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/board/api/habits/{self.activity.id}/steps/').status_code, 404)

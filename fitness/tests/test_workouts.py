"""Step lists, the workout player API, finish rules, progression, manual logging, focus mode, timeline items."""
import json
from datetime import date, timedelta
from unittest import mock

from board.models import (
    AccountabilityPartner, AccountabilityPartnerStatus, DailyData, DayMode, DayPlan, HabitLog, HabitStep,
    HabitStepLog, Task, TimelineEvent, UserDetail,
)
from fitness import workouts as wk
from fitness.models import Exercise, SessionStatus, SetLog, WorkoutSession
from fitness.steps import build_focus_steps, build_workout_steps, est_total, planned_sets

from .base import WED, FitnessBase, aware


def post(client, url, body=None):
    return client.post(url, json.dumps(body or {}), content_type='application/json')


def put(client, url, body=None):
    return client.put(url, json.dumps(body or {}), content_type='application/json')


class StepListTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.install_plan()
        self.lib = Exercise.objects.in_bulk()

    def day(self, d):
        from fitness.program import program_day
        return program_day(self.program, d)[1]

    def test_full_body_shape(self):
        steps = build_workout_steps(self.day(WED), self.lib)
        kinds = [s['kind'] for s in steps]
        self.assertEqual(steps[0]['title'], 'Arm Circles · warm-up')
        self.assertEqual(kinds[0], 'exercise_timed')
        # pair A: squat -> rest 30 -> face pull -> rest 60, twice
        self.assertEqual([s['title'] for s in steps[1:5]],
                         ['Band Squat · set 1 of 2', 'Rest', 'Band Face Pull · set 1 of 2', 'Rest'])
        self.assertEqual([s['est_seconds'] for s in (steps[2], steps[4])], [30, 60])
        self.assertEqual(steps[5]['title'], 'Band Squat · set 2 of 2')
        self.assertTrue(steps[5]['last_set'])
        self.assertNotEqual(kinds[-1], 'rest')
        self.assertEqual(len(planned_sets(steps)), 12)          # 6 exercises x 2

    def test_rep_sets_never_auto_advance_on_time(self):
        steps = build_workout_steps(self.day(WED), self.lib)
        for s in steps:
            if s['kind'] == 'exercise_set':
                self.assertEqual(s['advance'], 'manual_with_fallback')
                self.assertEqual(s['fallback_seconds'], round(s['est_seconds'] * 1.5))
            else:
                self.assertEqual(s['advance'], 'auto')

    def test_unilateral_switches_sides(self):
        steps = build_workout_steps(self.day(date(2026, 12, 15)), self.lib)     # lower: split squat
        i = next(i for i, s in enumerate(steps) if s.get('exercise_id') == 'split_squat')
        self.assertEqual([s['kind'] for s in steps[i:i + 3]], ['exercise_set', 'transition', 'exercise_set'])
        self.assertEqual([steps[i]['side'], steps[i + 2]['side']], ['right', 'left'])
        self.assertEqual(steps[i + 1]['title'], 'Switch sides')
        # Dead bug alternates in one clip: never split
        self.assertFalse(any(s.get('exercise_id') == 'dead_bug' and s.get('side') for s in steps))

    def test_next_preview(self):
        steps = build_workout_steps(self.day(WED), self.lib)
        self.assertEqual(steps[1]['next_preview'], 'Band Face Pull · 10–12 reps')
        self.assertIsNone(steps[-1]['next_preview'])

    def test_focus_steps(self):
        steps = build_focus_steps(25, 5, 4, 15)
        self.assertEqual([s['kind'] for s in steps], ['focus', 'break'] * 3 + ['focus'])
        self.assertEqual(est_total(steps), 4 * 25 * 60 + 3 * 5 * 60)
        long = build_focus_steps(25, 5, 6, 15)
        self.assertEqual(long[7]['title'], 'Long break')


class PlayerApiTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.install_plan()

    def start(self):
        r = post(self.client, '/board/api/fitness/workouts/start/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['data']

    def log(self, sid, ex, idx, reps=12, **kw):
        return post(self.client, f'/board/api/fitness/workouts/{sid}/sets/',
                    {'exercise': ex, 'set_index': idx, 'reps_done': reps, **kw}).json()

    def do_all_sets(self, data, reps=None, load=''):
        for s in data['steps']:
            if s['kind'] == 'exercise_set' and not s.get('warmup'):
                self.log(data['session']['id'], s['exercise_id'], s['set_index'],
                         reps=reps if reps is not None else s['target']['reps'][1], side=s.get('side', ''), load=load)

    def finish_after(self, sid, seconds, mode='finish'):
        self.set_now(aware(WED) + timedelta(seconds=seconds))
        return post(self.client, f'/board/api/fitness/workouts/{sid}/finish/', {'mode': mode}).json()['data']

    def set_now(self, dt):
        self._now_patch.stop()
        self._now_patch = mock.patch('django.utils.timezone.now', return_value=dt)
        self._now_patch.start()

    def test_start_and_resume(self):
        a = self.start()
        self.assertFalse(a['resumed'])
        self.assertEqual(a['meta']['exercise_count'], 6)
        self.assertIn('band_squat', a['meta']['exercises'])
        b = self.start()
        self.assertTrue(b['resumed'])
        self.assertEqual(a['session']['id'], b['session']['id'])
        self.assertEqual(self.client.get('/board/api/fitness/workouts/active/').json()['data']['session']['id'],
                         a['session']['id'])

    def test_no_workout_on_walk_day(self):
        self.set_today(date(2026, 12, 3))
        r = post(self.client, '/board/api/fitness/workouts/start/')
        self.assertEqual(r.status_code, 400)

    def test_state_saved_and_paused_timeout_abandons(self):
        d = self.start()
        sid = d['session']['id']
        put(self.client, f'/board/api/fitness/workouts/{sid}/state/', {'index': 3, 'paused': True})
        s = WorkoutSession.objects.get(pk=sid)
        self.assertEqual(s.state['index'], 3)
        self.assertIsNotNone(s.paused_at)
        self.set_now(aware(WED) + timedelta(minutes=31))
        self.assertIsNone(self.client.get('/board/api/fitness/workouts/active/').json()['data'])
        self.assertEqual(WorkoutSession.objects.get(pk=sid).status, SessionStatus.ABANDONED)

    def test_player_may_only_rewrite_steps_ahead(self):
        d = self.start()
        sid = d['session']['id']
        put(self.client, f'/board/api/fitness/workouts/{sid}/state/', {'index': 2})
        changed = [dict(s, title='X') for s in d['steps']]
        put(self.client, f'/board/api/fitness/workouts/{sid}/state/', {'steps': changed[:5]})
        s = WorkoutSession.objects.get(pk=sid)
        self.assertEqual(len(s.steps), 5)
        self.assertNotEqual(s.steps[0]['title'], 'X')     # already played: untouched
        self.assertEqual(s.steps[4]['title'], 'X')

    def test_sets_auto_tick_exercise_subtask(self):
        d = self.start()
        sid = d['session']['id']
        self.log(sid, 'band_squat', 1)
        step = HabitStep.objects.get(habit=self.activity, key='ex:band_squat')
        self.assertFalse(HabitStepLog.objects.filter(step=step, date=WED, done=True).exists())
        self.log(sid, 'band_squat', 2)
        log = HabitStepLog.objects.get(step=step, date=WED)
        self.assertTrue(log.done)
        self.assertEqual(log.source, 'workout')
        self.log(sid, 'band_squat', 2, skipped=True)          # changing a set back unticks
        self.assertFalse(HabitStepLog.objects.get(step=step, date=WED).done)

    def test_full_workout_completes_habit_and_awards_xp(self):
        d = self.start()
        sid = d['session']['id']
        self.log_metric('steps', 7000)
        self.do_all_sets(d)
        before = UserDetail.objects.get(user=self.user).total_points
        out = self.finish_after(sid, d['session']['est_seconds'])
        self.assertEqual(out['status'], 'completed')
        self.assertEqual(out['summary']['sets_done'], 12)
        self.assertEqual(out['xp'], 20 + 2 * 12)
        self.assertGreaterEqual(UserDetail.objects.get(user=self.user).total_points - before, 44)
        self.assertGreater(out['est_kcal'], 0)
        self.assertTrue(HabitLog.objects.get(habit=self.activity, date=WED).is_done)

    def test_too_fast_is_partial(self):
        d = self.start()
        self.do_all_sets(d)
        out = self.finish_after(d['session']['id'], d['session']['est_seconds'] * 0.3)
        self.assertEqual(out['status'], 'partial')
        self.assertEqual(out['xp'], 0)
        self.assertFalse(HabitLog.objects.filter(habit=self.activity, date=WED, is_done=True).exists())

    def test_partial_credit_threshold(self):
        d = self.start()
        sid = d['session']['id']
        sets = [s for s in d['steps'] if s['kind'] == 'exercise_set']
        for s in sets[:6]:                                    # exactly half of 12
            self.log(sid, s['exercise_id'], s['set_index'])
        out = self.finish_after(sid, d['session']['est_seconds'], mode='end')
        self.assertEqual(out['status'], 'completed')
        self.assertEqual(out['xp'], 20 + 2 * 6)

    def test_below_half_sets_is_partial_but_feeds_progression(self):
        d = self.start()
        sid = d['session']['id']
        self.log(sid, 'band_squat', 1)
        out = self.finish_after(sid, d['session']['est_seconds'], mode='end')
        self.assertEqual(out['status'], 'partial')
        self.assertTrue(SetLog.objects.filter(session_id=sid).exists())

    def test_partner_hears_about_a_finished_workout(self):
        from django.contrib.auth.models import User
        friend = User.objects.create_user('f', 'f@example.com', 'pw')
        AccountabilityPartner.objects.create(habit=self.activity, partner=friend,
                                             status=AccountabilityPartnerStatus.ACTIVE)
        d = self.start()
        self.do_all_sets(d)
        self.finish_after(d['session']['id'], d['session']['est_seconds'])
        ev = TimelineEvent.objects.get(user=friend, reference__model='WorkoutSession')
        self.assertIn('finished Full body', ev.event)

    def test_pr_and_progression(self):
        # Session 1 (Wed): all sets at the top of the range with the red band
        d = self.start()
        self.do_all_sets(d, load='red band')
        self.finish_after(d['session']['id'], d['session']['est_seconds'])
        # Session 2 (Fri): same again -> two sessions at reps_max with no rir -> go heavier
        self.set_today(date(2026, 12, 4))
        d2 = self.start()
        self.assertEqual(d2['meta']['last']['band_squat']['load'], 'red band')
        sid = d2['session']['id']
        r = self.log(sid, 'band_squat', 1, reps=12, load='green band')
        self.assertEqual(r['data']['pr'], 'Band Squat: first time at green band')
        self.do_all_sets(d2, load='red band')
        self.set_now(aware(date(2026, 12, 4)) + timedelta(seconds=d2['session']['est_seconds']))
        out = post(self.client, f'/board/api/fitness/workouts/{sid}/finish/').json()['data']
        self.assertEqual(out['summary']['suggestions']['band_row']['load'], 'green band')

    def test_reps_missed_twice_suggests_back_off(self):
        for day in (WED, date(2026, 12, 4)):
            self.set_today(day)
            d = self.start()
            self.do_all_sets(d, reps=6, load='green band')
            self.set_now(aware(day) + timedelta(seconds=d['session']['est_seconds']))
            out = post(self.client, f'/board/api/fitness/workouts/{d["session"]["id"]}/finish/').json()['data']
        self.assertEqual(out['summary']['suggestions']['band_squat'], {
            'type': 'down', 'exercise': 'band_squat', 'load': 'red band', 'text': 'Try red band next time'})

    def test_skip_today(self):
        self.assertEqual(post(self.client, '/board/api/fitness/workouts/skip/').status_code, 200)
        self.assertTrue(WorkoutSession.objects.filter(status=SessionStatus.SKIPPED, date=WED).exists())


class ManualLogTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.install_plan()

    def test_as_planned(self):
        r = post(self.client, '/board/api/fitness/workouts/log/', {'as_planned': True, 'start_time': '07:00',
                                                                   'duration_min': 30})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        self.assertEqual(d['status'], 'completed')
        self.assertEqual(d['source'], 'manual')
        self.assertEqual(SetLog.objects.filter(session_id=d['id']).count(), 12)
        self.assertTrue(HabitStepLog.objects.get(step__key='finish', date=WED).done)
        again = post(self.client, '/board/api/fitness/workouts/log/', {'as_planned': True})
        self.assertEqual(again.status_code, 400)

    def test_edits_and_past_days(self):
        self.set_today(date(2026, 12, 8))
        r = post(self.client, '/board/api/fitness/workouts/log/', {
            'date': '2026-12-07', 'as_planned': True, 'duration_min': 25,
            'sets': [{'exercise': 'band_squat', 'set_index': 2, 'reps_done': 9, 'load': 'red band'},
                     {'exercise': 'band_row', 'set_index': 2, 'skipped': True}]})
        self.assertEqual(r.status_code, 200, r.content)
        sid = r.json()['data']['id']
        self.assertEqual(SetLog.objects.get(session_id=sid, exercise_id='band_squat', set_index=2).reps_done, 9)
        self.assertTrue(SetLog.objects.get(session_id=sid, exercise_id='band_row', set_index=2).skipped)
        self.assertEqual(r.json()['data']['summary']['sets_done'], 11)
        too_old = post(self.client, '/board/api/fitness/workouts/log/', {'date': '2026-11-30'})
        self.assertEqual(too_old.status_code, 400)

    def test_plan_endpoint(self):
        d = self.client.get('/board/api/fitness/workouts/plan/').json()['data']
        self.assertEqual(len(d['rows']), 12)
        self.assertFalse(d['logged'])


class PainTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.install_plan()

    def test_knee_drops_or_regresses_affected_moves(self):
        r = post(self.client, '/board/api/fitness/pain/', {'joint': 'knee'})
        self.assertEqual(r.status_code, 200)
        # no safe regression among the placeholders, so both knee moves drop out
        self.assertEqual(r.json()['data']['changes'], {'band_squat': None, 'split_squat': None})
        from fitness.program import expand
        self.assertNotIn('ex:band_squat', [i.key for i in expand(self.activity, WED)])
        steps = wk.start_session(self.user.id)[0].steps
        self.assertFalse(any(s.get('exercise_id') == 'band_squat' for s in steps))


class FocusTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(user=self.user, task_name='Write the PRD')

    def test_full_focus_session(self):
        r = post(self.client, '/board/api/focus/sessions/', {'task': self.task.id, 'focus_min': 25, 'cycles': 2})
        d = r.json()['data']
        sid = d['session']['id']
        self.assertEqual(d['session']['title'], 'Write the PRD')
        self.assertEqual([s['kind'] for s in d['steps']], ['focus', 'break', 'focus'])
        post(self.client, f'/board/api/focus/sessions/{sid}/park/', {'text': 'call the bank'})
        post(self.client, f'/board/api/focus/sessions/{sid}/distracted/')
        put(self.client, f'/board/api/focus/sessions/{sid}/', {'index': 2})
        self._now_patch.stop()
        self._now_patch = mock.patch('django.utils.timezone.now', return_value=aware(WED) + timedelta(minutes=55))
        self._now_patch.start()
        put(self.client, f'/board/api/focus/sessions/{sid}/', {'index': 3})
        out = post(self.client, f'/board/api/focus/sessions/{sid}/finish/', {'tick': True}).json()['data']
        self.assertEqual(out['completed_cycles'], 2)
        self.assertEqual(out['interruptions'], 1)
        self.assertEqual(out['xp'], 20)
        self.assertEqual(out['focus_minutes'], 50)
        self.assertTrue(Task.objects.filter(task_name='call the bank', user=self.user).exists())
        self.assertTrue(Task.objects.get(pk=self.task.pk).is_done)
        self.assertEqual(DailyData.objects.get(user=self.user).focus_minutes, 50)

    def test_fast_forwarding_earns_nothing(self):
        d = post(self.client, '/board/api/focus/sessions/', {'cycles': 4}).json()['data']
        sid = d['session']['id']
        put(self.client, f'/board/api/focus/sessions/{sid}/', {'index': 7})   # skipped straight to the end
        out = post(self.client, f'/board/api/focus/sessions/{sid}/finish/').json()['data']
        self.assertEqual(out['xp'], 0)
        self.assertEqual(out['focus_minutes'], 0)


class TimelineTest(FitnessBase):
    def setUp(self):
        super().setUp()
        self.install_plan()

    def items(self, d):
        data = self.client.get(f'/board/api/timeline/?date={d}').json()['data']
        return {e['fit']['kind'] if 'fit' in e else None: e for e in data if e['event_type'] == 'fitness'}, \
            [e for e in data if e['event_type'] == 'fitness']

    def test_session_day(self):
        by_kind, all_ = self.items(WED)
        self.assertEqual(set(by_kind), {'workout', 'snack', 'meal', 'water', 'walk', 'weighin', 'bedtime'} - {'weighin'})
        self.assertTrue(by_kind['workout']['notify'])
        self.assertFalse(next(e for e in all_ if e['fit']['kind'] == 'meal')['notify'])
        self.assertIn('Full body', by_kind['workout']['event'])

    def test_rest_day_shows_only_walk_meals_water_bedtime(self):
        by_kind, _ = self.items(date(2026, 12, 6))
        self.assertEqual(set(by_kind), {'meal', 'water', 'walk', 'bedtime'})

    def test_disrupted_day_swaps_workout_for_a_short_walk(self):
        DayPlan.objects.create(user=self.user, date=WED, template='workday', mode=DayMode.DISRUPTED)
        by_kind, _ = self.items(WED)
        self.assertNotIn('workout', by_kind)
        self.assertEqual(by_kind['walk']['event'], 'Walk 20 min')

    def test_weigh_in_on_monday(self):
        self.set_today(date(2026, 12, 7))
        by_kind, _ = self.items(date(2026, 12, 7))
        self.assertIn('weighin', by_kind)

    def test_water_items_tick_from_the_tracker(self):
        _, all_ = self.items(WED)
        water = [e for e in all_ if e['fit']['kind'] == 'water']
        self.assertFalse(any(e['action_response'] for e in water))
        self.log_metric('water', 2900)                       # 2.4 L + 0.5 L on a workout day
        _, all_ = self.items(WED)
        self.assertTrue(all(e['action_response'] for e in all_ if e['fit']['kind'] == 'water'))

    def test_workout_item_done_after_finishing(self):
        wk.manual_log(self.user.id, WED)
        by_kind, _ = self.items(WED)
        self.assertEqual(by_kind['workout']['action_response'], {'done': True})

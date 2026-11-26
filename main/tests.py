import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from board.models import DayPlan, Habit, HabitLog, Journal, JournalEntry, Metric, MetricEntry, Task, UserDetail
from main import internal_metrics

PH = dict(POSTHOG_API_KEY='phc_test', POSTHOG_HOST='https://example.invalid')


def _user(name, days_ago=0, **kw):
    u = User.objects.create_user(name, f'{name}@x.com', 'pw', **kw)
    User.objects.filter(pk=u.pk).update(date_joined=timezone.now() - timedelta(days=days_ago))
    u.refresh_from_db()
    UserDetail.objects.get_or_create(user=u)
    return u


class TrackEndpointTests(TestCase):
    def setUp(self):
        self.user = _user('ana')

    def _post(self, body, login=True):
        if login:
            s = self.client.session
            s['user_id'] = self.user.id
            s.save()
        return self.client.post('/api/track/', json.dumps(body), content_type='application/json')

    def test_requires_login(self):
        self.assertEqual(self._post({'events': []}, login=False).status_code, 401)

    @override_settings(**PH)
    @mock.patch('main.analytics.get_client')
    def test_forwards_clean_events_only(self, get_client):
        res = self._post({'client': 'extension', 'events': [
            {'event': 'view_time', 'properties': {'view': 'pane:todos', 'kind': 'pane', 'seconds': 42.5, 'evil': 'x'}},
            {'event': 'ui_click', 'properties': {'action': 'Habits.showHabitModal', 'view': 'pane:home', 'count': 3}},
            {'event': 'ui_click', 'properties': {'action': '<script>', 'count': 3}},   # bad string dropped
            {'event': 'view_time', 'properties': {'view': 'pane:home', 'seconds': 99999}},  # out of range dropped
            {'event': 'not_allowed', 'properties': {}},
        ]})
        self.assertEqual(res.json()['accepted'], 4)
        calls = get_client.return_value.capture.call_args_list
        self.assertEqual(len(calls), 4)
        first = calls[0]
        self.assertEqual(first.args[0], 'view_time')
        self.assertEqual(first.kwargs['distinct_id'], str(self.user.id))
        self.assertEqual(first.kwargs['properties']['client'], 'extension')
        self.assertNotIn('evil', first.kwargs['properties'])
        self.assertNotIn('action', calls[2].kwargs['properties'])
        self.assertNotIn('seconds', calls[3].kwargs['properties'])

    def test_noop_without_key(self):
        self.assertEqual(self._post({'events': [{'event': 'app_opened'}]}).json()['accepted'], 0)


@override_settings(**PH)
class ServerEventTests(TestCase):
    def setUp(self):
        self.user = _user('bo')
        patcher = mock.patch('main.analytics.get_client')
        self.ph = patcher.start().return_value
        self.addCleanup(patcher.stop)

    def events(self):
        return [c.args[0] for c in self.ph.capture.call_args_list]

    def test_feature_events_without_user_text(self):
        with self.captureOnCommitCallbacks(execute=True):
            h = Habit.objects.create(user=self.user, habit='Secret habit', identity='x', frequency=[0, 1])
            log = HabitLog.objects.create(habit=h, date=timezone.localdate())  # pending: no event
        with self.captureOnCommitCallbacks(execute=True):
            log.is_done = True
            log.save()
            t = Task.objects.create(user=self.user, task_name='Private todo text')
        with self.captureOnCommitCallbacks(execute=True):
            t.is_done = True
            t.save()
            plan = DayPlan.objects.create(user=self.user, date=timezone.localdate(), template='workday')
        with self.captureOnCommitCallbacks(execute=True):
            plan.mode = 'light'
            plan.save()
        self.assertEqual(self.events(), ['habit_created', 'habit_logged', 'todo_created', 'todo_completed', 'day_mode_set'])
        dumped = json.dumps([c.kwargs['properties'] for c in self.ph.capture.call_args_list])
        self.assertNotIn('Secret', dumped)
        self.assertNotIn('Private', dumped)

    def test_signup_event_and_identify(self):
        with self.captureOnCommitCallbacks(execute=True):
            User.objects.create_user('cy', 'cy@x.com', 'pw')
        self.assertIn('user_signed_up', self.events())
        self.ph.set.assert_called()


class DbMetricsTests(TestCase):
    def setUp(self):
        cache.clear()
        today = timezone.now()
        self.admin = _user('admin', 40, is_staff=True, is_superuser=True)
        self.doer = _user('doer', 20)
        self.lurker = _user('lurker', 3)
        habit = Habit.objects.create(user=self.doer, habit='h', identity='i')
        for d in (0, 1, 8):
            HabitLog.objects.create(habit=habit, date=(today - timedelta(days=d)).date(), is_done=True)
            HabitLog.objects.filter(habit=habit, date=(today - timedelta(days=d)).date()).update(updated_at=today - timedelta(days=d))
        j = Journal.objects.create(user=self.doer, name='Journal')
        JournalEntry.objects.create(journal=j, date=today.date(), at=today, text='hi')
        m = Metric.objects.create(user=self.admin, name='Walk')
        MetricEntry.objects.create(metric=m, date=today.date(), at=today, value=1)
        # Signup-style seed todo for the lurker: must not count as activity
        Task.objects.bulk_create([Task(user=self.lurker, task_name='seed')])
        at = self.lurker.date_joined + timedelta(seconds=20)
        Task.objects.filter(user=self.lurker).update(created_at=at, updated_at=at)

    def test_counts_exclude_staff_and_seeds(self):
        db = internal_metrics.db_metrics(30)
        self.assertEqual(db['total_users'], 2)
        self.assertEqual(db['dau'], 1)
        self.assertEqual(db['mau'], 1)
        self.assertEqual(db['excluded'], 1)
        feats = {f['label']: f for f in db['features']}
        self.assertEqual(feats['Habits']['recent'], 1)
        self.assertEqual(feats['Todos']['ever'], 0)
        self.assertEqual(feats['Trackers']['ever'], 0)   # only the excluded admin used it

    def test_counts_with_staff(self):
        db = internal_metrics.db_metrics(30, include_staff=True)
        self.assertEqual(db['total_users'], 3)
        self.assertEqual(db['dau'], 2)


@override_settings(POSTHOG_PERSONAL_API_KEY='phx', POSTHOG_PROJECT_ID='1')
class DashboardViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = _user('root', 10, is_staff=True, is_superuser=True)

    def fake_hogql(self, sql):
        if 'count(DISTINCT if(' in sql:
            return [[2, 3, 4, 120.0]]
        if 'toDate(timestamp)' in sql:
            return [[timezone.localdate().isoformat(), 2, 30.0]]
        if "event = 'view_time'" in sql:
            return [['pane:home', 'pane', 3, 40, 90.0, 35.0], ['modal:habitModal', 'modal', 1, 4, 3.0, 40.0]]
        if "event = 'ui_click'" in sql:
            return [['Habits.showHabitModal', 12, 3, 'pane:home'], ['#rare', 1, 1, 'pane:todos']]
        if "event = 'app_opened'" in sql:
            return [['web', 3, 20], ['extension', 2, 50]]
        return [['habit_logged', 3, 40]]

    def test_requires_superuser(self):
        self.assertEqual(self.client.get('/internal/').status_code, 403)

    def test_renders_with_posthog(self):
        self.client.force_login(self.admin)
        with mock.patch.object(internal_metrics, '_hogql', side_effect=self.fake_hogql) as q:
            res = self.client.get('/internal/?days=90')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(q.call_count, 6)
        html = res.content.decode()
        for text in ('Feature adoption', 'pane:home', 'Habits.showHabitModal', 'Never clicked', 'extension'):
            self.assertIn(text, html)
        self.assertIn("NOT IN ('", q.call_args_list[0].args[0])   # staff excluded in HogQL too

    def test_posthog_failure_degrades(self):
        self.client.force_login(self.admin)
        with mock.patch.object(internal_metrics, '_hogql', side_effect=RuntimeError('boom')):
            res = self.client.get('/internal/')
        self.assertContains(res, 'PostHog query failed')
        self.assertContains(res, 'Feature adoption')

import json
from datetime import time, timedelta

from django.core import mail
from django.test import override_settings

from board.models import Habit, Task
from squads import core, items, limits, safety
from squads.models import Board, NotificationLog, NotificationPrefs, PushSubscription, UserPlan
from squads.notify import notify
from squads.tests.base import MON, SquadTestCase, at


class NotifyTests(SquadTestCase):
    def test_daily_cap_drops_lowest_priority_first(self):
        NotificationPrefs.objects.create(user=self.meera, daily_cap=4)
        for i in range(3):
            self.assertEqual(notify(self.meera, 'nudge', f'n{i}').status, 'sent' if i < 3 else 'dropped')
        self.assertEqual(notify(self.meera, 'recap', 'r').status, 'dropped')       # recap keeps 3 slots free
        self.assertEqual(notify(self.meera, 'reaction', 'x').status, 'dropped')    # reactions keep 2
        self.assertEqual(notify(self.meera, 'at_risk', 'a').status, 'sent')        # at-risk uses the last slot
        self.assertEqual(notify(self.meera, 'at_risk', 'b').status, 'dropped')
        self.assertEqual(notify(self.meera, 'added', 'c').status, 'sent')          # never capped

    def test_quiet_hours_queue_or_drop_stale(self):
        NotificationPrefs.objects.create(user=self.meera, quiet_start=time(22, 0), quiet_end=time(7, 0))
        self.travel(at(MON, 23))
        self.assertEqual(notify(self.meera, 'at_risk', 'a').status, 'dropped')     # stale: dropped, not delayed
        q = notify(self.meera, 'nudge', 'n')
        self.assertEqual(q.status, 'queued')
        self.assertEqual(q.deliver_after, at(MON + timedelta(days=1), 7))
        from squads.notify import deliver_queued
        deliver_queued(at(MON + timedelta(days=1), 7, 1))
        q.refresh_from_db()
        self.assertEqual(q.status, 'sent')

    def test_mute_silences_all_but_added(self):
        b = self.squad(self.meera)
        core.set_muted(b, self.meera.id, True)
        self.assertEqual(notify(self.meera, 'nudge', 'n', board=b).status, 'muted')
        self.assertEqual(notify(self.meera, 'added', 'a', board=b).status, 'sent')

    def test_email_fallback_for_time_sensitive_without_push(self):
        notify(self.meera, 'nudge', 'Arjun nudged you', 'Check in')
        self.assertEqual(mail.outbox[-1].subject, 'Arjun nudged you')
        before = len(mail.outbox)
        notify(self.meera, 'reaction', 'Someone reacted')
        self.assertEqual(len(mail.outbox), before)                               # not time-sensitive


@override_settings(OTP_PER_EMAIL_PER_HOUR=5, OTP_MAX_ATTEMPTS=5)
class OTPTests(SquadTestCase):
    def setUp(self):
        super().setUp()
        from unittest import mock
        p = mock.patch('main.signals.generate_daily_timeline.delay')   # onboarding job, no broker in tests
        p.start()
        self.addCleanup(p.stop)
    def code(self):
        return mail.outbox[-1].subject.split()[0]

    def post(self, url, body):
        return self.client.post(url, json.dumps(body), content_type='application/json')

    def test_sign_up_and_log_in_with_a_code(self):
        r = self.post('/auth/otp/request/', {'email': 'New.Person@Example.com'})
        self.assertEqual(r.status_code, 200)
        r = self.post('/auth/otp/verify/', {'email': 'new.person@example.com', 'code': self.code()})
        self.assertEqual(r.json()['data']['created'], True)
        self.assertEqual(self.client.get('/board/api/user_details/').status_code, 200)
        from main.models import EmailOTP
        self.assertNotIn(self.code(), EmailOTP.objects.first().code_hash)        # stored hashed

    def test_existing_google_account_is_the_same_account(self):
        self.post('/auth/otp/request/', {'email': 'MEERA@example.com'})
        r = self.post('/auth/otp/verify/', {'email': 'meera@example.com', 'code': self.code()})
        self.assertEqual(r.json()['data']['user_id'], self.meera.id)
        self.assertFalse(r.json()['data']['created'])

    def test_wrong_code_attempts_and_expiry(self):
        self.post('/auth/otp/request/', {'email': 'x@example.com'})
        for i in range(5):
            r = self.post('/auth/otp/verify/', {'email': 'x@example.com', 'code': '000000'})
            self.assertEqual(r.status_code, 400)
        r = self.post('/auth/otp/verify/', {'email': 'x@example.com', 'code': self.code()})
        self.assertEqual(r.status_code, 429)
        self.travel(self.now + timedelta(minutes=1))
        self.post('/auth/otp/request/', {'email': 'y@example.com'})
        self.travel(self.now + timedelta(minutes=11))
        r = self.post('/auth/otp/verify/', {'email': 'y@example.com', 'code': self.code()})
        self.assertIn('expired', r.json()['error'])

    def test_rate_limited_per_email(self):
        for i in range(5):
            self.travel(self.now + timedelta(seconds=31))
            self.assertEqual(self.post('/auth/otp/request/', {'email': 'z@example.com'}).status_code, 200)
        self.travel(self.now + timedelta(seconds=31))
        self.assertEqual(self.post('/auth/otp/request/', {'email': 'z@example.com'}).status_code, 429)

    def test_app_client_gets_a_refresh_token(self):
        self.post('/auth/otp/request/', {'email': 'app@example.com'})
        r = self.post('/auth/otp/verify/', {'email': 'app@example.com', 'code': self.code(), 'client_type': 'app'})
        self.assertIn('refresh_token', r.json()['data'])


@override_settings(HOSTED=True)
class LimitTests(SquadTestCase):
    def test_free_plan_blocks_second_squad_and_records_trigger(self):
        core.create_squad(self.arjun, name='One')
        with self.assertRaises(limits.LimitBlocked) as cm:
            core.create_squad(self.arjun, name='Two')
        self.assertEqual(cm.exception.trigger, 'squads_owned')
        self.assertEqual(UserPlan.objects.get(user=self.arjun).upgrade_trigger, 'squads_owned')

    def test_joining_is_never_limited_but_member_cap_blocks_adds(self):
        b = core.create_squad(self.arjun, name='One')
        inv = core.current_invite(b, self.arjun.id)
        for i in range(3):
            core.join_with_invite(inv.token, self.user(f'u{i}', f'U{i}'))
        with self.assertRaises(limits.LimitBlocked):
            core.join_with_invite(inv.token, self.meera)                      # 4 members on free

    def test_downgrade_freezes_extra_squads_and_owner_picks(self):
        UserPlan.objects.create(user=self.arjun, plan='pro')
        a = core.create_squad(self.arjun, name='A')
        b = core.create_squad(self.arjun, name='B')
        UserPlan.objects.filter(user=self.arjun).update(plan='free')
        frozen = limits.apply_downgrade(self.arjun, keep_board_id=b.id)
        self.assertEqual(frozen, [a.id])
        self.assertEqual(Board.objects.get(pk=a.id).status, 'read_only')    # nothing removed

    def test_lapse_has_a_seven_day_grace(self):
        UserPlan.objects.create(user=self.arjun, plan='pro', paid_until=self.now - timedelta(days=6))
        self.assertEqual(limits.plan_of(self.arjun), 'pro')
        UserPlan.objects.filter(user=self.arjun).update(paid_until=self.now - timedelta(days=8))
        self.assertEqual(limits.plan_of(self.arjun), 'free')

    @override_settings(HOSTED=False)
    def test_self_hosted_is_unlimited(self):
        for i in range(5):
            core.create_squad(self.arjun, name=f'S{i}')


class ApiTests(SquadTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.arjun)

    def api(self, method, url, body=None, user=None):
        if user:
            self.client.force_login(user)
        if method == 'get':
            r = self.client.get(url)
        else:
            r = getattr(self.client, method)(url, json.dumps(body or {}), content_type='application/json')
        return r.status_code, r.json() if r['Content-Type'].startswith('application/json') else r.content

    def test_create_squad_and_read_every_tab(self):
        code, res = self.api('post', '/squads/api/boards/', {
            'name': 'DSA grind', 'template': 'study',
            'habits': [{'habit': 'Solve 2 problems', 'is_core': True}],
            'tracker': {'name': 'Problems', 'unit': 'problems', 'goal': 500}})
        self.assertEqual(code, 201, res)
        bid = res['data']['id']
        for tab in ('', 'today/', 'heatmap/', 'leaderboard/', 'feed/', 'goals/', 'focus/', 'habits/', 'trackers/',
                    'todos/', 'members/', 'invite/', 'recap/'):
            code, res = self.api('get', f'/squads/api/boards/{bid}/{tab}')
            self.assertEqual(code, 200, (tab, res))
        code, res = self.api('get', '/squads/api/boards/')
        self.assertEqual(res['data'][0]['name'], 'DSA grind')
        code, res = self.api('get', f'/squads/api/boards/{bid}/today/', user=self.meera)
        self.assertEqual(code, 404)                                           # not a member

    def test_shared_and_assigned_todos_through_the_todo_api(self):
        b = self.squad(self.meera, self.kabir)
        code, res = self.api('post', f'/squads/api/boards/{b.id}/todos/',
                             {'task_name': 'Book the court', 'completion_mode': 'assigned', 'assignee': self.kabir.id})
        self.assertEqual(code, 201, res)
        tid = res['data']['id']
        shared = items.create_squad_todo(b, self.arjun.id, task_name='Pick a problem set')
        mine = [t['task_name'] for t in self.api('get', '/board/api/tasks/', user=self.meera)[1]['data']]
        self.assertIn('Pick a problem set', mine)
        self.assertNotIn('Book the court', mine)                              # assigned to Kabir
        code, _ = self.api('put', f'/board/api/tasks/{tid}/', {'is_done': True}, user=self.arjun)
        self.assertEqual(code, 404)                                           # not his: assigned to Kabir
        code, _ = self.api('put', f'/board/api/tasks/{tid}/', {'is_done': True}, user=self.kabir)
        self.assertEqual(code, 200)
        code, _ = self.api('put', f'/board/api/tasks/{shared.id}/', {'is_done': True}, user=self.meera)
        self.assertEqual(code, 200)
        self.assertEqual(Task.objects.get(pk=shared.id).completed_by, self.meera)
        code, _ = self.api('put', f'/board/api/tasks/{shared.id}/', {'board': Board.personal_for(self.meera).id},
                           user=self.meera)
        self.assertEqual(Task.objects.get(pk=shared.id).board, b)              # board is read-only

    def test_timeline_and_habit_list_show_the_squad_tag(self):
        b = self.squad(self.meera)
        habits = self.api('get', '/board/api/habits/', user=self.meera)[1]['data']
        self.assertEqual(habits[0]['squad']['name'], 'DSA grind')

    def test_reactions_one_per_user_per_item(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.meera, MON)
        fid = self.api('get', f'/squads/api/boards/{b.id}/feed/')[1]['data'][0]['id']
        self.api('post', f'/squads/api/boards/{b.id}/feed/{fid}/react/', {'emoji': '🔥'})
        self.api('post', f'/squads/api/boards/{b.id}/feed/{fid}/react/', {'emoji': '👏'})
        item = self.api('get', f'/squads/api/boards/{b.id}/feed/')[1]['data'][0]
        self.assertEqual(item['reactions']['counts'], {'👏': 1})
        code, _ = self.api('post', f'/squads/api/boards/{b.id}/feed/{fid}/react/', {'emoji': '💩'})
        self.assertEqual(code, 400)

    def test_core_change_via_api_is_scheduled_for_tomorrow(self):
        b = self.squad(self.meera, optional=('Revise',))
        h = Habit.objects.get(board=b, habit='Revise')
        code, res = self.api('patch', f'/squads/api/boards/{b.id}/habits/{h.id}/', {'is_core': True})
        self.assertEqual(code, 200)
        self.assertFalse(res['data']['is_core'])
        self.assertTrue(res['data']['pending_rule']['is_core'])
        code, _ = self.api('patch', f'/squads/api/boards/{b.id}/habits/{h.id}/', {'is_core': False}, user=self.meera)
        self.assertEqual(code, 403)

    def test_invite_page_and_join_flow(self):
        b = self.squad()
        token = core.current_invite(b, self.arjun.id).token
        self.client.logout()
        r = self.client.get(f'/j/{token}/')
        self.assertContains(r, 'Free to join')
        self.assertContains(r, 'og:image')
        self.assertContains(r, 'Continue with email')
        self.client.force_login(self.meera)
        r = self.client.post(f'/j/{token}/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(b.active_memberships().filter(user=self.meera).exists())
        self.assertEqual(self.client.get(f'/j/{token}/og.png')['Content-Type'], 'image/png')

    def test_block_report_and_export(self):
        self.befriend(self.arjun, self.meera)
        code, _ = self.api('post', '/squads/api/block/', {'user_id': self.meera.id})
        self.assertEqual(code, 200)
        from board.models import Friend
        self.assertFalse(Friend.objects.filter(user=self.arjun, friend=self.meera).exists())
        code, _ = self.api('post', '/squads/api/report/', {'target_type': 'user', 'target_id': self.meera.id,
                                                           'reason': 'spam'})
        self.assertEqual(code, 201)
        b = self.squad(self.kabir)
        self.travel(at(MON, 8))
        self.check_in(b, self.arjun, MON)
        r = self.client.get('/squads/api/export/?format=csv')
        self.assertIn(b'contribution', r.content)
        self.assertEqual(json.loads(self.client.get('/squads/api/export/').content)['squad_history'][0]['type'],
                         'contribution')

    def test_push_subscription_round_trip(self):
        sub = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'x', 'auth': 'y'}}
        self.assertEqual(self.api('post', '/squads/api/push/', sub)[0], 201)
        self.assertTrue(PushSubscription.objects.filter(user=self.arjun).exists())
        self.assertEqual(self.api('delete', '/squads/api/push/', sub)[0], 200)

    def test_feature_flag_turns_a_track_off(self):
        from main.models import Config
        Config.objects.create(key='flag_challenges', value='off')
        code, _ = self.api('get', '/squads/api/challenges/')
        self.assertEqual(code, 404)

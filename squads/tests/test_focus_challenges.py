from datetime import timedelta

from django.core import mail
from django.test import override_settings

from board.models import Habit, HabitLog, MetricEntry
from squads import challenges as ch_mod, core, focus, items
from squads.evaluator import evaluate_board_day
from squads.models import CalendarDelivery, ChallengeParticipant, Contribution, FeedItem, FocusSession
from squads.tests.base import MON, SquadTestCase, at


class FocusTests(SquadTestCase):
    def schedule(self, b, **kw):
        with self.captureOnCommitCallbacks(execute=True):
            return focus.schedule(b, self.arjun.id, start_at=at(MON, 7), block_minutes=50, blocks=2, **kw)

    def test_ics_request_update_and_cancel(self):
        b = self.squad(self.meera)
        s = self.schedule(b)
        self.assertEqual(len(mail.outbox), 2)
        ics = mail.outbox[0].attachments[0][1]
        self.assertIn('METHOD:REQUEST', ics)
        self.assertIn('STATUS:CONFIRMED', ics)
        self.assertIn(f'UID:{s.ics_uid}', ics)
        self.assertIn('SEQUENCE:0', ics)
        self.assertIn('/squads/focus/rsvp/', mail.outbox[0].alternatives[0][0])   # optional RSVP links
        with self.captureOnCommitCallbacks(execute=True):
            focus.edit(s, self.arjun.id, start_at=at(MON, 8))
        self.assertIn('SEQUENCE:1', mail.outbox[-1].attachments[0][1])
        with self.captureOnCommitCallbacks(execute=True):
            focus.cancel(s, self.arjun.id)
        last = mail.outbox[-1].attachments[0][1]
        self.assertIn('METHOD:CANCEL', last)
        self.assertIn('SEQUENCE:2', last)
        self.assertEqual(CalendarDelivery.objects.filter(session=s, channel='ics_email').count(), 2)

    def test_rsvp_link_round_trip(self):
        b = self.squad(self.meera)
        s = self.schedule(b)
        token = focus.rsvp_token(s, self.meera.id, 'yes')
        resp = self.client.get(f'/squads/focus/rsvp/{token}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(s.rsvps.get(user=self.meera).response, 'yes')

    def attend(self, s, user, minutes, start=None):
        t = start or s.start_at
        focus.heartbeat(s, user.id, now=t)
        for _ in range(0, minutes * 60, 60):
            t += timedelta(seconds=60)
            focus.heartbeat(s, user.id, now=t)

    def test_quorum_points_and_auto_log(self):
        b = self.squad(self.meera, self.kabir)
        study = Habit.objects.get(board=b)
        s = self.schedule(b, linked_habit=study)
        self.attend(s, self.arjun, 109)                     # stays for both blocks
        self.attend(s, self.meera, 50 + 10 + 40)            # 90 of 100 focus minutes: completed
        self.attend(s, self.kabir, 30)                      # leaves early
        late = self.user('late', 'Late')
        core._add_member(b, late.id)
        with self.assertRaises(focus.FocusError):     # late join closes when the first block ends
            focus.heartbeat(s, late.id, now=s.start_at + timedelta(minutes=51))
        focus.close(s, now=s.end_at + timedelta(minutes=1))
        s.refresh_from_db()
        self.assertTrue(s.quorum_met)
        done = {a.user_id: a.completed for a in s.attendance.all()}
        self.assertEqual(done, {self.arjun.id: True, self.meera.id: True, self.kabir.id: False})
        meera_copy = items.linked_copy(study, self.meera.id)
        self.assertTrue(HabitLog.objects.get(habit=meera_copy, date=MON).is_done)   # auto-logged
        self.travel(at(MON + timedelta(days=1), 11))
        evaluate_board_day(b, MON)
        self.assertEqual(Contribution.objects.get(board=b, user=self.meera, reason='focus').points, 15)
        self.assertEqual(Contribution.objects.get(board=b, user=self.arjun, reason='focus_host').points, 5)
        self.assertFalse(Contribution.objects.filter(board=b, user=self.kabir, reason='focus').exists())

    def test_solo_session_logs_without_points(self):
        b = self.squad(self.meera)
        s = self.schedule(b)
        self.attend(s, self.arjun, 109)
        focus.close(s, now=s.end_at + timedelta(minutes=1))
        self.assertTrue(FeedItem.objects.filter(board=b, text__startswith='Solo session').exists())
        self.travel(at(MON + timedelta(days=1), 11))
        evaluate_board_day(b, MON)
        self.assertFalse(Contribution.objects.filter(board=b, reason='focus').exists())

    def test_one_person_on_two_devices_counts_once(self):
        b = self.squad(self.meera)
        s = self.schedule(b)
        focus.heartbeat(s, self.arjun.id, now=s.start_at)
        focus.heartbeat(s, self.arjun.id, now=s.start_at + timedelta(seconds=30))
        self.assertEqual(s.attendance.count(), 1)


class ChallengeTests(SquadTestCase):
    start = at(MON - timedelta(days=2), 9)

    def test_streak_challenge_skip_then_drop_then_unofficial(self):
        ch = ch_mod.create_challenge(self.arjun, title='30 days of DSA', visibility='link', start_date=MON,
                                     days=5, skip_tokens=1)
        p = ch_mod.join(ch, self.meera)
        self.assertIsNotNone(p.habit)
        self.assertEqual(p.habit.board.type, 'personal')                       # lands in Today
        HabitLog.objects.create(habit=p.habit, date=MON, is_done=True)
        ch_mod.evaluate_participant(p, now=at(MON + timedelta(days=3), 11))   # day 2 missed: skip; day 3: drop
        p.refresh_from_db()
        self.assertEqual(p.days_done, 1)
        self.assertEqual(p.skips_used, 1)
        self.assertEqual(p.status, 'dropped')
        ch_mod.continue_unofficially(p)
        self.assertEqual(p.status, 'unofficial')

    def test_completion_card_and_percentile(self):
        ch = ch_mod.create_challenge(self.arjun, title='Walk', visibility='public', start_date=MON, days=2)
        p = ch_mod.join(ch, self.meera)
        q = ch_mod.join(ch, self.kabir)
        for d in (MON, MON + timedelta(days=1)):
            HabitLog.objects.create(habit=p.habit, date=d, is_done=True)
        ch_mod.evaluate_all(now=at(MON + timedelta(days=2), 11))
        p.refresh_from_db()
        q.refresh_from_db()
        self.assertEqual(p.status, 'completed')
        self.assertEqual(q.status, 'dropped')
        self.assertEqual(ch_mod.percentile(ch, p), 100)
        resp = self.client.get(f'/c/{ch.slug}/card/{p.id}/image.png')
        self.assertEqual(resp['Content-Type'], 'image/png')

    def test_ladder_target_climbs(self):
        ch = ch_mod.create_challenge(self.arjun, title='Pushups', kind='ladder', visibility='link', start_date=MON,
                                     days=3, item_name='Pushups', unit='reps', daily_target=10, ladder_step=5)
        p = ch_mod.join(ch, self.meera)
        MetricEntry.objects.create(metric=p.metric, date=MON, at=at(MON, 8), value=10)
        MetricEntry.objects.create(metric=p.metric, date=MON + timedelta(days=1), at=at(MON, 8), value=14)
        ch_mod.evaluate_participant(p, now=at(MON + timedelta(days=2), 11))
        p.refresh_from_db()
        self.assertEqual(p.days_done, 1)                   # day 2 needed 15
        self.assertEqual(p.status, 'dropped')

    def test_rules_lock_at_start_only_end_date_extends(self):
        ch = ch_mod.create_challenge(self.arjun, title='X', visibility='link', start_date=MON, days=5)
        self.travel(at(MON, 9))
        with self.assertRaises(ch_mod.ChallengeError):
            ch_mod.update_challenge(ch, self.arjun.id, {'skip_tokens': 3})
        ch_mod.update_challenge(ch, self.arjun.id, {'end_date': (MON + timedelta(days=10)).isoformat()})
        self.assertEqual(ch.days, 11)

    def test_late_join_rules_and_squad_visibility(self):
        b = self.squad(self.meera)
        ch = ch_mod.create_challenge(self.arjun, title='Squad only', start_date=MON, days=5, parent_board=b,
                                     join_deadline=MON + timedelta(days=1), late_join='ineligible')
        self.assertFalse(ch_mod.can_see(ch, self.kabir.id))
        with self.assertRaises(ch_mod.ChallengeError):
            ch_mod.join(ch, self.kabir)
        self.travel(at(MON + timedelta(days=1), 9))
        p = ch_mod.join(ch, self.meera)
        self.assertFalse(p.eligible)
        self.travel(at(MON + timedelta(days=2), 9))
        self.assertFalse(ch_mod.join_open(ch))

    def test_versus_team_scores(self):
        a = self.squad(self.meera)
        other = core.create_squad(self.kabir, name='Rivals')
        ch = ch_mod.create_challenge(self.arjun, title='Battle', kind='versus', visibility='link', start_date=MON,
                                     days=3, parent_board=a)
        ch_mod.enter_team(ch, a, self.arjun.id)
        ch_mod.enter_team(ch, other, self.kabir.id)
        scores = {t['name']: t['members'] for t in ch_mod.team_scores(ch)}
        self.assertEqual(scores, {'DSA grind': 2, 'Rivals': 1})

    def test_discover_and_public_page_without_account(self):
        ch = ch_mod.create_challenge(self.arjun, title='Public walk', visibility='public', start_date=MON, days=7)
        soon, popular = ch_mod.discover(today=MON - timedelta(days=1))
        self.assertIn(ch, soon)
        resp = self.client.get(f'/c/{ch.slug}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Public walk')
        self.assertNotContains(resp, 'arjun@example.com')          # display names only

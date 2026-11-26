from datetime import timedelta

from django.core import mail

from board.models import Habit, Metric, MetricEntry
from squads import core, items
from squads.models import Board, BoardMembership, Contribution, Event, Invite, SquadGoal
from squads.tests.base import MON, SquadTestCase, at


class CreateAndJoinTests(SquadTestCase):
    def test_create_from_template_prefills_editable_items(self):
        t = items.template_suggestions('study')
        b = core.create_squad(self.arjun, name='DSA grind', template='study', habits=t['habits'][:1],
                              tracker=t['tracker'])
        self.assertEqual(b.emoji, '📚')
        self.assertEqual(Habit.objects.filter(board=b).count(), 1)   # one suggestion removed before saving
        self.assertTrue(SquadGoal.objects.filter(board=b, target=500).exists())
        self.assertEqual(BoardMembership.objects.get(board=b).role, 'owner')
        self.assertTrue(Event.objects.filter(name='squad_created').exists())

    def test_invite_link_expires_in_seven_days_and_can_be_revoked(self):
        b = self.squad()
        inv = core.current_invite(b, self.arjun.id)
        self.assertAlmostEqual((inv.expires_at - self.now).days, 7)
        core.revoke_invites(b, self.arjun.id)
        with self.assertRaises(core.SquadError):
            core.join_with_invite(inv.token, self.meera)
        self.travel(self.now + timedelta(days=8))
        inv2 = core.current_invite(b, self.arjun.id)
        self.assertNotEqual(inv.token, inv2.token)

    def test_joining_materialises_linked_copies_and_offers_overlaps(self):
        b = self.squad(core=('Solve 2 problems', 'Read'))
        mine = Habit.objects.create(user=self.meera, habit='solve 2 Problems', identity='x')
        inv = core.current_invite(b, self.arjun.id)
        m, overlaps = core.join_with_invite(inv.token, self.meera)
        self.assertEqual([o['personal_item'] for o in overlaps], [mine.id])
        read = Habit.objects.get(board=b, habit='Read')
        self.assertIsNotNone(items.linked_copy(read, self.meera.id))
        solve = Habit.objects.get(board=b, habit='Solve 2 problems')
        self.assertIsNone(items.linked_copy(solve, self.meera.id))   # waits for her choice
        items.resolve_overlap(b, self.meera.id, 'habit', solve.id, mine.id, 'link')
        self.assertEqual(items.linked_copy(solve, self.meera.id), mine)
        self.assertEqual(items.find_overlaps(b, self.meera.id), [])

    def test_adopt_and_separate(self):
        b = self.squad()
        solve = Habit.objects.get(board=b)
        mine = Habit.objects.create(user=self.meera, habit='Solve 2 problems', identity='x', detail='mine')
        core._add_member(b, self.meera.id)
        items.resolve_overlap(b, self.meera.id, 'habit', solve.id, mine.id, 'separate')
        copy = items.linked_copy(solve, self.meera.id)
        self.assertNotEqual(copy, mine)
        mine.refresh_from_db()
        self.assertIsNone(mine.linked_squad_habit)

    def test_direct_add_needs_accepted_friendship_and_shows_stay_leave(self):
        b = self.squad()
        with self.assertRaises(core.SquadError):
            core.add_friend_directly(b, self.arjun.id, self.kabir.id)
        self.befriend(self.arjun, self.kabir)
        m = core.add_friend_directly(b, self.arjun.id, self.kabir.id)
        self.assertTrue(m.added_directly and not m.add_acknowledged)
        self.assertTrue(any('added you' in e.subject for e in mail.outbox))   # push + email
        core.acknowledge_add(b, self.kabir.id, stay=False)
        m.refresh_from_db()
        self.assertEqual(m.status, 'left')

    def test_blocked_user_cannot_be_added(self):
        from squads import safety
        b = self.squad()
        self.befriend(self.arjun, self.kabir)
        safety.block(self.kabir.id, self.arjun.id)
        with self.assertRaises(core.SquadError):
            core.add_friend_directly(b, self.arjun.id, self.kabir.id)

    def test_members_suggest_and_admins_approve(self):
        b = self.squad(self.meera)
        self.befriend(self.meera, self.kabir)
        s = core.suggest_friend(b, self.meera.id, self.kabir.id)
        with self.assertRaises(core.SquadError):
            core.decide_suggestion(b, self.meera.id, s.id, True)
        core.decide_suggestion(b, self.arjun.id, s.id, True)
        self.assertTrue(BoardMembership.objects.filter(board=b, user=self.kabir, status='active').exists())


class MembershipTests(SquadTestCase):
    def test_owner_leaving_hands_over_and_contributions_stay(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.arjun, MON)
        core.leave(b, self.arjun.id)
        b.refresh_from_db()
        self.assertEqual(b.owner, self.meera)
        self.assertTrue(Contribution.objects.filter(board=b, user=self.arjun).exists())
        self.assertEqual(items.member_label(b, self.arjun), 'Former member')
        copy = Habit.objects.get(user=self.arjun, linked_squad_habit__board=b)   # personal link stays
        self.assertEqual(copy.board.type, 'personal')

    def test_delete_needs_the_name_and_keeps_personal_copies(self):
        b = self.squad(self.meera)
        with self.assertRaises(core.SquadError):
            core.delete_squad(b, self.arjun.id, 'wrong')
        with self.assertRaises(core.SquadError):
            core.delete_squad(b, self.meera.id, 'DSA grind')
        core.delete_squad(b, self.arjun.id, 'DSA grind')
        self.assertFalse(Board.objects.filter(pk=b.pk).exists())
        self.assertTrue(Habit.objects.filter(user=self.meera, habit='Solve 2 problems').exists())

    def test_archive_is_read_only(self):
        from squads.scoping import can_edit, can_log
        b = self.squad(self.meera)
        core.archive(b, self.arjun.id)
        self.assertFalse(can_edit(b, self.arjun.id))
        self.assertFalse(can_log(b, self.meera.id))
        self.travel(at(MON, 8))
        self.check_in(b, self.meera, MON)
        self.assertFalse(Contribution.objects.filter(board=b).exists())

    def test_account_deletion_keeps_totals_as_former_member(self):
        from squads.safety import anonymise_user
        b = self.squad(self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.arjun, MON)
        self.check_in(b, self.meera, MON)
        total = Contribution.objects.filter(board=b).count()
        anonymise_user(self.arjun)
        self.arjun.delete()
        b.refresh_from_db()
        self.assertEqual(b.owner, self.meera)                       # the squad survives its owner
        self.assertEqual(Contribution.objects.filter(board=b).count(), total)
        self.assertEqual(Contribution.objects.filter(board=b, user__isnull=True).first().member_label, 'Former member')


class GoalTests(SquadTestCase):
    def test_tracker_logs_feed_the_goal_with_pace_and_late_join_share(self):
        from squads.serializers import goal_dict
        b = core.create_squad(self.arjun, name='Fit', template='fitness',
                              tracker={'name': 'Minutes', 'unit': 'min', 'goal': 1000,
                                       'period_end': MON + timedelta(days=9)})
        core.join_with_invite(core.current_invite(b, self.arjun.id).token, self.meera)
        squad_metric = Metric.objects.get(board=b)
        self.travel(at(MON, 8))
        for u, v in ((self.arjun, 60), (self.meera, 40)):
            copy = items.linked_copy(squad_metric, u.id)
            MetricEntry.objects.create(metric=copy, date=MON, at=self.now, value=v)
        g = goal_dict(SquadGoal.objects.get(board=b), MON)
        self.assertEqual(g['total'], 100)
        self.assertEqual(g['pace_per_day'], 90.0)    # 900 left over 10 days
        self.assertEqual({s['name']: s['value'] for s in g['shares']}, {'Arjun': 60.0, 'Meera': 40.0})
        entry = MetricEntry.objects.filter(metric__user=self.meera).first()
        entry.value = 10
        entry.save()                                  # an edit appends a reversal and a new row
        self.assertEqual(goal_dict(SquadGoal.objects.get(board=b), MON)['total'], 70)

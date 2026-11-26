from datetime import timedelta

from board.models import DayPlan, Habit
from squads import core, items
from squads.evaluator import day_snapshot, evaluate_board_day
from squads.models import Contribution, DayResult, DayStatus, LeaderboardWeek, Nudge, SquadStreak
from squads.tests.base import MON, SquadTestCase, at


def points(board, user):
    return sum(c.points for c in Contribution.objects.filter(board=board, user=user))


class LedgerTests(SquadTestCase):
    def test_linked_log_writes_one_contribution_and_undo_appends_a_reversal(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.meera, MON)
        rows = Contribution.objects.filter(board=b, user=self.meera, reason='checkin')
        self.assertEqual(rows.count(), 1)
        self.check_in(b, self.meera, MON, done=False)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(sum(r.value for r in rows), 0)
        self.assertTrue(rows.filter(reversal_of__isnull=False).exists())

    def test_log_after_midnight_is_late_and_after_cutoff_is_ignored(self):
        b = self.squad(self.meera)
        self.travel(at(MON + timedelta(days=1), 9, 30))     # before the 10:00 cutoff
        log = self.check_in(b, self.meera, MON)
        log.refresh_from_db()
        self.assertTrue(log.late)
        self.assertTrue(Contribution.objects.get(board=b, user=self.meera, reason='checkin').late)
        self.travel(at(MON + timedelta(days=2), 11))         # the day after closed
        self.check_in(b, self.meera, MON + timedelta(days=1))
        self.assertEqual(Contribution.objects.filter(board=b, user=self.meera, reason='checkin').count(), 1)

    def test_one_log_counts_for_member_and_squad(self):
        b = self.squad(self.meera)
        copy = items.linked_copy(Habit.objects.get(board=b), self.meera.id)
        self.assertEqual(copy.board.type, 'personal')
        self.assertEqual(copy.user, self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.meera, MON)
        self.assertEqual(copy.habitlog_set.filter(is_done=True).count(), 1)
        self.assertEqual(day_snapshot(b, MON)['states'][self.meera.id][0], 'in')


class StreakTests(SquadTestCase):
    def test_two_members_both_in_survive_and_score(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.arjun, MON)
        self.travel(at(MON, 9))
        self.check_in(b, self.meera, MON)
        self.travel(at(MON + timedelta(days=1), 10, 5))
        r = evaluate_board_day(b, MON)
        self.assertEqual(r.status, DayStatus.SURVIVED)
        self.assertEqual(SquadStreak.objects.get(board=b).current, 1)
        self.assertEqual(points(b, self.arjun), 15)          # core 10 + survived 5
        self.assertEqual(points(b, self.meera), 20)          # + streak saver 5: her check-in crossed 100%

    def test_two_member_squad_needs_everyone(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.arjun, MON)
        self.travel(at(MON + timedelta(days=1), 11))
        self.assertEqual(evaluate_board_day(b, MON).status, DayStatus.BELOW)
        self.assertEqual(points(b, self.arjun), 10)          # own core check-in still counts

    def test_three_members_need_seventy_percent_and_a_miss_breaks_the_streak(self):
        b = self.squad(self.meera, self.kabir)
        self.travel(at(MON, 8))
        for u in (self.arjun, self.meera):
            self.check_in(b, u, MON)
        self.travel(at(MON + timedelta(days=1), 11))
        self.assertEqual(evaluate_board_day(b, MON).status, DayStatus.BELOW)   # 2/3 = 67% < 70%
        day2 = MON + timedelta(days=1)
        for u in (self.arjun, self.meera, self.kabir):
            self.check_in(b, u, day2)
        self.travel(at(day2 + timedelta(days=1), 11))
        self.assertEqual(evaluate_board_day(b, day2).status, DayStatus.SURVIVED)
        day3 = day2 + timedelta(days=1)
        self.check_in(b, self.arjun, day3)
        self.travel(at(day3 + timedelta(days=1), 11))
        self.assertEqual(evaluate_board_day(b, day3).status, DayStatus.BROKEN)
        self.assertEqual(SquadStreak.objects.get(board=b).current, 0)
        self.assertEqual(SquadStreak.objects.get(board=b).best, 1)

    def test_away_and_off_day_are_not_counted_light_day_counts_as_in(self):
        b = self.squad(self.meera, self.kabir)
        core.set_away(b, self.kabir.id, MON + timedelta(days=3), from_day=MON)
        DayPlan.objects.create(user=self.meera, date=MON, template='workday', mode='light', source='manual')
        self.travel(at(MON, 8))
        self.check_in(b, self.arjun, MON)
        snap = day_snapshot(b, MON)
        self.assertEqual(snap['states'][self.kabir.id][0], 'away')
        self.assertEqual(snap['states'][self.meera.id][0], 'in')
        self.assertEqual(len(snap['counted']), 2)
        DayPlan.objects.create(user=self.arjun, date=MON + timedelta(days=1), template='workday', mode='disrupted',
                               source='travel', reason='Travelling')
        self.assertEqual(day_snapshot(b, MON + timedelta(days=1))['states'][self.arjun.id][0], 'off')

    def test_first_day_does_not_count_against_the_squad(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 15))
        inv = core.current_invite(b, self.arjun.id)
        core.join_with_invite(inv.token, self.kabir)
        self.check_in(b, self.arjun, MON)
        self.check_in(b, self.meera, MON)
        self.travel(at(MON + timedelta(days=1), 11))
        r = evaluate_board_day(b, MON)
        self.assertEqual(r.details[str(self.kabir.id)], 'first_day')
        self.assertEqual(r.members_counted, 2)
        self.assertEqual(r.status, DayStatus.SURVIVED)

    def test_evaluation_waits_for_the_cutoff_and_is_idempotent(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 8))
        self.check_in(b, self.arjun, MON)
        self.check_in(b, self.meera, MON)
        done = self.evaluate(b, at(MON + timedelta(days=1), 9, 59))
        self.assertFalse(DayResult.objects.filter(board=b, day=MON).exists())
        done = self.evaluate(b, at(MON + timedelta(days=1), 10, 1))
        self.assertTrue(DayResult.objects.get(board=b, day=MON).survived)
        before = Contribution.objects.count()
        self.evaluate(b, at(MON + timedelta(days=1), 10, 20))
        self.assertIsNone(evaluate_board_day(b, MON))
        self.assertEqual(Contribution.objects.count(), before)

    def test_one_member_squad_has_no_streak(self):
        from squads.evaluator import evaluate_board
        b = self.squad()
        self.check_in(b, self.arjun, MON)
        self.assertEqual(evaluate_board(b, at(MON + timedelta(days=3), 11)), [])

    def test_core_change_applies_from_next_day(self):
        b = self.squad(self.meera, core=('Solve 2 problems',), optional=('Revise notes',))
        revise = Habit.objects.get(board=b, habit='Revise notes')
        self.travel(at(MON, 8))
        items.schedule_habit_rule(revise, is_core=True)
        self.assertFalse(items.rule_for(revise, MON)['is_core'])
        self.assertTrue(items.rule_for(revise, MON + timedelta(days=1))['is_core'])
        for u in (self.arjun, self.meera):
            self.check_in(b, u, MON)
        self.travel(at(MON + timedelta(days=1), 11))
        self.assertEqual(evaluate_board_day(b, MON).status, DayStatus.SURVIVED)   # Revise not core yet
        day2 = MON + timedelta(days=1)
        for u in (self.arjun, self.meera):
            self.check_in(b, u, day2)
        self.travel(at(day2 + timedelta(days=1), 11))
        self.assertEqual(evaluate_board_day(b, day2).status, DayStatus.BROKEN)    # now it is core
        revise.refresh_from_db()
        self.assertTrue(revise.is_core)

    def test_core_habits_cannot_be_opted_out(self):
        b = self.squad(self.meera, optional=('Revise notes',))
        with self.assertRaises(ValueError):
            items.opt_out(b, self.meera.id, Habit.objects.get(board=b, habit='Solve 2 problems').id)
        items.opt_out(b, self.meera.id, Habit.objects.get(board=b, habit='Revise notes').id)
        self.assertIsNone(items.linked_copy(Habit.objects.get(board=b, habit='Revise notes'), self.meera.id))


class NudgeAndLeaderboardTests(SquadTestCase):
    def test_nudge_rules_and_conversion_points(self):
        b = self.squad(self.meera)
        self.travel(at(MON, 18))
        with self.assertRaises(core.SquadError):
            core.nudge(b, self.arjun.id, self.meera.id)           # check in first
        self.check_in(b, self.arjun, MON)
        core.nudge(b, self.arjun.id, self.meera.id)
        with self.assertRaises(core.SquadError):
            core.nudge(b, self.arjun.id, self.meera.id)           # one per pair per day
        self.travel(at(MON, 19))
        self.check_in(b, self.meera, MON)
        self.assertIsNotNone(Nudge.objects.get(board=b).converted_at)
        self.travel(at(MON + timedelta(days=1), 11))
        evaluate_board_day(b, MON)
        self.assertEqual(Contribution.objects.get(board=b, user=self.arjun, reason='nudge').points, 3)

    def test_weekly_leaderboard_and_mvp_after_sunday(self):
        b = self.squad(self.meera)
        for i in range(7):
            d = MON + timedelta(days=i)
            self.travel(at(d, 8))
            self.check_in(b, self.arjun, d)
            self.travel(at(d, 9))
            self.check_in(b, self.meera, d)
        self.evaluate(b, at(MON + timedelta(days=7), 11))
        rows = {r.user_id: r for r in LeaderboardWeek.objects.filter(board=b, week_start=MON)}
        self.assertEqual(rows[self.meera.id].points, 7 * 20)
        self.assertTrue(rows[self.meera.id].is_mvp)
        self.assertFalse(rows[self.arjun.id].is_mvp)
        self.assertEqual(SquadStreak.objects.get(board=b).current, 7 + 0)   # this week's 7 days

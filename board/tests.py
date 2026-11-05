from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from board import metrics as mx
from board.days import resolve_day
from board.models import (
    BlockLog, DayPlan, DaySummary, Habit, HabitLog, Metric, MetricEntry, RoutineEntry, Tier,
    UserDetail,
)
from board.streaks import StreakContext, close_day, close_pending_days, compute_global_streak, habit_streaks

TODAY = date(2026, 11, 5)   # a Thursday
NOW = timezone.make_aware(datetime(2026, 11, 5, 10, 0))


def at(h, m=0, day=TODAY):
    return timezone.make_aware(datetime.combine(day, time(h, m)))


class Base(TestCase):
    def setUp(self):
        patcher = mock.patch('django.utils.timezone.now', return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user('ajwad', 'a@example.com', 'pw')
        self.other = User.objects.create_user('other', 'o@example.com', 'pw')
        self.detail = UserDetail.objects.create(user=self.user)
        UserDetail.objects.create(user=self.other)
        self.client.force_login(self.user)

    def entry(self, title, hh, mm=0, tier=Tier.ANCHOR, rtype='workday', fixed=False, user=None,
              old=True, **kw):
        e = RoutineEntry.objects.create(
            user=user or self.user, routine_type=rtype, title=title, time=time(hh, mm),
            tier=tier, fixed_time=fixed, **kw)
        if old:   # auto_now_add stamps the frozen NOW; a routine block normally predates today
            RoutineEntry.objects.filter(pk=e.pk).update(created_at=NOW - timedelta(days=30))
            e.refresh_from_db()
        return e

    def habit(self, created_at=None, **kw):
        h = Habit.objects.create(**kw)
        Habit.objects.filter(pk=h.pk).update(created_at=created_at or NOW - timedelta(days=30))
        h.refresh_from_db()
        return h

    def routine(self):
        self.wake = self.entry('Wake', 5, tier=Tier.ESSENTIAL, fixed=True)
        self.dsa = self.entry('DSA', 7, tier=Tier.ANCHOR)
        self.read = self.entry('Reading', 8, tier=Tier.FLEXIBLE)
        self.office = self.entry('Office', 9, 30, tier=Tier.ESSENTIAL, fixed=True)
        self.game = self.entry('Games', 12, tier=Tier.FLEXIBLE)

    def log(self, entry, status, day=TODAY):
        return BlockLog.objects.create(user=self.user, date=day, entry=entry, title=entry.title,
                                       scheduled_time=entry.time, tier=entry.tier, status=status)


class ResolveDayTests(Base):
    def test_default_follows_weekday_rule_and_normal_mode(self):
        r = resolve_day(self.user, TODAY, now=NOW)
        self.assertEqual((r['template'], r['mode'], r['is_default']), ('workday', 'normal', True))
        sat = resolve_day(self.user, date(2026, 11, 7), now=NOW)
        self.assertEqual(sat['template'], 'holiday')

    def test_weekend_days_are_a_user_setting(self):
        self.detail.weekend_days = [4, 5]
        self.detail.save()
        self.assertEqual(resolve_day(self.user, date(2026, 11, 6), now=NOW)['template'], 'holiday')
        self.assertEqual(resolve_day(self.user, date(2026, 11, 8), now=NOW)['template'], 'workday')

    def test_modes_show_the_right_tiers(self):
        self.routine()
        titles = lambda r: [b['title'] for b in r['blocks']]
        self.assertEqual(len(titles(resolve_day(self.user, TODAY, now=NOW))), 5)
        DayPlan.objects.create(user=self.user, date=TODAY, template='workday', mode='light')
        self.assertEqual(titles(resolve_day(self.user, TODAY, now=NOW)), ['Wake', 'DSA', 'Office'])
        DayPlan.objects.filter(user=self.user).update(mode='disrupted')
        self.assertEqual(titles(resolve_day(self.user, TODAY, now=NOW)), ['Wake', 'Office'])

    def test_disrupted_without_essentials_falls_back_to_first_anchor(self):
        self.entry('DSA', 7)
        DayPlan.objects.create(user=self.user, date=TODAY, template='workday', mode='disrupted')
        r = resolve_day(self.user, TODAY, now=NOW)
        self.assertEqual(r['warning'], 'no_essential')
        self.assertEqual([b['title'] for b in r['blocks']], ['DSA'])

    def test_missed_is_derived_after_block_end_plus_grace(self):
        self.routine()
        r = resolve_day(self.user, TODAY, now=NOW)   # 10:00; Reading (08:00-09:30) ended > 30 min ago
        status = {b['title']: b['status'] for b in r['blocks']}
        self.assertEqual(status['DSA'], 'missed')       # 07:00-08:00, 30 min grace long gone
        self.assertEqual(status['Reading'], 'pending')   # 08:00-09:30, grace ends exactly now
        self.assertEqual(status['Games'], 'pending')

    def test_block_added_after_its_own_time_is_not_missed_today(self):
        late = self.entry('Stretch', 6, old=False)   # created "now" (10:00), after 06:00
        r = resolve_day(self.user, TODAY, now=NOW)
        self.assertEqual({b['title']: b['status'] for b in r['blocks']}['Stretch'], 'pending')

    def test_day_met_needs_all_essentials_and_half_the_anchors(self):
        self.routine()
        self.entry('Gym', 18)
        r = resolve_day(self.user, TODAY, now=NOW)
        self.assertFalse(r['met'])
        self.log(self.wake, 'done'); self.log(self.office, 'done')
        self.assertFalse(resolve_day(self.user, TODAY, now=NOW)['met'])     # 0 of 2 anchors
        self.log(self.dsa, 'done')
        self.assertTrue(resolve_day(self.user, TODAY, now=NOW)['met'])      # 1 of 2

    def test_skipped_anchor_leaves_the_denominator_but_skipped_essential_fails(self):
        self.routine()
        self.log(self.wake, 'done'); self.log(self.office, 'done'); self.log(self.dsa, 'skipped')
        self.assertTrue(resolve_day(self.user, TODAY, now=NOW)['met'])
        BlockLog.objects.filter(entry=self.office).update(status='skipped')
        self.assertFalse(resolve_day(self.user, TODAY, now=NOW)['met'])

    def test_deleted_block_keeps_its_log_for_the_day(self):
        self.routine()
        self.log(self.wake, 'done'); self.log(self.office, 'done'); self.log(self.dsa, 'done')
        self.dsa.delete()
        r = resolve_day(self.user, TODAY, now=NOW)
        self.assertIn('DSA', [b['title'] for b in r['blocks']])
        self.assertTrue(r['met'])


class RunningLateTests(Base):
    def setUp(self):
        super().setUp()
        self.wake = self.entry('Wake', 5, tier=Tier.ESSENTIAL, fixed=True)
        self.dsa = self.entry('DSA', 10, 30)
        self.read = self.entry('Reading', 11, tier=Tier.FLEXIBLE)
        self.lunch = self.entry('Lunch', 13, tier=Tier.ESSENTIAL, fixed=True)
        self.walk = self.entry('Walk', 12, 45)         # anchor right before lunch
        self.game = self.entry('Games', 14, tier=Tier.FLEXIBLE)

    def late(self, minutes, press=NOW):
        plan, _ = DayPlan.objects.get_or_create(user=self.user, date=TODAY,
                                                defaults={'template': 'workday'})
        plan.shifts = [*plan.shifts, {'at': press.isoformat(), 'minutes': minutes}]
        plan.save()

    def blocks(self):
        return {b['title']: b for b in resolve_day(self.user, TODAY, now=NOW)['blocks']}

    def test_anchors_shift_flexible_before_next_fixed_drop_essential_stays(self):
        self.late(30)
        b = self.blocks()
        self.assertEqual(b['DSA']['time'], time(11, 0))
        self.assertEqual(b['DSA']['shifted_from'], time(10, 30))
        self.assertEqual(b['Reading']['status'], 'dropped')
        self.assertEqual(b['Wake']['time'], time(5, 0))           # before the press, untouched
        self.assertEqual(b['Lunch']['time'], time(13, 0))          # essential never moves
        self.assertEqual(b['Games']['status'], 'pending')          # after the next fixed block: untouched

    def test_anchor_that_would_pass_next_fixed_block_is_dropped_not_stacked(self):
        self.late(30)
        self.assertEqual(self.blocks()['Walk']['status'], 'dropped')   # 12:45 + 30 = 13:15 > lunch

    def test_dropped_blocks_leave_the_required_count(self):
        self.late(60)
        r = resolve_day(self.user, TODAY, now=NOW)
        titles = [b['title'] for b in r['blocks'] if b['tier'] == Tier.ANCHOR and b['status'] != 'dropped']
        self.assertEqual(r['required'], 2 + len(titles))   # 2 essentials + the anchors still in play

    def test_two_shifts_apply_only_after_their_own_press_time(self):
        self.late(15, press=at(9, 0))
        self.late(30, press=at(10, 0))
        self.assertEqual(self.blocks()['DSA']['time'], time(11, 15))

    def test_undo_restores_the_day(self):
        self.late(30)
        DayPlan.objects.update(shifts=[])
        self.assertEqual(self.blocks()['Reading']['status'], 'pending')


class DayApiTests(Base):
    def test_put_day_plan_sets_template_and_mode(self):
        r = self.client.put('/board/api/day_plans/2026-11-05/', {'mode': 'light', 'template': 'holiday'},
                            content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['data']['mode'], 'light')
        self.assertFalse(r.json()['data']['is_default'])

    def test_put_day_plan_rejects_closed_and_far_future_days(self):
        self.assertEqual(self.client.put('/board/api/day_plans/2026-11-04/', {'mode': 'light'},
                                         content_type='application/json').status_code, 400)
        self.assertEqual(self.client.put('/board/api/day_plans/2026-11-20/', {'mode': 'light'},
                                         content_type='application/json').status_code, 400)

    def test_timeline_has_day_and_routine_items_with_tier_and_status(self):
        e = self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        r = self.client.get('/board/api/timeline/?date=2026-11-05').json()
        self.assertEqual(r['day']['template'], 'workday')
        item = next(x for x in r['data'] if x['id'] == f'routine-{e.id}')
        self.assertEqual((item['tier'], item['status']), ('essential', 'missed'))
        self.assertEqual(item['action'], {'block': ['done', 'skipped']})
        self.assertTrue(item['ends_at'])  # blocks run until the next one starts
        self.assertTrue(any(x['id'] == 'day-checkin-2026-11-05' for x in r['data']))

    def test_changing_day_template_changes_the_timeline_blocks(self):
        w = self.entry('Office', 9, rtype='workday')
        h = self.entry('Long walk', 9, rtype='holiday')
        ids = lambda: {x['id'] for x in self.client.get('/board/api/timeline/?date=2026-11-05').json()['data']}
        self.assertIn(f'routine-{w.id}', ids())
        self.assertNotIn(f'routine-{h.id}', ids())
        self.client.put('/board/api/day_plans/2026-11-05/', {'template': 'holiday'}, content_type='application/json')
        self.assertIn(f'routine-{h.id}', ids())
        self.assertNotIn(f'routine-{w.id}', ids())

    def test_sleep_reminder_is_the_second_item_of_the_day(self):
        self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        self.entry('Office', 9)
        data = self.client.get('/board/api/timeline/?date=2026-11-05').json()['data']
        order = [x['id'] for x in sorted(data, key=lambda x: x['timestamp'])]
        first_two = order[:3]
        self.assertTrue(any(i.startswith('sleep-tracker-') for i in first_two[1:3]))
        self.assertLess(order.index('sleep-tracker-2026-11-05'), 3)

    def test_checkin_disappears_once_a_day_is_chosen(self):
        self.client.put('/board/api/day_plans/2026-11-05/', {'mode': 'normal', 'source': 'checkin'},
                        content_type='application/json')
        r = self.client.get('/board/api/timeline/?date=2026-11-05').json()
        self.assertFalse(any(x['id'].startswith('day-checkin') for x in r['data']))

    def test_block_log_done_skip_undo_and_closed_day_read_only(self):
        e = self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        url = f'/board/api/day_plans/2026-11-05/blocks/{e.id}/'
        self.assertEqual(self.client.put(url, {'status': 'done'}, content_type='application/json').status_code, 200)
        self.assertEqual(BlockLog.objects.get().status, 'done')
        self.client.put(url, {'status': 'skipped', 'reason': 'sick'}, content_type='application/json')
        self.assertEqual(BlockLog.objects.get().reason, 'sick')
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertFalse(BlockLog.objects.exists())
        closed = f'/board/api/day_plans/2026-11-04/blocks/{e.id}/'
        self.assertEqual(self.client.put(closed, {'status': 'done'}, content_type='application/json').status_code, 409)

    def test_cannot_log_another_users_block(self):
        theirs = self.entry('Wake', 5, user=self.other)
        r = self.client.put(f'/board/api/day_plans/2026-11-05/blocks/{theirs.id}/', {'status': 'done'},
                            content_type='application/json')
        self.assertEqual(r.status_code, 404)

    def test_running_late_post_and_undo(self):
        self.assertEqual(self.client.post('/board/api/day_plans/2026-11-05/late/', {'minutes': 30},
                                          content_type='application/json').status_code, 200)
        self.assertEqual(len(DayPlan.objects.get().shifts), 1)
        self.assertEqual(self.client.post('/board/api/day_plans/2026-11-05/late/', {'minutes': 20},
                                          content_type='application/json').status_code, 400)
        self.client.delete('/board/api/day_plans/2026-11-05/late/')
        self.assertEqual(DayPlan.objects.get().shifts, [])

    def test_travel_sets_disrupted_then_light_and_never_overwrites_manual(self):
        DayPlan.objects.create(user=self.user, date=date(2026, 11, 7), template='holiday',
                               mode='normal', source='manual')
        r = self.client.post('/board/api/day_plans/travel/', {'start': '2026-11-06', 'end': '2026-11-07'},
                             content_type='application/json').json()['data']
        self.assertEqual(r['skipped'], ['2026-11-07'])
        modes = {p.date.isoformat(): (p.mode, p.source) for p in DayPlan.objects.all()}
        self.assertEqual(modes['2026-11-06'], ('disrupted', 'travel'))
        self.assertEqual(modes['2026-11-07'], ('normal', 'manual'))
        self.assertEqual(modes['2026-11-08'], ('light', 'ramp'))
        self.client.delete('/board/api/day_plans/travel/?from=2026-11-06&to=2026-11-07')
        self.assertEqual(list(DayPlan.objects.values_list('source', flat=True)), ['manual'])

    def test_slip_brings_reset_card_and_completing_it_downgrades_to_light(self):
        self.assertEqual(self.client.post('/board/api/lapses/', {'note': 'stress'}, content_type='application/json').status_code, 200)
        items = self.client.get('/board/api/timeline/?date=2026-11-05').json()['data']
        reset = next(x for x in items if x['id'] == 'reset-2026-11-05')
        self.assertEqual(len(reset['reset']['steps']), 4)
        r = self.client.put('/board/api/day_plans/2026-11-05/reset/', {}, content_type='application/json')
        self.assertEqual(r.json()['data']['mode'], 'light')
        self.assertTrue(r.json()['data']['reset_done'])
        self.assertEqual(self.client.put('/board/api/day_plans/2026-11-05/reset/', {}, content_type='application/json').status_code, 200)
        reset = next(x for x in self.client.get('/board/api/timeline/?date=2026-11-05').json()['data']
                     if x['id'] == 'reset-2026-11-05')
        self.assertIsNone(reset['action'])

    def test_reset_with_nothing_to_reset_is_refused(self):
        self.assertEqual(self.client.put('/board/api/day_plans/2026-11-05/reset/', {}, content_type='application/json').status_code, 409)

    def test_slip_on_a_chosen_metric_logs_plus_one(self):
        m = Metric.objects.create(user=self.user, name='Coffee', kind='counter', direction='at_most',
                                  target=3, quick_steps=[1], is_private=True)
        self.detail.slip_metric = m
        self.detail.save()
        self.client.post('/board/api/lapses/', {'note': ''}, content_type='application/json')
        self.assertEqual(MetricEntry.objects.filter(metric=m).count(), 1)


class RoutineApiTests(Base):
    def test_bulk_create_is_an_upsert_so_ids_survive_edits(self):
        a = self.entry('Wake', 5)
        b = self.entry('Read', 8)
        body = {'routine_type': 'workday', 'entries': [
            {'id': a.id, 'title': 'Wake up', 'time': '05:00:00', 'tier': 'essential', 'fixed_time': True},
            {'title': 'Gym', 'time': '18:00:00'},
        ]}
        r = self.client.post('/board/api/routine_entries/bulk_create/', body, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        a.refresh_from_db()
        self.assertEqual((a.title, a.tier, a.fixed_time), ('Wake up', 'essential', True))
        self.assertFalse(RoutineEntry.objects.filter(pk=b.id).exists())         # missing from payload
        self.assertEqual(RoutineEntry.objects.filter(user=self.user).count(), 2)

    def test_logs_survive_a_routine_edit(self):
        a = self.entry('Wake', 5)
        BlockLog.objects.create(user=self.user, date=TODAY, entry=a, title='Wake', scheduled_time=a.time,
                                tier='anchor', status='done')
        self.client.post('/board/api/routine_entries/bulk_create/', {'routine_type': 'workday', 'entries': [
            {'id': a.id, 'title': 'Wake', 'time': '05:30:00'}]}, content_type='application/json')
        self.assertEqual(BlockLog.objects.get().entry_id, a.id)

    def test_empty_list_clears_the_routine(self):
        self.entry('Wake', 5)
        self.client.post('/board/api/routine_entries/bulk_create/', {'routine_type': 'workday', 'entries': []},
                         content_type='application/json')
        self.assertFalse(RoutineEntry.objects.exists())

    def test_payload_cannot_reach_another_users_entry(self):
        theirs = self.entry('Secret', 5, user=self.other)
        r = self.client.post('/board/api/routine_entries/bulk_create/', {'routine_type': 'workday', 'entries': [
            {'id': theirs.id, 'title': 'Mine now', 'time': '05:00:00'}]}, content_type='application/json')
        self.assertEqual(r.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, 'Secret')


class OwnershipTests(Base):
    def test_cannot_edit_delete_or_toggle_another_users_routine_or_habit(self):
        theirs = self.entry('Secret', 5, user=self.other)
        habit = self.habit(user=self.other, habit='Run', identity='Runner')
        j = 'application/json'
        self.assertEqual(self.client.put(f'/board/api/routine_entries/{theirs.id}/', {'title': 'x'}, content_type=j).status_code, 404)
        self.assertEqual(self.client.delete(f'/board/api/routine_entries/{theirs.id}/').status_code, 404)
        self.assertEqual(self.client.put(f'/board/api/habits/{habit.id}/', {'habit': 'x'}, content_type=j).status_code, 404)
        self.assertEqual(self.client.put(f'/board/api/habits/{habit.id}/toggle/', {'date': '2026-11-05'}, content_type=j).status_code, 404)
        self.assertEqual(self.client.get(f'/board/api/habits/{habit.id}/logs/').status_code, 404)
        self.assertEqual(self.client.delete(f'/board/api/habits/{habit.id}/').status_code, 404)
        self.assertFalse(HabitLog.objects.exists())
        theirs.refresh_from_db(); habit.refresh_from_db()
        self.assertEqual((theirs.title, habit.habit, habit.status), ('Secret', 'Run', 'active'))

    def test_timeline_respond_cannot_mark_another_users_task_or_habit(self):
        from board.models import Task, TimelineEvent
        task = Task.objects.create(user=self.other, task_name='t')
        ev = TimelineEvent.objects.create(user=self.user, timestamp=NOW, event_type='todo', event='x',
                                          reference={'model': 'Task', 'id': task.id}, action={'mark_done': [True, False]})
        r = self.client.put(f'/board/api/timeline/{ev.id}/respond/', {'action_response': {'mark_done': True}},
                            content_type='application/json')
        self.assertFalse(r.json()['propagation']['propagated'])
        task.refresh_from_db()
        self.assertFalse(task.is_done)

    def test_habit_card_answered_late_logs_the_events_own_date(self):
        from board.models import TimelineEvent
        habit = self.habit(user=self.user, habit='Run', identity='Runner',
                                     created_at=at(8, day=date(2026, 11, 1)))
        ev = TimelineEvent.objects.create(user=self.user, timestamp=at(6, day=date(2026, 11, 3)),
                                          event_type='habit', event='x',
                                          reference={'model': 'Habit', 'id': habit.id}, action={'mark_done': [True, False]})
        self.client.put(f'/board/api/timeline/{ev.id}/respond/', {'action_response': {'mark_done': True}},
                        content_type='application/json')
        self.assertEqual(list(HabitLog.objects.values_list('date', flat=True)), [date(2026, 11, 3)])


def summary(user, day, outcome, mode='normal'):
    return DaySummary.objects.create(user=user, date=day, mode=mode, required=1, required_done=1, outcome=outcome)


class StreakTests(Base):
    def test_global_streak_walks_summaries_skips_frozen_and_stops_at_missed(self):
        d = lambda n: TODAY - timedelta(days=n)
        for n, o in [(1, 'met'), (2, 'reset'), (3, 'frozen'), (4, 'met'), (5, 'legacy'), (6, 'missed'), (7, 'met')]:
            summary(self.user, d(n), o)
        self.assertEqual(compute_global_streak(self.user.id, now=NOW), 4)   # frozen adds nothing

    def test_idle_days_show_a_lapsed_streak_once_closed(self):
        self.detail.streak_rule = 'routine'
        self.detail.freezes = 0
        self.detail.save()
        self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        for n in range(8, 4, -1):
            summary(self.user, TODAY - timedelta(days=n), 'met')
        close_pending_days(self.user.id, now=NOW)                    # days 4,3,2,1 all missed
        self.assertEqual(compute_global_streak(self.user.id, now=NOW), 0)

    def test_freeze_is_consumed_in_date_order_and_never_twice_in_a_row(self):
        self.detail.streak_rule = 'routine'
        self.detail.freezes = 2
        self.detail.save()
        self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        summary(self.user, TODAY - timedelta(days=4), 'met')
        close_pending_days(self.user.id, now=NOW)
        outcomes = list(DaySummary.objects.filter(date__gt=TODAY - timedelta(days=4)).order_by('date')
                        .values_list('outcome', flat=True))
        self.assertEqual(outcomes, ['frozen', 'missed', 'frozen'])      # second miss in a row breaks
        self.detail.refresh_from_db()
        self.assertEqual(self.detail.freezes, 0)

    def test_close_day_is_idempotent_and_met_days_earn_a_freeze_every_seven(self):
        self.detail.streak_rule = 'routine'
        self.detail.freezes = 0
        self.detail.save()
        wake = self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        for n in range(7, 1, -1):
            summary(self.user, TODAY - timedelta(days=n), 'met')      # six counted days
        self.log(wake, 'done', day=TODAY - timedelta(days=1))
        close_day(self.user.id, TODAY - timedelta(days=1), now=NOW)
        close_day(self.user.id, TODAY - timedelta(days=1), now=NOW)
        self.assertEqual(DaySummary.objects.filter(date=TODAY - timedelta(days=1)).count(), 1)
        self.detail.refresh_from_db()
        self.assertEqual(self.detail.freezes, 1)                      # seventh counted day

    def test_freezes_cap_at_two(self):
        self.detail.streak_rule = 'routine'
        self.detail.freezes = 2
        self.detail.save()
        wake = self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        for n in range(7, 1, -1):
            summary(self.user, TODAY - timedelta(days=n), 'met')
        self.log(wake, 'done', day=TODAY - timedelta(days=1))
        close_day(self.user.id, TODAY - timedelta(days=1), now=NOW)
        self.detail.refresh_from_db()
        self.assertEqual(self.detail.freezes, 2)

    def test_activity_rule_keeps_todays_behaviour(self):
        habit = self.habit(user=self.user, habit='Run', identity='r', created_at=at(8, day=TODAY - timedelta(days=10)))
        HabitLog.objects.create(habit=habit, date=TODAY - timedelta(days=1), is_done=True)
        close_pending_days(self.user.id, now=NOW)
        self.assertEqual(DaySummary.objects.get(date=TODAY - timedelta(days=1)).outcome, 'legacy')

    def habit_fixture(self):
        """14 days: done, done, frozen miss, light-day miss (excused), done, ..., then a real miss."""
        start = TODAY - timedelta(days=13)
        habit = self.habit(user=self.user, habit='Read', identity='r', on_light='excused',
                                     on_disrupted='required', created_at=at(8, day=start))
        done = {1, 2, 5, 6, 7, 8, 9, 10, 12, 13}     # day offsets from start that are done
        for n in done:
            HabitLog.objects.create(habit=habit, date=start + timedelta(days=n), is_done=True)
        DaySummary.objects.create(user=self.user, date=start + timedelta(days=3), mode='normal',
                                  required=0, required_done=0, outcome='frozen')
        DayPlan.objects.create(user=self.user, date=start + timedelta(days=4), template='workday', mode='light')
        DayPlan.objects.create(user=self.user, date=start + timedelta(days=11), template='workday', mode='disrupted')
        return habit, start

    def test_habit_streak_fixture_with_frozen_excused_and_missed_days(self):
        habit, start = self.habit_fixture()
        logs = {l.date: l.is_done for l in habit.habitlog_set.all()}
        current, best = habit_streaks(habit, logs, StreakContext(self.user.id, today=TODAY))
        # day 11 is disrupted but on_disrupted=required, so it breaks: current is days 12, 13, plus today pending = 2
        self.assertEqual(current, 2)
        # offsets 1,2 | 3 frozen | 4 excused | 5..10 -> 2 + 6 = 8 done in one run
        self.assertEqual(best, 8)

    def test_habit_streak_excusal_follows_the_setting(self):
        habit, start = self.habit_fixture()
        habit.on_disrupted = 'excused'
        logs = {l.date: l.is_done for l in habit.habitlog_set.all()}
        current, _ = habit_streaks(habit, logs, StreakContext(self.user.id, today=TODAY))
        self.assertEqual(current, 10)      # 12, 13 + day 11 excused + 5..10 (6) + frozen/excused + 1,2 = 10

    def test_done_on_an_excused_day_still_adds_one(self):
        start = TODAY - timedelta(days=2)
        habit = self.habit(user=self.user, habit='Read', identity='r', on_light='excused',
                                     created_at=at(8, day=start))
        for n in (0, 1):
            HabitLog.objects.create(habit=habit, date=start + timedelta(days=n), is_done=True)
        DayPlan.objects.create(user=self.user, date=start + timedelta(days=1), template='workday', mode='light')
        current, _ = habit_streaks(habit, {start: True, start + timedelta(days=1): True},
                                   StreakContext(self.user.id, today=TODAY))
        self.assertEqual(current, 2)

    def test_habit_list_runs_a_bounded_number_of_queries(self):
        for i in range(8):
            h = self.habit(user=self.user, habit=f'h{i}', identity='x', created_at=at(8, day=TODAY - timedelta(days=30)))
            for n in range(1, 20):
                HabitLog.objects.create(habit=h, date=TODAY - timedelta(days=n), is_done=True)
        with self.assertNumQueries(12):   # session + user + context + habits + logs; flat in the number of habits
            r = self.client.get('/board/api/habits/')
        self.assertEqual(len(r.json()['data']), 8)
        self.assertEqual(r.json()['data'][0]['stats']['streak'], 19)

    def test_gamification_view_shows_a_lapsed_streak_not_the_old_number(self):
        self.detail.current_streak = 40
        self.detail.freezes = 0
        self.detail.streak_rule = 'routine'
        self.detail.save()
        self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        for n in range(6, 3, -1):
            summary(self.user, TODAY - timedelta(days=n), 'met')
        r = self.client.get('/board/api/gamification/').json()['data']
        self.assertEqual(r['current_streak'], 0)

    def test_reset_completes_a_day_that_would_have_missed(self):
        self.detail.streak_rule = 'routine'
        self.detail.save()
        wake = self.entry('Wake', 5, tier=Tier.ESSENTIAL)
        y = TODAY - timedelta(days=1)
        DayPlan.objects.create(user=self.user, date=y, template='workday', mode='light', source='reset',
                               reset_done_at=at(9, day=y))
        self.log(wake, 'done', day=y)
        close_day(self.user.id, y, now=NOW)
        self.assertEqual(DaySummary.objects.get(date=y).outcome, 'reset')


class MetricTests(Base):
    def make(self, **kw):
        defaults = dict(user=self.user, name='Walk', unit='min', kind='additive', target=30,
                        quick_steps=[10, 15, 30])
        defaults.update(kw)
        return Metric.objects.create(**defaults)

    def test_tracker_reminder_card_on_timeline_until_logged(self):
        m = self.client.post('/board/api/metrics/', {'name': 'Water', 'kind': 'additive', 'unit': 'l',
                                                      'remind_at': '10:30'}, content_type='application/json').json()['data']
        self.assertEqual(m['remind_at'], '10:30')
        r = self.client.get('/board/api/timeline/?date=2026-11-05').json()
        card = next(x for x in r['data'] if x['id'] == f"metric-{m['id']}-2026-11-05")
        self.assertEqual(card['action'], {'metric': ['log']})
        self.client.post(f"/board/api/metrics/{m['id']}/log/", {'value': 1}, content_type='application/json')
        r = self.client.get('/board/api/timeline/?date=2026-11-05').json()
        card = next(x for x in r['data'] if x['id'] == f"metric-{m['id']}-2026-11-05")
        self.assertIsNone(card['action'])

    def test_additive_sums_and_marks_a_linked_habit_done_at_target(self):
        m = self.make()
        h = self.habit(user=self.user, habit='Walk', identity='w', metric=m,
                                 created_at=at(8, day=TODAY - timedelta(days=5)))
        j = 'application/json'
        self.client.post(f'/board/api/metrics/{m.id}/log/', {'value': 15}, content_type=j)
        self.assertFalse(HabitLog.objects.filter(habit=h, is_done=True).exists())
        self.client.post(f'/board/api/metrics/{m.id}/log/', {'value': 15}, content_type=j)
        self.assertTrue(HabitLog.objects.get(habit=h, date=TODAY).is_done)
        self.client.delete(f'/board/api/metrics/{m.id}/log/')
        self.assertFalse(HabitLog.objects.get(habit=h, date=TODAY).is_done)

    def test_counter_logs_one_entry_with_fields_and_note_into_its_journal(self):
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type='application/json')
        self.client.post('/board/api/private/unlock/', {'pin': '4821'}, content_type='application/json')
        m = self.make(name='Coffee', kind='counter', unit='', direction='at_most', target=3,
                      quick_steps=[1], is_private=True,
                      fields=[{'key': 'trigger', 'label': 'Trigger', 'type': 'choice',
                               'options': ['after meal', 'stress'], 'allow_other': True},
                              {'key': 'urge', 'label': 'Urge', 'type': 'scale', 'max': 10}])
        r = self.client.post(f'/board/api/metrics/{m.id}/log/', {'data': {'trigger': 'stress', 'urge': 4},
                                                           'note': 'long call'}, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        e = MetricEntry.objects.get()
        self.assertEqual((e.value, e.data), (Decimal('1'), {'trigger': 'stress', 'urge': 4}))
        j = m.journal
        self.assertTrue(j.is_private)
        self.assertEqual(j.entries.get().text, 'long call')
        self.assertEqual(r.json()['data']['today'], 1.0)

    def test_field_validation_rejects_bad_scale(self):
        m = self.make(kind='counter', fields=[{'key': 'urge', 'label': 'Urge', 'type': 'scale', 'max': 10}])
        r = self.client.post(f'/board/api/metrics/{m.id}/log/', {'data': {'urge': 11}}, content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_single_overwrites_and_keeps_previous(self):
        m = self.make(name='Weight', kind='single', unit='kg', target=None, quick_steps=[])
        j = 'application/json'
        self.client.post(f'/board/api/metrics/{m.id}/log/', {'value': 70}, content_type=j)
        self.client.post(f'/board/api/metrics/{m.id}/log/', {'value': 69.5}, content_type=j)
        e = MetricEntry.objects.get()
        self.assertEqual((e.value, e.data['previous']), (Decimal('69.5'), 70.0))
        self.client.delete(f'/board/api/metrics/{m.id}/log/')
        self.assertFalse(MetricEntry.objects.exists())

    def test_at_most_habit_is_settled_at_day_close_and_target_light_applies_on_light_days(self):
        m = self.make(name='Coffee', kind='counter', direction='at_most', target=3, target_light=5,
                      quick_steps=[1], unit='')
        y = TODAY - timedelta(days=1)
        h = self.habit(user=self.user, habit='Limit', identity='x', metric=m,
                                 created_at=at(8, day=y - timedelta(days=3)))
        for i in range(4):
            MetricEntry.objects.create(metric=m, date=y, at=at(10 + i, day=y), value=1)
        close_day(self.user.id, y, now=NOW)
        self.assertFalse(HabitLog.objects.get(habit=h, date=y).is_done)      # 4 > 3
        d2 = y - timedelta(days=1)
        for i in range(4):
            MetricEntry.objects.create(metric=m, date=d2, at=at(10 + i, day=d2), value=1)
        DayPlan.objects.create(user=self.user, date=d2, template='workday', mode='light')
        close_day(self.user.id, d2, now=NOW)
        self.assertTrue(HabitLog.objects.get(habit=h, date=d2).is_done)      # 4 <= 5 on a light day

    def test_breach_brings_the_reset_card(self):
        m = self.make(name='Coffee', kind='counter', direction='at_most', target=1, quick_steps=[1], unit='')
        j = 'application/json'
        self.client.post(f'/board/api/metrics/{m.id}/log/', {}, content_type=j)
        self.assertFalse(any(x['id'].startswith('reset') for x in self.client.get('/board/api/timeline/?date=2026-11-05').json()['data']))
        self.client.post(f'/board/api/metrics/{m.id}/log/', {}, content_type=j)
        self.assertTrue(any(x['id'].startswith('reset') for x in self.client.get('/board/api/timeline/?date=2026-11-05').json()['data']))

    def test_insights_group_triggers_and_time_of_day(self):
        m = self.make(kind='counter', quick_steps=[1],
                      fields=[{'key': 'trigger', 'label': 'T', 'type': 'choice', 'options': ['a', 'b']}])
        for t in ('a', 'a', 'b'):
            mx.log_entry(m, data={'trigger': t})
        r = self.client.get(f'/board/api/metrics/{m.id}/insights/?days=7').json()['data']
        self.assertEqual(r['triggers']['trigger'], {'a': 2, 'b': 1})
        self.assertEqual(sum(r['time_of_day']), 3)
        self.assertEqual(r['daily'][-1]['value'], 3.0)

    def test_metrics_are_owner_scoped(self):
        theirs = self.make(user=self.other)
        self.assertEqual(self.client.post(f'/board/api/metrics/{theirs.id}/log/', {'value': 1}, content_type='application/json').status_code, 404)

    def test_sleep_card_mirrors_into_sleep_metric_and_journal_text_into_default_journal(self):
        r = self.client.put('/board/api/daily_data/2026-11-05/', {'sleep_hours': '7.5', 'journal': 'good day'},
                            content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        sleep = Metric.objects.get(user=self.user, is_system=True)
        self.assertEqual(MetricEntry.objects.get(metric=sleep).value, Decimal('7.5'))
        self.assertEqual(sleep.journal.entries.get().text, 'good day')
        self.client.put('/board/api/daily_data/2026-11-05/', {'journal': ''}, content_type='application/json')
        self.assertFalse(sleep.journal.entries.exists())

    def test_habit_checklist_steps_and_stages_mark_the_habit_done(self):
        h = self.habit(user=self.user, habit='Rehab', identity='x',
                                 created_at=at(8, day=TODAY - timedelta(days=3)))
        j = 'application/json'
        s1 = self.client.post(f'/board/api/habits/{h.id}/steps/', {'name': 'Glute bridges', 'target': '2 x 10', 'stage': 1}, content_type=j).json()['data']
        s2 = self.client.post(f'/board/api/habits/{h.id}/steps/', {'name': 'Strength set', 'stage': 2}, content_type=j).json()['data']
        steps = self.client.get(f'/board/api/habits/{h.id}/steps/').json()['data']['steps']
        self.assertEqual([s['visible'] for s in steps], [True, False])
        self.client.put(f'/board/api/habit_steps/{s1["id"]}/log/', {'done': True}, content_type=j)
        self.assertTrue(HabitLog.objects.get(habit=h, date=TODAY).is_done)       # only stage 1 is required
        h.current_stage = 2
        h.save()
        self.client.put(f'/board/api/habit_steps/{s2["id"]}/log/', {'done': False}, content_type=j)
        self.assertFalse(HabitLog.objects.get(habit=h, date=TODAY).is_done)

    def test_other_users_habit_steps_are_not_reachable(self):
        h = self.habit(user=self.other, habit='Rehab', identity='x')
        self.assertEqual(self.client.get(f'/board/api/habits/{h.id}/steps/').status_code, 404)


class PrivacyTests(Base):
    def setUp(self):
        super().setUp()
        self.secret = self.habit(user=self.user, habit='Quit sugar', identity='x', is_private=True,
                                           created_at=at(8, day=TODAY - timedelta(days=3)))
        self.plain = self.habit(user=self.user, habit='Read', identity='x',
                                          created_at=at(8, day=TODAY - timedelta(days=3)))
        self.metric = Metric.objects.create(user=self.user, name='Coffee', kind='counter', quick_steps=[1],
                                            is_private=True)
        self.j = 'application/json'

    def unlock(self):
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type=self.j)
        return self.client.post('/board/api/private/unlock/', {'pin': '4821'}, content_type=self.j)

    def names(self):
        return [h['habit'] for h in self.client.get('/board/api/habits/').json()['data']]

    def test_pin_validation_and_hash_never_exposed(self):
        self.assertEqual(self.client.post('/board/api/private/pin/', {'pin': '12'}, content_type=self.j).status_code, 400)
        self.assertEqual(self.client.post('/board/api/private/pin/', {'pin': 'abcd'}, content_type=self.j).status_code, 400)
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type=self.j)
        ud = self.client.get('/board/api/user_details/').json()['data']
        self.assertNotIn('private_pin_hash', ud)
        self.assertTrue(ud['has_private_pin'])

    def test_locked_hides_every_private_row_with_no_placeholder(self):
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type=self.j)
        self.assertEqual(self.names(), ['Read'])
        self.assertEqual(self.client.get('/board/api/metrics/').json()['data'], [])
        self.assertEqual(self.client.get(f'/board/api/metrics/{self.metric.id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/board/api/habits/{self.secret.id}/steps/').status_code, 404)
        self.assertEqual(self.client.put(f'/board/api/habits/{self.secret.id}/toggle/', {'date': '2026-11-05'},
                                         content_type=self.j).status_code, 404)
        self.assertEqual(self.client.post(f'/board/api/metrics/{self.metric.id}/log/', {}, content_type=self.j).status_code, 404)
        from board.models import Journal
        Journal.objects.create(user=self.user, name='Quit diary', is_private=True)
        self.assertEqual([x['name'] for x in self.client.get('/board/api/journal_books/').json()['data']], ['Journal'])

    def test_unlock_shows_them_and_lock_hides_them_again(self):
        self.assertEqual(self.unlock().status_code, 200)
        self.assertEqual(sorted(self.names()), ['Quit sugar', 'Read'])
        self.assertEqual(len(self.client.get('/board/api/metrics/').json()['data']), 1)
        self.client.post('/board/api/private/lock/', {}, content_type=self.j)
        self.assertEqual(self.names(), ['Read'])

    def test_unlock_expires_after_the_window(self):
        self.unlock()
        later = NOW + timedelta(minutes=11)
        with mock.patch('time.time', return_value=later.timestamp()):
            self.assertEqual(self.names(), ['Read'])

    def test_five_wrong_pins_lock_unlocking_for_fifteen_minutes(self):
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type=self.j)
        for _ in range(4):
            self.assertEqual(self.client.post('/board/api/private/unlock/', {'pin': '0000'}, content_type=self.j).status_code, 403)
        r = self.client.post('/board/api/private/unlock/', {'pin': '0000'}, content_type=self.j)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.client.post('/board/api/private/unlock/', {'pin': '4821'}, content_type=self.j).status_code, 429)

    def test_timeline_hides_private_habit_events_until_unlocked(self):
        from board.models import TimelineEvent
        TimelineEvent.objects.create(user=self.user, timestamp=at(9), event_type='habit', event='Time to: Quit sugar',
                                     reference={'model': 'Habit', 'id': self.secret.id}, action={'mark_done': [True, False]})
        events = lambda: [e['event'] for e in self.client.get('/board/api/timeline/?date=2026-11-05').json()['data']]
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type=self.j)
        self.assertNotIn('Time to: Quit sugar', events())
        self.assertNotIn('Reminder', events())
        self.secret.private_reminder = True
        self.secret.save()
        self.assertIn('Reminder', events())
        self.assertNotIn('Time to: Quit sugar', events())
        self.client.post('/board/api/private/unlock/', {'pin': '4821'}, content_type=self.j)
        self.assertIn('Time to: Quit sugar', events())

    def test_score_and_achievements_leave_private_habits_out_while_locked(self):
        HabitLog.objects.create(habit=self.plain, date=TODAY, is_done=True)
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type=self.j)
        locked = self.client.get('/board/api/productivity_score/?date=2026-11-05').json()['data']['breakdown']
        self.assertEqual(locked['habits_due'], 1)
        self.unlock()
        unlocked = self.client.get('/board/api/productivity_score/?date=2026-11-05').json()['data']['breakdown']
        self.assertEqual(unlocked['habits_due'], 2)

    def test_streaks_still_count_private_activity(self):
        HabitLog.objects.create(habit=self.secret, date=TODAY - timedelta(days=1), is_done=True)
        close_pending_days(self.user.id, now=NOW)
        self.assertEqual(DaySummary.objects.get(date=TODAY - timedelta(days=1)).outcome, 'legacy')

    def test_forgotten_pin_resets_through_an_email_code(self):
        from django.core import mail
        self.client.post('/board/api/private/pin/', {'pin': '4821'}, content_type=self.j)
        self.assertEqual(self.client.post('/board/api/private/reset/request/', {}, content_type=self.j).status_code, 200)
        code = mail.outbox[0].body.split('code is ')[1][:6]
        self.assertEqual(self.client.post('/board/api/private/reset/confirm/', {'code': '000000', 'pin': '9999'},
                                          content_type=self.j).status_code, 403)
        self.assertEqual(self.client.post('/board/api/private/reset/confirm/', {'code': code, 'pin': '9999'},
                                          content_type=self.j).status_code, 200)
        self.assertEqual(self.client.post('/board/api/private/unlock/', {'pin': '9999'}, content_type=self.j).status_code, 200)

    def test_private_habit_cannot_be_shared_with_a_partner(self):
        r = self.client.post('/board/api/accountability_partners/', {'habit_id': self.secret.id, 'email': 'x@example.com'},
                             content_type=self.j)
        self.assertEqual(r.status_code, 400)


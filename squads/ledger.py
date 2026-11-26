"""
Contribution ledger. Every log on a linked item writes a row; edits within the
late-log cutoff append a reversal and a new row, never update in place.
Points are written by the day evaluator, after the cutoff, never before.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from squads.events import track
from squads.models import (
    BoardType, Contribution, ContributionReason, FeedItem, MembershipStatus, Nudge, SquadGoal,
)

NUDGE_WINDOW_HOURS = 2


def active_rows(**filters):
    """Rows that are neither reversals nor reversed."""
    return Contribution.objects.filter(reversal_of__isnull=True, reversed_by__isnull=True, **filters)


def reverse(row):
    return Contribution.objects.create(
        board=row.board, user=row.user, member_label=row.member_label, source_type=row.source_type,
        source_id=row.source_id, goal=row.goal, points=-row.points, value=-row.value, reason=row.reason,
        day=row.day, late=row.late, reversal_of=row,
    )


def _member_active(board, user_id):
    if board.type == BoardType.PERSONAL:
        return False
    return board.memberships.filter(user_id=user_id, status=MembershipStatus.ACTIVE).exists()


def _within_cutoff(board, day, now):
    return now <= board.cutoff_for(day)


def _is_late(board, day, now):
    return board.local_now(now).date() > day


# ──────────────────────────────────────
# Habit logs
# ──────────────────────────────────────

def on_habit_log(log, deleted=False, now=None):
    habit = log.habit
    squad_habit = habit.linked_squad_habit
    if squad_habit is None:
        return
    board = squad_habit.board
    user_id = habit.user_id
    now = now or timezone.now()
    if not _member_active(board, user_id) or not board.is_writable:
        return
    if not _within_cutoff(board, log.date, now):
        return   # the day is closed for the squad; the personal log still stands
    late = _is_late(board, log.date, now)
    done = (not deleted) and log.is_done
    with transaction.atomic():
        existing = list(active_rows(board=board, user_id=user_id, source_type='habitlog', source_id=log.id,
                                    reason=ContributionReason.CHECKIN))
        if done and not existing:
            Contribution.objects.create(
                board=board, user_id=user_id, source_type='habitlog', source_id=log.id, points=0, value=1,
                reason=ContributionReason.CHECKIN, day=log.date, late=late)
            if not deleted:
                type(log).objects.filter(pk=log.pk).update(logged_at=now, late=late)
            _checkin_side_effects(board, squad_habit, habit, user_id, log.date, late, now)
        elif not done and existing:
            for row in existing:
                reverse(row)
    # Goals counted by habit check-ins
    for goal in SquadGoal.objects.filter(board=board, habit=squad_habit,
                                         period_start__lte=log.date, period_end__gte=log.date):
        _sync_goal_value(goal, user_id, 'habitlog', log.id, Decimal(1) if done else Decimal(0), log.date, late)


def _checkin_side_effects(board, squad_habit, personal_habit, user_id, day, late, now):
    from django.contrib.auth.models import User
    from squads.items import display_name
    user = User.objects.filter(pk=user_id).first()
    # Private linked items expose only done / not done, under the squad's own item name
    FeedItem.objects.create(
        board=board, user_id=user_id, kind='checkin', late=late, reactable=True,
        text=f'{display_name(user)} did {squad_habit.habit}' + (' (logged late)' if late else ''),
        ref={'habit': squad_habit.id, 'day': day.isoformat()},
    )
    since = now - timezone.timedelta(hours=NUDGE_WINDOW_HOURS)
    Nudge.objects.filter(board=board, to_user_id=user_id, day=day, converted_at__isnull=True,
                         created_at__gte=since).update(converted_at=now)
    track('squad_log', user_id, board_id=board.id,
          source=personal_habit.habitlog_set.filter(date=day).values_list('source', flat=True).first() or 'manual',
          late=late, linked=True)


# ──────────────────────────────────────
# Tracker entries
# ──────────────────────────────────────

def _sync_goal_value(goal, user_id, source_type, source_id, value, day, late):
    rows = list(active_rows(board=goal.board, user_id=user_id, source_type=source_type, source_id=source_id,
                            reason=ContributionReason.VALUE, goal=goal))
    if len(rows) == 1 and rows[0].value == value:
        return
    for row in rows:
        reverse(row)
    if value:
        Contribution.objects.create(board=goal.board, user_id=user_id, source_type=source_type, source_id=source_id,
                                    goal=goal, points=0, value=value, reason=ContributionReason.VALUE,
                                    day=day, late=late)


def on_metric_entry(entry, deleted=False, now=None):
    metric = entry.metric
    squad_metric = metric.linked_squad_tracker
    if squad_metric is None:
        return
    board = squad_metric.board
    user_id = metric.user_id
    now = now or timezone.now()
    if not _member_active(board, user_id) or not board.is_writable or not _within_cutoff(board, entry.date, now):
        return
    late = _is_late(board, entry.date, now)
    value = Decimal(0) if deleted else Decimal(entry.value)
    with transaction.atomic():
        goals = list(SquadGoal.objects.filter(board=board, tracker=squad_metric,
                                              period_start__lte=entry.date, period_end__gte=entry.date))
        for goal in goals:
            if goal.aggregation == 'count':
                _sync_goal_value(goal, user_id, 'metricentry', entry.id, Decimal(0 if deleted else 1), entry.date, late)
            else:
                _sync_goal_value(goal, user_id, 'metricentry', entry.id, value, entry.date, late)
        if not goals:
            rows = list(active_rows(board=board, user_id=user_id, source_type='metricentry', source_id=entry.id,
                                    reason=ContributionReason.VALUE, goal__isnull=True))
            if not (len(rows) == 1 and rows[0].value == value):
                for row in rows:
                    reverse(row)
                if value:
                    Contribution.objects.create(board=board, user_id=user_id, source_type='metricentry',
                                                source_id=entry.id, value=value, reason=ContributionReason.VALUE,
                                                day=entry.date, late=late)
    if not deleted:
        type(entry).objects.filter(pk=entry.pk).update(late=late)
        track('squad_log', user_id, board_id=board.id, source=entry.source or 'manual', late=late, linked=True)


# ──────────────────────────────────────
# Reads
# ──────────────────────────────────────

def net(qs):
    agg = qs.aggregate(points=Sum('points'), value=Sum('value'))
    return int(agg['points'] or 0), Decimal(agg['value'] or 0)


def points_by_user(board, start, end):
    rows = (Contribution.objects.filter(board=board, day__gte=start, day__lte=end)
            .values('user_id').annotate(points=Sum('points')))
    return {r['user_id']: int(r['points'] or 0) for r in rows}


def goal_progress(goal):
    qs = Contribution.objects.filter(goal=goal, reason=ContributionReason.VALUE)
    by_user = {r['user_id']: Decimal(r['v'] or 0) for r in qs.values('user_id').annotate(v=Sum('value'))}
    total = sum(by_user.values(), Decimal(0))
    if goal.aggregation == 'avg':
        days = max(1, (min(timezone.localdate(), goal.period_end) - goal.period_start).days + 1)
        members = max(1, len(by_user))
        total = total / days / members
    return total, by_user


def has_activity(board, user_id, day):
    return active_rows(board=board, user_id=user_id, day=day).filter(
        Q(reason=ContributionReason.CHECKIN) | Q(reason=ContributionReason.VALUE)).exists()

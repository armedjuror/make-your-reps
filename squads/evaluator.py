"""
Day evaluation engine.

One Celery beat job (every 15 minutes) evaluates any squad whose local day has
passed its late-log cutoff (10:00 next day, board timezone, configurable) and
any challenge participant whose own day has. Idempotent per (board, date) and
(participant, date): the DayResult / ChallengeDay row is the lock.

Streak rules:
* Counted members = active members who joined before that day, minus members
  on an Off day or away. Light and Disrupted days count as in.
* A member is in when all their assigned core habits are done that day.
* The day survives if members in / counted >= threshold (2 members: 100%,
  3+: 70%, admin-configurable). Changes apply from the next day.
* Streak and heatmap only run once the squad has 2+ active members.
* A member's first day doesn't count against the squad.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from board.models import DayMode, DayPlan, Habit, HabitLog, HabitStatus
from squads import items
from squads.events import track
from squads.ledger import active_rows, points_by_user
from squads.models import (
    Board, BoardStatus, BoardType, Contribution, ContributionReason as R, DayResult, DayStatus, FeedItem,
    FocusAttendance, FocusSession, FocusStatus, LeaderboardWeek, MembershipStatus, Nudge, SquadGoal, SquadStreak,
)

logger = logging.getLogger(__name__)

POINTS = {
    R.CORE_DONE: 10,
    R.DAY_SURVIVED: 5,
    R.STREAK_SAVER: 5,
    R.FOCUS: 15,
    R.FOCUS_HOST: 5,
    R.NUDGE: 3,
}
GOAL_POINTS_CAP = 10   # per member per day


def week_start(day):
    return day - timedelta(days=day.weekday())   # Monday


def last_closed_day(board, now=None):
    """The latest day whose cutoff has passed in board time."""
    now = now or timezone.now()
    local_today = board.local_today(now)
    yesterday = local_today - timedelta(days=1)
    return yesterday if now >= board.cutoff_for(yesterday) else yesterday - timedelta(days=1)


def streak_start_day(board):
    """First day the squad had 2+ active members (streak, heatmap and points start there)."""
    joins = sorted(m.joined_day() for m in board.memberships.filter(status=MembershipStatus.ACTIVE))
    return joins[1] if len(joins) >= 2 else None


# ──────────────────────────────────────
# Members' state for a day
# ──────────────────────────────────────

def _scheduled(habit, day):
    return not habit.frequency or day.weekday() in habit.frequency


def core_habits_for(board, user_id, day):
    out = []
    for h in Habit.objects.filter(board=board, status=HabitStatus.ACTIVE.value).prefetch_related('assignees'):
        created = board.local_now(h.created_at).date()
        if created > day or not _scheduled(h, day):
            continue
        rule = items.rule_for(h, day)
        if rule['is_core'] and (not rule['assignees'] or user_id in rule['assignees']):
            out.append(h)
    return out


def member_state(board, membership, day):
    """('in' | 'out' | 'away' | 'off' | 'first_day' | 'none', completed_at or None, auto_in)."""
    user_id = membership.user_id
    if membership.is_away_on(day):
        return 'away', None, False
    plan = DayPlan.objects.filter(user_id=user_id, date=day).first()
    if plan and plan.source == 'travel':
        return 'off', None, False
    cores = core_habits_for(board, user_id, day)
    if not cores:
        return 'none', None, False
    if plan and plan.mode in (DayMode.LIGHT, DayMode.DISRUPTED):
        return 'in', None, True
    done_at = []
    for h in cores:
        copy = items.linked_copy(h, user_id)
        log = HabitLog.objects.filter(habit=copy, date=day, is_done=True).first() if copy else None
        if log and (log.logged_at or log.updated_at) > board.cutoff_for(day):
            log = None   # logged after the day closed for the squad
        if not log:
            state = 'first_day' if membership.joined_day() == day else 'out'
            return state, None, False
        done_at.append(log.logged_at or log.updated_at)
    return 'in', max(done_at), False


def day_snapshot(board, day):
    """Current numbers for a day (used live for at-risk alerts and the slide-over)."""
    states = {}
    for m in board.memberships.filter(status=MembershipStatus.ACTIVE):
        if m.joined_day() > day:
            continue   # not a member yet that day
        states[m.user_id] = member_state(board, m, day)
    # 'first_day' (joined that day and not in) is left out: it doesn't count against the squad
    counted = [u for u, (s, _, _) in states.items() if s in ('in', 'out')]
    members_in = [u for u in counted if states[u][0] == 'in']
    total_active = board.active_memberships().count()
    threshold = items.threshold_for(board, day, total_active)
    pct = round(100 * len(members_in) / len(counted)) if counted else 0
    return {
        'states': states, 'counted': counted, 'members_in': members_in, 'threshold': threshold,
        'pct': pct, 'survives': bool(counted) and pct >= threshold, 'has_core': any(
            s != 'none' for s, _, _ in states.values()),
    }


# ──────────────────────────────────────
# Squad day
# ──────────────────────────────────────

def _award(board, user_id, reason, day, points, source_type='day', source_id=None):
    if not points:
        return
    exists = active_rows(board=board, user_id=user_id, reason=reason, day=day, source_type=source_type,
                         source_id=source_id).exists()
    if not exists:
        Contribution.objects.create(board=board, user_id=user_id, reason=reason, day=day, points=points,
                                    source_type=source_type, source_id=source_id)


def evaluate_board_day(board, day):
    """Write DayResult, update the streak and award the day's points. Returns the DayResult or None."""
    if DayResult.objects.filter(board=board, day=day).exists():
        return None
    items.apply_due_rules(board, day)
    snap = day_snapshot(board, day)
    states = snap['states']
    counted, members_in = snap['counted'], snap['members_in']
    if not snap['has_core']:
        status = DayStatus.REST
    elif not counted:
        status = DayStatus.OFF
    else:
        status = DayStatus.SURVIVED if snap['survives'] else DayStatus.BELOW
    try:
        with transaction.atomic():
            streak, _ = SquadStreak.objects.select_for_update().get_or_create(board=board)
            if status == DayStatus.BELOW and streak.current > 0:
                status = DayStatus.BROKEN
            result = DayResult.objects.create(
                board=board, day=day, members_in=len(members_in), members_counted=len(counted),
                threshold_pct=snap['threshold'], survived=status == DayStatus.SURVIVED, status=status,
                details={str(u): s for u, (s, _, _) in states.items()},
            )
            if status == DayStatus.SURVIVED:
                streak.current += 1
                streak.best = max(streak.best, streak.current)
            elif status in (DayStatus.BROKEN, DayStatus.BELOW):
                streak.current = 0
            streak.last_evaluated_date = day
            streak.save()
            _award_day_points(board, day, snap, status)
    except IntegrityError:
        return None   # another worker got there first
    _award_focus_points(board, day)
    _award_nudge_points(board, day)
    _award_goal_points(board, day)
    refresh_leaderboard(board, day)
    if status in (DayStatus.SURVIVED, DayStatus.BROKEN):
        text = (f'Day survived: {len(members_in)}/{len(counted)} in · {streak.current}-day streak'
                if status == DayStatus.SURVIVED else f'Streak broken: {len(members_in)}/{len(counted)} in')
        FeedItem.objects.create(board=board, kind='day', text=text, ref={'day': day.isoformat()},
                                reactable=status == DayStatus.SURVIVED)
    track('day_evaluated', None, board_id=board.id, survived=status == DayStatus.SURVIVED, pct_in=snap['pct'],
          status=status)
    return result


def _award_day_points(board, day, snap, status):
    states, counted = snap['states'], snap['counted']
    real = [u for u in snap['members_in'] if not states[u][2] and states[u][1] is not None]
    for u in real:
        _award(board, u, R.CORE_DONE, day, POINTS[R.CORE_DONE])
    if status != DayStatus.SURVIVED:
        return
    for u in snap['members_in']:
        _award(board, u, R.DAY_SURVIVED, day, POINTS[R.DAY_SURVIVED])
    # Streak saver: the check-in that pushed the day over the threshold
    needed = next(k for k in range(1, len(counted) + 1) if 100 * k / len(counted) >= snap['threshold'])
    auto = [u for u in snap['members_in'] if states[u][2]]
    ordered = auto + sorted(real, key=lambda u: states[u][1])
    if len(ordered) >= needed and len(counted) > 1:
        saver = ordered[needed - 1]
        if saver in real:
            _award(board, saver, R.STREAK_SAVER, day, POINTS[R.STREAK_SAVER])


def _award_focus_points(board, day):
    for s in FocusSession.objects.filter(board=board, status=FocusStatus.DONE, quorum_met=True):
        if board.local_now(s.start_at).date() != day:
            continue
        for a in FocusAttendance.objects.filter(session=s, completed=True, user__isnull=False):
            _award(board, a.user_id, R.FOCUS, day, POINTS[R.FOCUS], 'focus', s.id)
        if s.host_id:
            _award(board, s.host_id, R.FOCUS_HOST, day, POINTS[R.FOCUS_HOST], 'focus', s.id)


def _award_nudge_points(board, day):
    for n in Nudge.objects.filter(board=board, day=day, converted_at__isnull=False):
        _award(board, n.from_user_id, R.NUDGE, day, POINTS[R.NUDGE], 'nudge', n.id)


def _award_goal_points(board, day):
    for goal in SquadGoal.objects.filter(board=board, period_start__lte=day, period_end__gte=day):
        period_days = max(1, (goal.period_end - goal.period_start).days + 1)
        daily_needed = Decimal(goal.target) / period_days if goal.target else Decimal(1)
        rows = (active_rows(goal=goal, day=day, reason=R.VALUE).values('user_id').annotate(v=Sum('value')))
        for r in rows:
            if not r['user_id'] or not r['v'] or daily_needed <= 0:
                continue
            pts = min(GOAL_POINTS_CAP, int(round(10 * float(r['v']) / float(daily_needed))))
            _award(board, r['user_id'], R.GOAL, day, pts, 'goal', goal.id)


def refresh_leaderboard(board, day):
    """Materialise the week's totals; once Sunday is evaluated, crown the MVP."""
    start = week_start(day)
    end = start + timedelta(days=6)
    totals = points_by_user(board, start, end)
    for user_id, pts in totals.items():
        if user_id is None:
            continue
        LeaderboardWeek.objects.update_or_create(board=board, week_start=start, user_id=user_id,
                                                 defaults={'points': pts})
    if day >= end and totals:
        best = max((p for u, p in totals.items() if u), default=0)
        if best > 0:
            LeaderboardWeek.objects.filter(board=board, week_start=start).update(is_mvp=False)
            LeaderboardWeek.objects.filter(board=board, week_start=start, points=best).update(is_mvp=True)


def evaluate_board(board, now=None):
    """Evaluate every closed, not yet evaluated day for one squad."""
    start = streak_start_day(board)
    if start is None or board.status == BoardStatus.ARCHIVED:
        return []
    last = last_closed_day(board, now)
    streak = SquadStreak.objects.filter(board=board).first()
    day = max(start, streak.last_evaluated_date + timedelta(days=1)) if streak and streak.last_evaluated_date else start
    day = max(day, last - timedelta(days=30))   # never backfill more than a month at once
    out = []
    while day <= last:
        r = evaluate_board_day(board, day)
        if r:
            out.append(r)
        day += timedelta(days=1)
    return out


def evaluate_all(now=None):
    done = 0
    for board in Board.objects.filter(type=BoardType.SQUAD).exclude(status=BoardStatus.ARCHIVED):
        try:
            done += len(evaluate_board(board, now))
        except Exception:
            logger.exception('Evaluating squad %s failed', board.id)
    from squads import challenges
    done += challenges.evaluate_all(now)
    return done

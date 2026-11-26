"""Plain-dict serializers for the squads API."""
from datetime import timedelta

from django.utils import timezone

from board.models import Habit, HabitStatus, Metric, Task
from squads import items
from squads.evaluator import day_snapshot, streak_start_day, week_start
from squads.ledger import goal_progress, points_by_user
from squads.models import (
    BoardType, ChallengeParticipant, FocusSession, FocusStatus, ItemOptOut, MembershipStatus, ParticipantStatus,
    SquadGoal,
)


def member_dict(board, m, state=None):
    return {
        'user_id': m.user_id, 'name': items.display_name(m.user), 'role': m.role,
        'initials': ''.join(w[0] for w in items.display_name(m.user).split()[:2]).upper(),
        'joined_at': m.joined_at.isoformat(), 'away_until': m.away_until.isoformat() if m.away_until else None,
        'state': state,
    }


def board_summary(board, user_id, now=None):
    """Dock tile / Squads page card."""
    now = now or timezone.now()
    today = board.local_today(now)
    streak = getattr(board, 'streak', None)
    active = board.active_memberships().count()
    started = streak_start_day(board) is not None
    snap = day_snapshot(board, today) if started else None
    my_state = snap['states'].get(user_id, ('none',))[0] if snap else None
    at_risk = bool(snap and snap['counted'] and not snap['survives'] and board.local_now(now).hour >= 12)
    me = board.memberships.filter(user_id=user_id).first()
    return {
        'id': board.id, 'type': board.type, 'name': board.name, 'emoji': board.emoji, 'status': board.status,
        'members': active, 'streak': streak.current if streak else 0, 'best_streak': streak.best if streak else 0,
        'started': started, 'my_state': my_state, 'at_risk': at_risk,
        'pending_me': my_state == 'out', 'in_today': len(snap['members_in']) if snap else 0,
        'counted_today': len(snap['counted']) if snap else 0, 'pct_today': snap['pct'] if snap else 0,
        'threshold': snap['threshold'] if snap else board.threshold_pct(active),
        'role': me.role if me else None, 'muted': me.muted if me else False,
        'needs_ack': bool(me and me.added_directly and not me.add_acknowledged),
        'added_by': items.display_name(me.added_by) if me and me.added_by_id else None,
    }


def urgency(summary):
    """Right dock order: at risk + you pending, then active today, then the rest."""
    if summary['at_risk'] and summary['pending_me']:
        return 0
    if summary['in_today']:
        return 1
    return 2


def habit_dict(h, user_id, day):
    rule = items.rule_for(h, day)
    copy = items.linked_copy(h, user_id)
    opted_out = ItemOptOut.objects.filter(habit=h, user_id=user_id).exists()
    return {
        'id': h.id, 'habit': h.habit, 'detail': h.detail, 'frequency': h.frequency,
        'notify_at': h.notify_at.isoformat() if h.notify_at else None, 'is_core': rule['is_core'],
        'assignees': rule['assignees'], 'assigned_to_me': not rule['assignees'] or user_id in rule['assignees'],
        'pending_rule': _pending_rule(h, day), 'my_copy': copy.id if copy else None,
        'my_reminder': copy.notify_at.isoformat() if copy and copy.notify_at else None,
        'opted_out': opted_out, 'steps': [{'name': s.name, 'target': s.target} for s in h.steps.all()],
    }


def _pending_rule(h, day):
    hist = (h.board.settings or {}).get('rule_history', {}).get(str(h.id), [])
    future = [e for e in hist if e['from'] > day.isoformat()]
    return future[-1] if future else None


def tracker_dict(m, user_id):
    copy = items.linked_copy(m, user_id)
    return {'id': m.id, 'name': m.name, 'unit': m.unit, 'kind': m.kind, 'my_copy': copy.id if copy else None}


def todo_dict(t):
    return {
        'id': t.id, 'task_name': t.task_name, 'deadline': t.deadline.isoformat() if t.deadline else None,
        'is_done': t.is_done, 'completion_mode': t.completion_mode, 'assignee': t.assignee_id,
        'assignee_name': items.display_name(t.assignee) if t.assignee_id else None,
        'completed_by': items.display_name(t.completed_by) if t.completed_by_id else None,
        'created_by': t.user_id,
    }


def goal_dict(goal, today):
    total, by_user = goal_progress(goal)
    days_left = max(0, (goal.period_end - today).days + 1)
    remaining = max(0, float(goal.target) - float(total))
    from django.contrib.auth.models import User
    users = {u.id: u for u in User.objects.filter(id__in=[u for u in by_user if u])}
    members = {m.user_id: m for m in goal.board.memberships.all()}
    period_days = max(1, (goal.period_end - goal.period_start).days + 1)
    shares = []
    for uid, v in sorted(by_user.items(), key=lambda kv: -kv[1]):
        m = members.get(uid)
        joined = goal.board.local_now(m.joined_at).date() if m else goal.period_start
        span = max(1, (goal.period_end - max(goal.period_start, joined)).days + 1)
        shares.append({
            'user_id': uid, 'name': items.member_label(goal.board, users.get(uid)), 'value': float(v),
            # Late joiners: their fair share is pro-rated from the join date
            'fair_share': round(float(goal.target) * span / period_days / max(1, len(members)), 1),
        })
    return {
        'id': goal.id, 'title': goal.title, 'unit': goal.unit, 'aggregation': goal.aggregation,
        'target': float(goal.target), 'total': round(float(total), 2),
        'pct': min(100, round(100 * float(total) / float(goal.target))) if goal.target else 0,
        'period_start': goal.period_start.isoformat(), 'period_end': goal.period_end.isoformat(),
        'pace_per_day': round(remaining / days_left, 1) if days_left else None, 'days_left': days_left,
        'tracker': goal.tracker_id, 'habit': goal.habit_id, 'shares': shares,
    }


def leaderboard(board, viewer_id, week=None, history_start=None):
    today = board.local_today()
    ws = week or week_start(today)
    if history_start and ws < history_start:
        return {'week_start': ws.isoformat(), 'hidden': True, 'rows': [], 'team_score': 0}
    totals = points_by_user(board, ws, ws + timedelta(days=6))
    from django.contrib.auth.models import User
    from squads.models import LeaderboardWeek
    mvp_ids = set(LeaderboardWeek.objects.filter(board=board, week_start=ws, is_mvp=True).values_list('user_id', flat=True))
    users = {u.id: u for u in User.objects.filter(id__in=[u for u in totals if u])}
    rows = [{'user_id': uid, 'name': items.member_label(board, users.get(uid)), 'points': pts,
             'mvp': uid in mvp_ids, 'me': uid == viewer_id}
            for uid, pts in sorted(totals.items(), key=lambda kv: -kv[1])]
    # Former members' points stay in the team score
    return {'week_start': ws.isoformat(), 'week_end': (ws + timedelta(days=6)).isoformat(),
            'team_score': sum(totals.values()), 'rows': rows, 'resets': 'Monday 00:00 squad time'}


def heatmap(board, start, end, history_start=None):
    from squads.models import DayResult
    results = {r.day: r for r in DayResult.objects.filter(board=board, day__gte=start, day__lte=end)}
    begin = streak_start_day(board)
    today = board.local_today()
    cells = []
    d = start
    while d <= end:
        r = results.get(d)
        if history_start and d < history_start:
            cell = {'day': d.isoformat(), 'status': 'hidden'}
        elif r:
            cell = {'day': d.isoformat(), 'status': r.status, 'pct': r.pct_in, 'in': r.members_in,
                    'counted': r.members_counted, 'threshold': r.threshold_pct}
        elif begin is None or d < begin:
            cell = {'day': d.isoformat(), 'status': 'pre_start'}
        elif d >= today - timedelta(days=1):
            cell = {'day': d.isoformat(), 'status': 'open'}
        else:
            cell = {'day': d.isoformat(), 'status': 'pending'}
        cells.append(cell)
        d += timedelta(days=1)
    return cells


def next_focus(board):
    s = FocusSession.objects.filter(board=board, status__in=[FocusStatus.SCHEDULED, FocusStatus.LIVE],
                                    start_at__gte=timezone.now() - timedelta(hours=4)).order_by('start_at').first()
    return {'id': s.id, 'title': s.title, 'start_at': s.start_at.isoformat(), 'blocks': s.blocks,
            'block_minutes': s.block_minutes, 'status': s.status, 'room_url': f'/squads/focus/{s.id}/room/'} if s else None


def today_panel(board, user_id):
    """Slide-over: who's in today, nudge buttons, goal bar, next focus session."""
    today = board.local_today()
    started = streak_start_day(board) is not None
    snap = day_snapshot(board, today)
    members = []
    from squads.models import Nudge
    nudged = set(Nudge.objects.filter(board=board, from_user_id=user_id, day=today).values_list('to_user_id', flat=True))
    pending_items = {}
    for m in board.active_memberships().select_related('user'):
        state = snap['states'].get(m.user_id, ('none',))[0]
        d = member_dict(board, m, state)
        d['nudged'] = m.user_id in nudged
        if state == 'out':
            from squads.evaluator import core_habits_for
            missing = [h.habit for h in core_habits_for(board, m.user_id, today)
                       if not _done_today(h, m.user_id, today)]
            d['pending'] = missing
        members.append(d)
    goal = SquadGoal.objects.filter(board=board, period_end__gte=today).order_by('period_end').first()
    me_state = snap['states'].get(user_id, ('none',))[0]
    return {
        'day': today.isoformat(), 'started': started, 'members': members, 'in': len(snap['members_in']),
        'counted': len(snap['counted']), 'pct': snap['pct'], 'threshold': snap['threshold'],
        'survives': snap['survives'], 'me': me_state, 'can_nudge': me_state == 'in',
        'goal': goal_dict(goal, today) if goal else None, 'next_focus': next_focus(board),
        'invite_prompt': None if started else 'Invite 1 friend to start your streak.',
    }


def _done_today(h, user_id, day):
    from board.models import HabitLog
    copy = items.linked_copy(h, user_id)
    return bool(copy and HabitLog.objects.filter(habit=copy, date=day, is_done=True).exists())


def board_detail(board, user_id):
    today = board.local_today()
    summary = board_summary(board, user_id)
    members = [member_dict(board, m) for m in board.active_memberships().select_related('user').order_by('joined_at')]
    return {
        **summary,
        'timezone': board.timezone, 'template': board.template,
        'settings': {
            'streak_threshold_pct': board.setting('streak_threshold_pct'),
            'late_log_cutoff_hour': board.setting('late_log_cutoff_hour'),
            'pending_threshold': next((e for e in (board.settings or {}).get('threshold_history', [])
                                       if e['from'] > today.isoformat()), None),
        },
        'member_list': members,
        'habits': [habit_dict(h, user_id, today) for h in Habit.objects.filter(
            board=board, status=HabitStatus.ACTIVE.value).prefetch_related('assignees', 'steps')],
        'trackers': [tracker_dict(m, user_id) for m in Metric.objects.filter(board=board)],
        'todos': [todo_dict(t) for t in Task.objects.filter(board=board, is_deleted=False)
                  .select_related('assignee', 'completed_by').order_by('is_done', 'deadline', 'id')],
        'my_away_until': next((m['away_until'] for m in members if m['user_id'] == user_id), None),
    }


def challenge_summary_for_user(user_id):
    out = []
    for p in ChallengeParticipant.objects.filter(user_id=user_id).exclude(
            status=ParticipantStatus.REMOVED).select_related('challenge__board'):
        ch = p.challenge
        if ch.ended and ch.end_date < timezone.localdate() - timedelta(days=7):
            continue
        from squads.challenges import progress
        pr = progress(ch, p)
        out.append({'id': ch.board_id, 'type': BoardType.CHALLENGE, 'name': ch.title, 'emoji': ch.board.emoji,
                    'slug': ch.slug, 'status': p.status, 'day': pr['day'], 'days': ch.days,
                    'at_risk': p.status == 'active' and not pr['done_today'] and ch.phase() == 'active'
                    and timezone.localtime().hour >= 18,
                    'pending_me': p.status == 'active' and not pr['done_today'] and ch.phase() == 'active',
                    'in_today': 1 if pr['done_today'] else 0, 'streak': pr['days_done'], 'members': None})
    return out

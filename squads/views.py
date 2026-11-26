"""
Squads JSON API (mounted at /squads/api/). Session auth like the rest of the
app (Bearer tokens via AuthMiddleware); CSRF is enforced for cookie requests.
"""
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib.auth.models import User
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_time

from board.models import Friend, Habit, HabitStatus, Metric, Task
from squads import challenges as ch_mod, core, flags, focus as focus_mod, items, limits, safety, share
from squads import serializers as S
from squads.challenges import ChallengeError
from squads.core import SquadError
from squads.events import track
from squads.focus import FocusError
from squads.limits import LimitBlocked
from squads.models import (
    REACTION_EMOJIS, Board, BoardType, Challenge, FeedItem, FocusSession, MemberSuggestion, NotificationLog,
    NotificationPrefs, PushSubscription, Reaction, SquadGoal,
)
from squads.scoping import can_edit, can_log, can_view, member_board_ids

logger = logging.getLogger(__name__)


# ──────────────────────────────────────
# Plumbing
# ──────────────────────────────────────

def ok(data=None, status=200, **extra):
    return JsonResponse({'status': 'success', 'data': data, **extra}, status=status)


def fail(error, status=400, **extra):
    return JsonResponse({'status': 'failed', 'error': error, **extra}, status=status)


def api(methods=('GET',), flag='squads'):
    def deco(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return fail('Method not allowed', 405)
            if flag and not flags.enabled(flag):
                return fail('This feature is not available yet', 404)
            user_id = request.session.get('user_id')
            if not user_id:
                return fail('Not authenticated', 401)
            try:
                data = json.loads(request.body or b'{}') if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') else {}
            except ValueError:
                return fail('Invalid JSON')
            if not isinstance(data, dict):
                return fail('Expected a JSON object')
            try:
                return fn(request, user_id, data, *args, **kwargs)
            except LimitBlocked as e:
                return JsonResponse(e.payload(), status=402)
            except SquadError as e:
                return fail(str(e), e.status)
            except (ChallengeError, FocusError, ValueError) as e:
                return fail(str(e))
            except (Board.DoesNotExist, Habit.DoesNotExist, Metric.DoesNotExist, Task.DoesNotExist,
                    SquadGoal.DoesNotExist, FocusSession.DoesNotExist, MemberSuggestion.DoesNotExist):
                return fail('Not found', 404)
        return wrapper
    return deco


def _board(board_id, user_id, types=(BoardType.SQUAD,)):
    board = get_object_or_404(Board, pk=board_id, type__in=types)
    if not can_view(board, user_id):
        raise SquadError('Not found', 404)
    return board


def _need_edit(board, user_id):
    if not can_edit(board, user_id):
        raise SquadError('Only squad admins can do that' if board.is_writable else 'This squad is read-only', 403)


def _need_log(board, user_id):
    if not can_log(board, user_id):
        raise SquadError('This squad is read-only' if not board.is_writable else 'Not a member', 403)


def _date(value, field='date'):
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f'{field} must be YYYY-MM-DD')


def _dt(value, board=None, field='start_at'):
    if not value:
        raise ValueError(f'{field} is required')
    dt = parse_datetime(str(value))
    if dt is None:
        raise ValueError(f'{field} must be an ISO date-time')
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=board.tz) if board else timezone.make_aware(dt)
    return dt


def _decimal(value, field):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f'{field} must be a number')


def _time(value):
    return parse_time(str(value)) if value else None


# ──────────────────────────────────────
# Boards
# ──────────────────────────────────────

@api(('GET', 'POST'))
def boards(request, user_id, data):
    if request.method == 'GET':
        squads_ = Board.objects.filter(id__in=member_board_ids(user_id, (BoardType.SQUAD,))).select_related('streak')
        rows = [S.board_summary(b, user_id) for b in squads_]
        if flags.enabled('challenges'):
            rows += S.challenge_summary_for_user(user_id)
        rows.sort(key=lambda r: (S.urgency(r), (r['name'] or '').lower()))
        return ok(rows, flags=flags.all_flags())
    focus = data.get('focus') or None
    if focus and focus.get('start_at'):
        focus = {**focus, 'start_at': _dt(focus['start_at'])}
    habits = []
    for h in data.get('habits') or []:
        habits.append({**h, 'notify_at': _time(h.get('notify_at'))})
    board = core.create_squad(user_id, name=data.get('name', ''), template=data.get('template', 'custom'),
                              emoji=data.get('emoji', ''), tz=data.get('timezone'), habits=habits,
                              tracker=data.get('tracker') or None, focus=focus)
    return ok(S.board_detail(board, user_id), status=201)


@api()
def template(request, user_id, data, name):
    return ok(items.template_suggestions(name))


@api(('GET', 'PATCH', 'DELETE'))
def board(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if request.method == 'GET':
        items.apply_due_rules(b)
        return ok(S.board_detail(b, user_id))
    if request.method == 'PATCH':
        core.update_settings(b, user_id, data)
        return ok(S.board_detail(b, user_id))
    core.delete_squad(b, user_id, data.get('confirm_name'))
    return ok({'deleted': True})


@api(('POST',))
def archive(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    (core.unarchive if data.get('restore') else core.archive)(b, user_id)
    return ok({'status': b.status})


@api(('GET', 'POST', 'DELETE'))
def invite(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if request.method == 'DELETE':
        core.revoke_invites(b, user_id)
        return ok({'revoked': True})
    inv = core.current_invite(b, user_id, regenerate=request.method == 'POST' and data.get('regenerate'))
    url = share.absolute(f'/j/{inv.token}/')
    if request.method == 'POST' and data.get('channel'):
        track('invite_link_shared', user_id, board_id=b.id, channel=str(data['channel'])[:20])
    text = f"Join my squad {b.emoji} {b.name} on makeyourreps: {url}"
    return ok({'token': inv.token, 'url': url, 'expires_at': inv.expires_at.isoformat(),
               'whatsapp': f'https://wa.me/?text={__import__("urllib.parse").parse.quote(text)}', 'text': text})


@api(('GET', 'POST'))
def members(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if request.method == 'GET':
        friends = Friend.objects.filter(user_id=user_id).select_related('friend')
        in_squad = set(b.active_memberships().values_list('user_id', flat=True))
        hidden = safety.hidden_user_ids(user_id)
        return ok({
            'members': [S.member_dict(b, m) for m in b.active_memberships().select_related('user')],
            'addable_friends': [{'user_id': f.friend_id, 'name': items.display_name(f.friend)}
                                for f in friends if f.friend_id not in in_squad and f.friend_id not in hidden],
        })
    target = int(data.get('user_id') or 0)
    if can_edit(b, user_id):
        core.add_friend_directly(b, user_id, target)
        return ok({'added': True}, status=201)
    core.suggest_friend(b, user_id, target)
    return ok({'suggested': True}, status=201)


@api(('PATCH', 'DELETE'))
def member(request, user_id, data, board_id, member_id):
    b = _board(board_id, user_id)
    if request.method == 'DELETE':
        core.remove_member(b, user_id, member_id)
        return ok({'removed': True})
    core.set_role(b, user_id, member_id, data.get('role'))
    return ok({'role': data.get('role')})


@api(('POST',))
def transfer(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    core.transfer_ownership(b, user_id, int(data.get('user_id') or 0))
    return ok({'owner': b.owner_id})


@api(('POST',))
def leave(request, user_id, data, board_id):
    b = _board(board_id, user_id, (BoardType.SQUAD, BoardType.CHALLENGE))
    core.leave(b, user_id, quiet=True)
    return ok({'left': True})


@api(('POST',))
def acknowledge(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    core.acknowledge_add(b, user_id, stay=bool(data.get('stay', True)))
    return ok({'stay': bool(data.get('stay', True))})


@api(('GET', 'POST'))
def suggestions(request, user_id, data, board_id, suggestion_id=None):
    b = _board(board_id, user_id)
    if request.method == 'GET':
        return ok([{'id': s.id, 'user_id': s.user_id, 'name': items.display_name(s.user),
                    'suggested_by': items.display_name(s.suggested_by)}
                   for s in b.suggestions.filter(status='pending').select_related('user', 'suggested_by')])
    core.decide_suggestion(b, user_id, suggestion_id, bool(data.get('approve')))
    return ok({'decided': True})


@api(('GET', 'POST'), flag='squad_items')
def overlaps(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if request.method == 'GET':
        return ok(items.find_overlaps(b, user_id))
    items.resolve_overlap(b, user_id, data.get('type'), int(data['squad_item']), int(data['personal_item']),
                          data.get('choice'))
    return ok(items.find_overlaps(b, user_id))


@api(('POST',), flag='squad_items')
def opt(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if data.get('opt_in'):
        items.opt_in(b, user_id, int(data['habit']))
    else:
        items.opt_out(b, user_id, int(data['habit']))
    return ok({'habit': int(data['habit']), 'opted_out': not data.get('opt_in')})


# ──────────────────────────────────────
# Squad items
# ──────────────────────────────────────

@api(('GET', 'POST'), flag='squad_items')
def habits(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    today = b.local_today()
    if request.method == 'GET':
        return ok([S.habit_dict(h, user_id, today) for h in Habit.objects.filter(board=b, status=HabitStatus.ACTIVE.value)])
    _need_edit(b, user_id)
    name = (data.get('habit') or '').strip()
    if not name:
        raise ValueError('What is the habit?')
    h = items.create_squad_habit(b, user_id, habit=name, detail=data.get('detail', ''),
                                 frequency=data.get('frequency') or [], notify_at=_time(data.get('notify_at')),
                                 is_core=bool(data.get('is_core')), assignee_ids=data.get('assignees') or None,
                                 steps=data.get('steps') or [])
    return ok(S.habit_dict(h, user_id, today), status=201)


@api(('PATCH', 'DELETE'), flag='squad_items')
def habit(request, user_id, data, board_id, habit_id):
    b = _board(board_id, user_id)
    h = Habit.objects.get(pk=habit_id, board=b)
    # Shared habit contents: any member may edit them unless the squad restricts it to admins
    contents_by_members = (b.settings or {}).get('members_edit_contents', False)
    if request.method == 'DELETE':
        _need_edit(b, user_id)
        h.status = HabitStatus.DELETED.value
        h.save(update_fields=['status'])
        Habit.objects.filter(linked_squad_habit=h).update(linked_squad_habit=None)
        return ok({'deleted': True})
    content_keys = {'habit', 'detail', 'steps', 'frequency'}
    rule_keys = {'is_core', 'assignees'}
    if set(data) & rule_keys or not contents_by_members:
        _need_edit(b, user_id)
    else:
        _need_log(b, user_id)
    if set(data) & content_keys:
        for key in ('habit', 'detail', 'frequency'):
            if key in data:
                setattr(h, key, data[key])
        h.save()
        if 'steps' in data:
            from board.models import HabitStep
            HabitStep.objects.filter(habit=h).delete()
            for i, st in enumerate(data['steps'] or []):
                HabitStep.objects.create(habit=h, order=i, name=str(st.get('name', ''))[:120],
                                         target=str(st.get('target', ''))[:60])
        items.push_contents(h)
    if set(data) & rule_keys:
        # Core and assignee changes apply from the next day; no history is recomputed
        items.schedule_habit_rule(h, is_core=data.get('is_core'), assignee_ids=data.get('assignees'))
    return ok(S.habit_dict(h, user_id, b.local_today()))


@api(('GET', 'POST'), flag='squad_items')
def trackers(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if request.method == 'GET':
        return ok([S.tracker_dict(m, user_id) for m in Metric.objects.filter(board=b)])
    _need_edit(b, user_id)
    name = (data.get('name') or '').strip()
    if not name:
        raise ValueError('Name the tracker')
    kind = data.get('kind') if data.get('kind') in ('counter', 'additive', 'single') else 'additive'
    m = items.create_squad_tracker(b, user_id, name=name, unit=data.get('unit', ''), kind=kind)
    return ok(S.tracker_dict(m, user_id), status=201)


@api(('GET', 'POST'), flag='squad_items')
def todos(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if request.method == 'GET':
        return ok([S.todo_dict(t) for t in Task.objects.filter(board=b, is_deleted=False)
                   .select_related('assignee', 'completed_by')])
    _need_log(b, user_id)
    name = (data.get('task_name') or '').strip()
    if not name:
        raise ValueError('What needs doing?')
    mode = data.get('completion_mode') if data.get('completion_mode') in ('shared', 'assigned') else 'shared'
    assignee = int(data['assignee']) if data.get('assignee') else None
    if assignee and not b.active_memberships().filter(user_id=assignee).exists():
        raise ValueError('Assign it to a squad member')
    if mode == 'assigned' and not assignee:
        raise ValueError('Pick who it is assigned to')
    deadline = _dt(data['deadline'], b, 'deadline') if data.get('deadline') else None
    t = items.create_squad_todo(b, user_id, task_name=name, deadline=deadline, completion_mode=mode,
                                assignee_id=assignee)
    return ok(S.todo_dict(t), status=201)


# ──────────────────────────────────────
# Daily loop
# ──────────────────────────────────────

@api(flag='squads')
def today(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    return ok(S.today_panel(b, user_id))


@api(('POST',), flag='streaks')
def nudge(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    core.nudge(b, user_id, int(data.get('user_id') or 0))
    return ok({'nudged': True}, status=201)


@api(('POST',), flag='streaks')
def away(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    m = core.set_away(b, user_id, _date(data.get('until'), 'until'), _date(data.get('from'), 'from'))
    return ok({'away_until': m.away_until.isoformat() if m.away_until else None})


@api(('POST',))
def mute(request, user_id, data, board_id):
    b = _board(board_id, user_id, (BoardType.SQUAD, BoardType.CHALLENGE))
    m = core.set_muted(b, user_id, data.get('muted', True))
    return ok({'muted': m.muted})


@api(flag='streaks')
def heatmap(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    today = b.local_today()
    end = _date(request.GET.get('to')) or today
    start = _date(request.GET.get('from')) or end - timedelta(days=83)
    if (end - start).days > 400:
        raise ValueError('At most 400 days at a time')
    return ok(S.heatmap(b, start, end, limits.history_start(b.owner_id, today)))


@api(flag='streaks')
def heatmap_day(request, user_id, data, board_id, day):
    b = _board(board_id, user_id)
    d = _date(day)
    from squads.models import Contribution, DayResult
    r = DayResult.objects.filter(board=b, day=d).first()
    users = {u.id: u for u in User.objects.filter(id__in=[int(k) for k in (r.details if r else {})])}
    pts = {}
    for c in Contribution.objects.filter(board=b, day=d).values('user_id', 'points'):
        pts[c['user_id']] = pts.get(c['user_id'], 0) + c['points']
    return ok({
        'day': d.isoformat(), 'status': r.status if r else None, 'pct': r.pct_in if r else None,
        'members': [{'user_id': int(k), 'name': items.member_label(b, users.get(int(k))), 'state': v,
                     'points': pts.get(int(k), 0)} for k, v in (r.details if r else {}).items()],
    })


@api(('GET',))
def feed(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    hidden = safety.hidden_user_ids(user_id)
    rows = list(b.feed.exclude(user_id__in=hidden)[:60])
    reactions = {}
    for r in Reaction.objects.filter(board=b, target_type='feed', target_id__in=[f.id for f in rows]):
        bucket = reactions.setdefault(r.target_id, {'counts': {}, 'mine': None})
        bucket['counts'][r.emoji] = bucket['counts'].get(r.emoji, 0) + 1
        if r.user_id == user_id:
            bucket['mine'] = r.emoji
    return ok([{'id': f.id, 'kind': f.kind, 'text': f.text, 'late': f.late, 'created_at': f.created_at.isoformat(),
                'reactable': f.reactable, 'reactions': reactions.get(f.id, {'counts': {}, 'mine': None})}
               for f in rows], emojis=REACTION_EMOJIS)


@api(('POST', 'DELETE'))
def react(request, user_id, data, board_id, feed_id):
    b = _board(board_id, user_id)
    item = get_object_or_404(FeedItem, pk=feed_id, board=b, reactable=True)
    if request.method == 'DELETE':
        Reaction.objects.filter(user_id=user_id, target_type='feed', target_id=item.id).delete()
        return ok({'removed': True})
    emoji = data.get('emoji')
    if emoji not in REACTION_EMOJIS:
        raise ValueError('Pick one of the reactions')
    _, created = Reaction.objects.update_or_create(user_id=user_id, target_type='feed', target_id=item.id,
                                                   defaults={'board': b, 'emoji': emoji})
    if created and item.user_id and item.user_id != user_id:
        from squads.notify import notify
        notify(item.user_id, 'reaction', f'{items.display_name(User.objects.get(pk=user_id))} reacted {emoji}',
               item.text[:120], url=f'/board/#squad/{b.id}', board=b)
    return ok({'emoji': emoji})


# ──────────────────────────────────────
# Goals and leaderboard
# ──────────────────────────────────────

@api(('GET', 'POST'), flag='leaderboard')
def goals(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    today = b.local_today()
    if request.method == 'GET':
        return ok([S.goal_dict(g, today) for g in b.goals.all()])
    _need_edit(b, user_id)
    tracker = Metric.objects.get(pk=data['tracker'], board=b) if data.get('tracker') else None
    habit = Habit.objects.get(pk=data['habit'], board=b) if data.get('habit') else None
    if not (tracker or habit):
        raise ValueError('A goal counts a squad tracker or habit')
    agg = data.get('aggregation') if data.get('aggregation') in ('sum', 'count', 'avg') else 'sum'
    target = _decimal(data.get('target'), 'target')
    if target <= 0:
        raise ValueError('Target must be above zero')
    end = _date(data.get('period_end'), 'period_end') or core.date_end_of_year(today)
    start = _date(data.get('period_start'), 'period_start') or today
    if end < start:
        raise ValueError('The goal must end after it starts')
    g = SquadGoal.objects.create(
        board=b, tracker=tracker, habit=habit, aggregation=agg, target=target, period_start=start, period_end=end,
        unit=(tracker.unit if tracker else 'check-ins'),   # unit locked at creation
        title=(data.get('title') or f'Together we\'ll hit {target.normalize()} {(tracker.unit if tracker else "check-ins")} by {end:%d %b}')[:120],
        created_by_id=user_id)
    return ok(S.goal_dict(g, today), status=201)


@api(('DELETE',), flag='leaderboard')
def goal(request, user_id, data, board_id, goal_id):
    b = _board(board_id, user_id)
    _need_edit(b, user_id)
    SquadGoal.objects.get(pk=goal_id, board=b).delete()
    return ok({'deleted': True})


@api(flag='leaderboard')
def leaderboard(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    week = _date(request.GET.get('week'))
    from squads.evaluator import week_start
    hs = limits.history_start(b.owner_id, b.local_today())
    return ok(S.leaderboard(b, user_id, week_start(week) if week else None, hs))


# ──────────────────────────────────────
# Focus sessions
# ──────────────────────────────────────

@api(('GET', 'POST'), flag='focus')
def focus_sessions(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    if request.method == 'GET':
        now = timezone.now()
        qs = b.focus_sessions.select_related('host').prefetch_related('rsvps', 'attendance__user')
        upcoming = [focus_mod.serialize(s, user_id) for s in qs.filter(end_at_gte(now)).order_by('start_at')]
        past = [focus_mod.serialize(s, user_id) for s in qs.exclude(id__in=[u['id'] for u in upcoming])
                .exclude(status='cancelled').order_by('-start_at')[:30]]
        return ok({'upcoming': upcoming, 'past': past})
    linked = Habit.objects.get(pk=data['linked_habit'], board=b) if data.get('linked_habit') else None
    s = focus_mod.schedule(b, user_id, start_at=_dt(data.get('start_at'), b), block_minutes=int(data.get('block_minutes', 50)),
                           blocks=int(data.get('blocks', 1)), break_minutes=int(data.get('break_minutes', 10)),
                           title=data.get('title') or 'Focus session', linked_habit=linked)
    return ok(focus_mod.serialize(s, user_id), status=201)


def end_at_gte(now):
    """Sessions that are still upcoming or running (end computed from start + length)."""
    from django.db.models import Q
    return Q(status__in=['scheduled', 'live'], start_at__gte=now - timedelta(hours=8))


@api(('GET', 'PATCH', 'DELETE'), flag='focus')
def focus_session(request, user_id, data, board_id, session_id):
    b = _board(board_id, user_id)
    s = FocusSession.objects.get(pk=session_id, board=b)
    if request.method == 'DELETE':
        focus_mod.cancel(s, user_id)
    elif request.method == 'PATCH':
        changes = {k: data[k] for k in ('block_minutes', 'blocks', 'break_minutes', 'title') if k in data}
        if 'start_at' in data:
            changes['start_at'] = _dt(data['start_at'], b)
        focus_mod.edit(s, user_id, **changes)
    return ok(focus_mod.serialize(s, user_id))


@api(('POST',), flag='focus')
def focus_rsvp(request, user_id, data, session_id):
    s = get_object_or_404(FocusSession, pk=session_id)
    _board(s.board_id, user_id)
    focus_mod.set_rsvp(s, user_id, data.get('response'))
    return ok(focus_mod.serialize(s, user_id))


@api(('GET', 'POST'), flag='focus')
def focus_room(request, user_id, data, session_id):
    s = get_object_or_404(FocusSession.objects.select_related('board'), pk=session_id)
    _board(s.board_id, user_id)
    if request.method == 'POST':
        focus_mod.heartbeat(s, user_id, leaving=bool(data.get('leaving')))
        s.refresh_from_db()
    return ok(focus_mod.room_state(s, user_id))


# ──────────────────────────────────────
# Challenges
# ──────────────────────────────────────

def _challenge(slug, user_id):
    ch = get_object_or_404(Challenge.objects.select_related('board', 'host', 'parent_board'), slug=slug)
    if not ch_mod.can_see(ch, user_id):
        raise SquadError('Not found', 404)
    return ch


@api(('GET', 'POST'), flag='challenges')
def challenges(request, user_id, data):
    if request.method == 'GET':
        board_id = request.GET.get('board')
        if board_id:
            b = _board(int(board_id), user_id)
            qs = Challenge.objects.filter(parent_board=b)
        else:
            qs = Challenge.objects.filter(participants__user_id=user_id)
        return ok([ch_mod.serialize(c, user_id) for c in qs.select_related('board', 'host').distinct()])
    parent = _board(int(data['parent_board']), user_id) if data.get('parent_board') else None
    ch = ch_mod.create_challenge(
        user_id, title=(data.get('title') or '').strip() or 'Challenge', kind=data.get('kind', 'streak'),
        visibility=data.get('visibility', 'squad'), start_date=_date(data.get('start_date')) or timezone.localdate(),
        days=data.get('days'), end_date=_date(data.get('end_date')), item_name=data.get('item_name', ''),
        unit=data.get('unit', ''), daily_target=data.get('daily_target'), ladder_step=data.get('ladder_step'),
        skip_tokens=data.get('skip_tokens', 0), parent_board=parent, join_deadline=_date(data.get('join_deadline')),
        late_join=data.get('late_join', 'prorate'), team_mode=data.get('team_mode', 'sum'),
        tz=data.get('timezone'))
    ch_mod.join(ch, user_id, tz=data.get('timezone'),
                team_board=parent if ch.kind == 'versus' else None)
    return ok(ch_mod.serialize(ch, user_id), status=201)


@api(('GET', 'PATCH'), flag='challenges')
def challenge(request, user_id, data, slug):
    ch = _challenge(slug, user_id)
    if request.method == 'PATCH':
        ch_mod.update_challenge(ch, user_id, data)
    return ok({**ch_mod.serialize(ch, user_id), 'leaderboard': ch_mod.leaderboard(ch, user_id)})


@api(('POST',), flag='challenges')
def challenge_join(request, user_id, data, slug):
    ch = _challenge(slug, user_id)
    team = _board(int(data['team_board']), user_id) if data.get('team_board') else None
    if team is not None:
        ch_mod.enter_team(ch, team, user_id, tz=data.get('timezone'))
    else:
        ch_mod.join(ch, user_id, tz=data.get('timezone'))
    return ok(ch_mod.serialize(ch, user_id))


@api(('POST',), flag='challenges')
def challenge_continue(request, user_id, data, slug):
    ch = _challenge(slug, user_id)
    p = ch.participants.get(user_id=user_id)
    ch_mod.continue_unofficially(p)
    return ok(ch_mod.serialize(ch, user_id))


@api(('DELETE',), flag='challenges')
def challenge_participant(request, user_id, data, slug, member_id):
    ch = _challenge(slug, user_id)
    ch_mod.remove_participant(ch, user_id, member_id)
    return ok({'removed': True})


@api(flag='challenges')
def discover(request, user_id, data):
    soon, popular = ch_mod.discover()
    return ok({'starting_soon': [ch_mod.serialize(c, user_id) for c in soon],
               'most_joined': [ch_mod.serialize(c, user_id) for c in popular]})


# ──────────────────────────────────────
# Share
# ──────────────────────────────────────

@api(flag='share')
def recap(request, user_id, data, board_id):
    b = _board(board_id, user_id)
    from squads.evaluator import week_start
    ws = week_start(_date(request.GET.get('week')) or b.local_today())
    token = share.token_for('recap', b=b.id, w=ws.isoformat())
    return ok({**share.recap(b, ws), 'share_url': share.absolute(f'/s/recap/{token}/'),
               'image_url': share.absolute(f'/s/recap/{token}/image.png')})


@api(('POST',), flag='share')
def shared(request, user_id, data):
    """share_card_shared: the client reports a share to WhatsApp / Instagram / copy."""
    track('share_card_shared', user_id, type=str(data.get('type', ''))[:20], channel=str(data.get('channel', ''))[:20])
    return ok({'tracked': True})


# ──────────────────────────────────────
# Safety and data
# ──────────────────────────────────────

@api(('POST', 'DELETE'), flag='safety')
def block(request, user_id, data):
    target = int(data.get('user_id') or 0)
    if not User.objects.filter(pk=target).exists():
        return fail('Not found', 404)
    if request.method == 'DELETE':
        safety.unblock(user_id, target)
        return ok({'blocked': False})
    safety.block(user_id, target)
    return ok({'blocked': True})


@api(('POST',), flag='safety')
def report(request, user_id, data):
    r = safety.report(user_id, data.get('target_type'), data.get('target_id'), data.get('reason'))
    return ok({'id': r.id}, status=201)


@api(flag='safety')
def export(request, user_id, data):
    fmt = 'csv' if request.GET.get('format') == 'csv' else 'json'
    body, ctype = safety.export(user_id, fmt)
    resp = HttpResponse(body, content_type=ctype)
    resp['Content-Disposition'] = f'attachment; filename="squad-history.{fmt}"'
    return resp


# ──────────────────────────────────────
# Notifications
# ──────────────────────────────────────

@api(('GET', 'POST', 'DELETE'), flag='notifications')
def push_subscriptions(request, user_id, data):
    from django.conf import settings
    if request.method == 'GET':
        return ok({'vapid_public_key': settings.VAPID_PUBLIC_KEY,
                   'subscribed': PushSubscription.objects.filter(user_id=user_id).exists()})
    endpoint = (data.get('endpoint') or '').strip()
    if not endpoint.startswith('https://'):
        raise ValueError('A push endpoint is required')
    if request.method == 'DELETE':
        PushSubscription.objects.filter(user_id=user_id, endpoint=endpoint).delete()
        return ok({'subscribed': False})
    PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={
        'user_id': user_id, 'keys': data.get('keys') or {}, 'channel': data.get('channel', 'webpush')})
    return ok({'subscribed': True}, status=201)


@api(('GET', 'PUT'), flag='notifications')
def notification_prefs(request, user_id, data):
    from squads.notify import prefs_for
    p = prefs_for(user_id)
    if request.method == 'PUT':
        if 'timezone' in data and data['timezone']:
            from zoneinfo import ZoneInfo
            ZoneInfo(data['timezone'])
            p.timezone = data['timezone']
        if 'quiet_start' in data:
            p.quiet_start = _time(data['quiet_start'])
        if 'quiet_end' in data:
            p.quiet_end = _time(data['quiet_end'])
        if 'daily_cap' in data:
            cap = int(data['daily_cap'])
            if not 1 <= cap <= 30:
                raise ValueError('Daily cap must be 1-30')
            p.daily_cap = cap
        p.save()
    return ok({'timezone': p.timezone, 'quiet_start': p.quiet_start.isoformat() if p.quiet_start else None,
               'quiet_end': p.quiet_end.isoformat() if p.quiet_end else None, 'daily_cap': p.daily_cap})


@api(('GET', 'POST'))
def notifications(request, user_id, data):
    if request.method == 'POST':
        NotificationLog.objects.filter(user_id=user_id, read=False).update(read=True)
        return ok({'read': True})
    rows = NotificationLog.objects.filter(user_id=user_id).exclude(status='dropped')[:30]
    return ok([{'id': n.id, 'kind': n.kind, 'title': n.title, 'body': n.body, 'url': n.url, 'read': n.read,
                'created_at': n.created_at.isoformat()} for n in rows])


@api(('GET', 'POST'))
def plan(request, user_id, data):
    """Current plan, limits and the board to keep active after a downgrade."""
    if request.method == 'POST' and data.get('keep_board'):
        frozen = limits.apply_downgrade(user_id, keep_board_id=int(data['keep_board']))
        return ok({'read_only': frozen})
    keys = {k: limits.limit_for(user_id, k) for k in limits.LIMIT_KEYS}
    from squads.models import UserPlan
    state = UserPlan.objects.filter(user_id=user_id).first()
    return ok({'plan': limits.plan_of(user_id), 'hosted': limits.hosted(), 'limits': keys,
               'upgrade_trigger': state.upgrade_trigger if state else ''})

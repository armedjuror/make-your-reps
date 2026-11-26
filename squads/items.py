"""
Squad items and linking.

A squad habit or tracker is the shared definition (board = the squad). Each
member takes part through one personal item linked to it: the member's own
reminder time and timeline slot live on that copy, and one log on it counts
for the member and for the squad.

Rules:
* A personal item links to at most one squad item (one FK).
* A squad item has at most one linked item per member.
* A private personal item linked to a squad exposes only done / not done.
* Changes to core habits, assignees and the threshold apply from the next day.
"""
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from board.models import Habit, HabitStatus, HabitStep, Metric, Task
from squads.events import track
from squads.models import (
    Board, BoardMembership, BoardType, ChallengeParticipant, FeedItem, ItemOptOut, MembershipStatus,
)

# ──────────────────────────────────────
# Templates (B1)
# ──────────────────────────────────────

TEMPLATES = {
    'study': {
        'emoji': '📚',
        'habits': [
            {'habit': 'Solve 2 problems', 'is_core': True},
            {'habit': 'Revise yesterday\'s notes', 'is_core': False},
        ],
        'tracker': {'name': 'Problems solved', 'unit': 'problems', 'goal': 500},
        'focus': {'weekday': 5, 'hour': 7, 'block_minutes': 50, 'blocks': 2},
    },
    'fitness': {
        'emoji': '💪',
        'habits': [
            {'habit': 'Workout', 'is_core': True},
            {'habit': 'Stretch 10 minutes', 'is_core': False},
        ],
        'tracker': {'name': 'Minutes trained', 'unit': 'min', 'goal': 3000},
        'focus': None,
    },
    'family': {
        'emoji': '🏡',
        'habits': [
            {'habit': 'Read for 20 minutes', 'is_core': True},
            {'habit': 'No screens after 9 pm', 'is_core': False},
        ],
        'tracker': {'name': 'Pages read', 'unit': 'pages', 'goal': 2000},
        'focus': {'weekday': 6, 'hour': 18, 'block_minutes': 30, 'blocks': 1},
    },
    'custom': {'emoji': '✨', 'habits': [], 'tracker': None, 'focus': None},
}


def template_suggestions(template):
    """What the create form pre-fills: all editable or removable before saving."""
    t = TEMPLATES.get(template) or TEMPLATES['custom']
    return {'emoji': t['emoji'], 'habits': t['habits'], 'tracker': t['tracker'], 'focus': t['focus']}


# ──────────────────────────────────────
# Tags shown in Today
# ──────────────────────────────────────

def squad_tag(board):
    if board is None or board.type == BoardType.PERSONAL:
        return None
    tag = {'id': board.id, 'name': board.name, 'emoji': board.emoji, 'type': board.type}
    if board.type == BoardType.CHALLENGE and hasattr(board, 'challenge'):
        ch = board.challenge
        today = timezone.localdate()
        n = (today - ch.start_date).days + 1
        if 1 <= n <= ch.days:
            tag['label'] = f'Day {n}/{ch.days}'
    return tag


def squad_tag_for_habit(habit):
    if habit.board_id and habit.linked_squad_habit_id:
        return squad_tag(habit.linked_squad_habit.board)
    return None


def squad_tag_for_metric(metric):
    if metric.board_id and metric.linked_squad_tracker_id:
        return squad_tag(metric.linked_squad_tracker.board)
    return None


# ──────────────────────────────────────
# Rule changes that apply from the next day
# ──────────────────────────────────────

def _rules(board):
    board.settings = board.settings or {}
    return board.settings.setdefault('rule_history', {})


def schedule_habit_rule(habit, *, is_core=None, assignee_ids=None, effective=None):
    """Record a core / assignee change for the squad habit, effective tomorrow (board time)."""
    board = habit.board
    board.refresh_from_db(fields=['settings'])
    effective = effective or board.local_today() + timedelta(days=1)
    snapshot_initial_rules(habit)
    current = rule_for(habit, effective)
    hist = _rules(board).setdefault(str(habit.id), [])
    hist[:] = [e for e in hist if e['from'] != effective.isoformat()]   # last change that day wins
    hist.append({
        'from': effective.isoformat(),
        'is_core': current['is_core'] if is_core is None else bool(is_core),
        'assignees': current['assignees'] if assignee_ids is None else sorted(int(x) for x in assignee_ids),
    })
    hist.sort(key=lambda e: e['from'])
    board.save(update_fields=['settings'])


def schedule_threshold(board, pct, effective=None):
    board.refresh_from_db(fields=['settings'])
    effective = effective or board.local_today() + timedelta(days=1)
    board.settings = board.settings or {}
    board.settings.setdefault('threshold_initial', board.setting('streak_threshold_pct'))
    hist = board.settings.setdefault('threshold_history', [])
    hist[:] = [e for e in hist if e['from'] != effective.isoformat()]
    hist.append({'from': effective.isoformat(), 'pct': int(pct) if pct else None})
    hist.sort(key=lambda e: e['from'])
    board.save(update_fields=['settings'])


def snapshot_initial_rules(habit):
    """Keep the state before the first change, so earlier days evaluate with it."""
    board = habit.board
    board.settings = board.settings or {}
    init = board.settings.setdefault('rule_initial', {})
    if str(habit.id) not in init:
        init[str(habit.id)] = {'is_core': habit.is_core,
                               'assignees': sorted(habit.assignees.values_list('id', flat=True))}


def rule_for(habit, day):
    """{is_core, assignees} in force for ``habit`` on ``day``."""
    settings_ = habit.board.settings or {}
    hist = settings_.get('rule_history', {}).get(str(habit.id), [])
    applicable = [e for e in hist if e['from'] <= day.isoformat()]
    if applicable:
        return {'is_core': applicable[-1]['is_core'], 'assignees': applicable[-1]['assignees']}
    initial = settings_.get('rule_initial', {}).get(str(habit.id))
    if hist and initial:
        return dict(initial)
    return {'is_core': habit.is_core, 'assignees': sorted(habit.assignees.values_list('id', flat=True))}


def threshold_for(board, day, member_count):
    settings_ = board.settings or {}
    hist = settings_.get('threshold_history', [])
    applicable = [e for e in hist if e['from'] <= day.isoformat()]
    if applicable:
        pct = applicable[-1]['pct']
    elif hist:
        pct = settings_.get('threshold_initial')
    else:
        pct = board.setting('streak_threshold_pct')
    return int(pct) if pct else (100 if member_count <= 2 else 70)


def apply_due_rules(board, today=None):
    """Move scheduled changes whose day has come onto the habits themselves."""
    board.refresh_from_db(fields=['settings'])   # never act on (or save over) stale settings
    today = today or board.local_today()
    hist = (board.settings or {}).get('rule_history', {})
    for habit_id, entries in hist.items():
        due = [e for e in entries if e['from'] <= today.isoformat()]
        if not due:
            continue
        e = due[-1]
        habit = Habit.objects.filter(pk=int(habit_id), board=board).first()
        if not habit:
            continue
        changed = habit.is_core != e['is_core']
        if changed:
            habit.is_core = e['is_core']
            habit.save(update_fields=['is_core'])
        current = sorted(habit.assignees.values_list('id', flat=True))
        if current != e['assignees']:
            habit.assignees.set(e['assignees'])
            sync_habit_members(habit)
    th = [e for e in (board.settings or {}).get('threshold_history', []) if e['from'] <= today.isoformat()]
    if th and board.setting('streak_threshold_pct') != th[-1]['pct']:
        board.settings['streak_threshold_pct'] = th[-1]['pct']
        board.save(update_fields=['settings'])


# ──────────────────────────────────────
# Materialising members' linked items
# ──────────────────────────────────────

def _norm(name):
    return re.sub(r'[^a-z0-9]+', ' ', (name or '').lower()).strip()


def is_assigned(habit, user_id):
    ids = list(habit.assignees.values_list('id', flat=True))
    return not ids or user_id in ids


def linked_copy(squad_item, user_id):
    if isinstance(squad_item, Habit):
        return Habit.objects.filter(linked_squad_habit=squad_item, user_id=user_id,
                                    board__type=BoardType.PERSONAL).exclude(status=HabitStatus.DELETED.value).first()
    return Metric.objects.filter(linked_squad_tracker=squad_item, user_id=user_id,
                                 board__type=BoardType.PERSONAL).first()


def _copy_steps(src, dst):
    HabitStep.objects.filter(habit=dst).delete()
    HabitStep.objects.bulk_create([
        HabitStep(habit=dst, order=s.order, name=s.name, target=s.target, how_to=s.how_to, stage=s.stage)
        for s in src.steps.all()
    ])


def materialize_habit(squad_habit, user_id):
    """Give the member their linked copy (idempotent)."""
    existing = linked_copy(squad_habit, user_id)
    if existing:
        return existing
    if ItemOptOut.objects.filter(habit=squad_habit, user_id=user_id).exists():
        return None
    copy = Habit.objects.create(
        user_id=user_id, board=Board.personal_for(user_id),
        habit=squad_habit.habit, detail=squad_habit.detail, identity=squad_habit.identity or squad_habit.habit,
        frequency=list(squad_habit.frequency or []), notify_at=squad_habit.notify_at,
        linked_squad_habit=squad_habit,
    )
    _copy_steps(squad_habit, copy)
    try:
        from board.tasks import generate_timeline_for_new_item
        generate_timeline_for_new_item('habit', copy.id)
    except Exception:
        pass
    return copy


def materialize_tracker(squad_metric, user_id):
    existing = linked_copy(squad_metric, user_id)
    if existing:
        return existing
    return Metric.objects.create(
        user_id=user_id, board=Board.personal_for(user_id), name=squad_metric.name, unit=squad_metric.unit,
        kind=squad_metric.kind, direction=squad_metric.direction, target=squad_metric.target,
        quick_steps=list(squad_metric.quick_steps or []), linked_squad_tracker=squad_metric,
    )


def active_member_ids(board):
    return list(board.active_memberships().values_list('user_id', flat=True))


def sync_habit_members(squad_habit):
    """Assigned members get a copy; unassigned members' copies are unlinked and archived."""
    for uid in active_member_ids(squad_habit.board):
        if is_assigned(squad_habit, uid):
            materialize_habit(squad_habit, uid)
        else:
            copy = linked_copy(squad_habit, uid)
            if copy:
                copy.status = HabitStatus.COMPLETED.value
                copy.save(update_fields=['status'])


def sync_tracker_members(squad_metric):
    for uid in active_member_ids(squad_metric.board):
        materialize_tracker(squad_metric, uid)


def push_contents(squad_habit):
    """Shared contents (name, detail, steps) follow the squad habit; timing stays personal."""
    for copy in Habit.objects.filter(linked_squad_habit=squad_habit, board__type=BoardType.PERSONAL):
        copy.habit, copy.detail = squad_habit.habit, squad_habit.detail
        copy.save(update_fields=['habit', 'detail'])
        _copy_steps(squad_habit, copy)


@transaction.atomic
def create_squad_habit(board, creator_id, *, habit, detail='', frequency=None, notify_at=None,
                       is_core=False, assignee_ids=None, steps=None):
    h = Habit.objects.create(
        board=board, user_id=creator_id, habit=habit[:255], detail=detail or '', identity=habit[:255],
        frequency=frequency or [], notify_at=notify_at, is_core=is_core,
    )
    if assignee_ids:
        h.assignees.set(assignee_ids)
    for i, st in enumerate(steps or []):
        HabitStep.objects.create(habit=h, order=i, name=str(st.get('name', ''))[:120],
                                 target=str(st.get('target', ''))[:60])
    sync_habit_members(h)
    return h


@transaction.atomic
def create_squad_tracker(board, creator_id, *, name, unit='', kind='additive', target=None):
    m = Metric.objects.create(board=board, user_id=creator_id, name=name[:64], unit=unit[:16],
                              kind=kind, target=target)
    sync_tracker_members(m)
    return m


def create_squad_todo(board, creator_id, *, task_name, deadline=None, completion_mode='shared', assignee_id=None):
    t = Task.objects.create(board=board, user_id=creator_id, task_name=task_name, deadline=deadline,
                            completion_mode=completion_mode, assignee_id=assignee_id)
    try:
        from squads.tasks import generate_timeline_for_squad_todo
        generate_timeline_for_squad_todo(t.id)
    except Exception:
        pass
    return t


# ──────────────────────────────────────
# Overlaps on join (B5)
# ──────────────────────────────────────

def find_overlaps(board, user_id):
    """Similar personal habits / trackers (name + type match) not yet linked anywhere."""
    out = []
    personal_habits = list(Habit.objects.filter(
        board__owner_id=user_id, board__type=BoardType.PERSONAL, status=HabitStatus.ACTIVE.value,
        linked_squad_habit__isnull=True, is_system=False))
    for sh in Habit.objects.filter(board=board, status=HabitStatus.ACTIVE.value):
        if not is_assigned(sh, user_id) or linked_copy(sh, user_id):
            continue
        for ph in personal_habits:
            if _norm(ph.habit) == _norm(sh.habit):
                out.append({'type': 'habit', 'squad_item': sh.id, 'squad_name': sh.habit,
                            'personal_item': ph.id, 'personal_name': ph.habit})
                break
    personal_metrics = list(Metric.objects.filter(
        board__owner_id=user_id, board__type=BoardType.PERSONAL, linked_squad_tracker__isnull=True, is_system=False))
    for sm in Metric.objects.filter(board=board):
        if linked_copy(sm, user_id):
            continue
        for pm in personal_metrics:
            if _norm(pm.name) == _norm(sm.name) and (pm.unit or '') == (sm.unit or ''):
                out.append({'type': 'tracker', 'squad_item': sm.id, 'squad_name': sm.name,
                            'personal_item': pm.id, 'personal_name': pm.name})
                break
    return out


@transaction.atomic
def resolve_overlap(board, user_id, item_type, squad_item_id, personal_item_id, choice):
    """choice: link (count my item), adopt (my item takes the squad's setup), separate (keep both)."""
    if item_type == 'habit':
        squad_item = Habit.objects.get(pk=squad_item_id, board=board)
        personal = Habit.objects.get(pk=personal_item_id, board__owner_id=user_id, board__type=BoardType.PERSONAL)
    else:
        squad_item = Metric.objects.get(pk=squad_item_id, board=board)
        personal = Metric.objects.get(pk=personal_item_id, board__owner_id=user_id, board__type=BoardType.PERSONAL)
    if linked_copy(squad_item, user_id):
        raise ValueError('Already linked')
    if choice == 'separate':
        result = materialize_habit(squad_item, user_id) if item_type == 'habit' else materialize_tracker(squad_item, user_id)
    elif choice in ('link', 'adopt'):
        if item_type == 'habit':
            if personal.linked_squad_habit_id:
                raise ValueError('That habit is already linked to a squad')
            personal.linked_squad_habit = squad_item
            if choice == 'adopt':
                personal.habit, personal.detail = squad_item.habit, squad_item.detail
                personal.frequency = list(squad_item.frequency or [])
                _copy_steps(squad_item, personal)
            personal.save()
        else:
            if personal.linked_squad_tracker_id:
                raise ValueError('That tracker is already linked to a squad')
            personal.linked_squad_tracker = squad_item
            if choice == 'adopt':
                personal.name, personal.unit, personal.kind = squad_item.name, squad_item.unit, squad_item.kind
            personal.save()
        result = personal
    else:
        raise ValueError('Unknown choice')
    track('overlap_resolved', user_id, board_id=board.id, choice=choice)
    return result


def opt_out(board, user_id, squad_habit_id):
    habit = Habit.objects.get(pk=squad_habit_id, board=board)
    if rule_for(habit, board.local_today())['is_core']:
        raise ValueError("Core habits can't be opted out")
    ItemOptOut.objects.get_or_create(habit=habit, user_id=user_id)
    copy = linked_copy(habit, user_id)
    if copy:
        copy.linked_squad_habit = None
        copy.save(update_fields=['linked_squad_habit'])


def opt_in(board, user_id, squad_habit_id):
    habit = Habit.objects.get(pk=squad_habit_id, board=board)
    ItemOptOut.objects.filter(habit=habit, user_id=user_id).delete()
    return materialize_habit(habit, user_id)


def materialize_all(board, user_id, skip_overlaps=True):
    """Copies for every squad item the member takes on, except ones waiting on an overlap choice."""
    waiting = {(o['type'], o['squad_item']) for o in find_overlaps(board, user_id)} if skip_overlaps else set()
    for sh in Habit.objects.filter(board=board, status=HabitStatus.ACTIVE.value):
        if ('habit', sh.id) not in waiting and is_assigned(sh, user_id):
            materialize_habit(sh, user_id)
    for sm in Metric.objects.filter(board=board):
        if ('tracker', sm.id) not in waiting:
            materialize_tracker(sm, user_id)


# ──────────────────────────────────────
# Todos (C5)
# ──────────────────────────────────────

def check_todo_update(task, user_id, data):
    """None when allowed, else the reason. Closing follows completion mode; other edits need an admin."""
    from squads.scoping import can_close_todo, can_edit
    keys = set(k for k in data.keys() if k not in ('id',))
    if keys <= {'is_done'}:
        if can_close_todo(task, user_id):
            return None
        return 'Only the assignee can close this todo' if task.completion_mode == 'assigned' else 'Not a member'
    if can_edit(task.board, user_id) or task.user_id == user_id:
        return None
    return 'Only squad admins can edit this todo'


def todo_closed(task, user_id, done):
    task.completed_by_id = user_id if done else None
    Task.objects.filter(pk=task.pk).update(completed_by_id=task.completed_by_id)
    if done:
        from django.contrib.auth.models import User
        name = display_name(User.objects.filter(pk=user_id).first())
        FeedItem.objects.create(board=task.board, user_id=user_id, kind='todo_done',
                                text=f'{name} closed: {task.task_name[:200]}', ref={'task': task.id},
                                reactable=True)


def display_name(user):
    if user is None:
        return 'Former member'
    return (user.get_full_name() or user.first_name or user.username or 'Someone').strip()


def member_label(board, user):
    """'Former member' once someone has left or deleted their account."""
    if user is None:
        return 'Former member'
    m = BoardMembership.objects.filter(board=board, user=user).first()
    if m and m.status != MembershipStatus.ACTIVE:
        return 'Former member'
    return display_name(user)

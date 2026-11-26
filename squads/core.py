"""
Squads core: create from a template, invite link, direct add of accepted
friends, member suggestions, roles, away mode, nudges, leave, archive, delete.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from board.models import Friend
from squads import items, limits
from squads.events import track
from squads.models import (
    Board, BoardMembership, BoardStatus, BoardTemplate, BoardType, FeedItem, Invite, MemberSuggestion,
    MembershipStatus, Nudge, Role, SquadGoal, SquadStreak,
)
from squads.scoping import can_edit, is_member, membership


class SquadError(Exception):
    status = 400

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _forbid(msg='Only squad admins can do that'):
    return SquadError(msg, 403)


def owned_squads(user_id):
    return Board.objects.filter(owner_id=user_id, type=BoardType.SQUAD).exclude(status=BoardStatus.ARCHIVED)


# ──────────────────────────────────────
# Create (B1)
# ──────────────────────────────────────

def create_squad(owner, *, name, template=BoardTemplate.CUSTOM, emoji='', tz=None, habits=None, tracker=None,
                 focus=None):
    """
    ``habits``: [{habit, is_core, frequency?, notify_at?}], ``tracker``: {name, unit, goal, period_end?},
    ``focus``: {start_at (aware datetime), block_minutes, blocks}. All come from the template and the
    owner can edit or remove each before saving.
    """
    owner_id = getattr(owner, 'id', owner)
    name = (name or '').strip()[:80]
    if not name:
        raise SquadError('Give your squad a name')
    if template not in BoardTemplate.values:
        template = BoardTemplate.CUSTOM
    # Checked outside the transaction: the recorded upgrade_trigger must survive the raise
    limits.check(owner_id, 'squads_owned', owned_squads(owner_id).count())
    with transaction.atomic():
        return _create_squad(owner_id, name, template, emoji, tz, habits, tracker, focus)


def _create_squad(owner_id, name, template, emoji, tz, habits, tracker, focus):
    board = Board.objects.create(
        type=BoardType.SQUAD, name=name, owner_id=owner_id, template=template,
        emoji=(emoji or items.TEMPLATES[template]['emoji'])[:16],
        timezone=tz or Board.personal_for(owner_id).timezone,
    )
    BoardMembership.objects.create(board=board, user_id=owner_id, role=Role.OWNER)
    SquadStreak.objects.create(board=board)
    for h in habits or []:
        if not (h.get('habit') or '').strip():
            continue
        items.create_squad_habit(board, owner_id, habit=h['habit'].strip(), detail=h.get('detail', ''),
                                 frequency=h.get('frequency') or [], notify_at=h.get('notify_at'),
                                 is_core=bool(h.get('is_core')))
    if tracker and (tracker.get('name') or '').strip():
        metric = items.create_squad_tracker(board, owner_id, name=tracker['name'].strip(), unit=tracker.get('unit', ''))
        if tracker.get('goal'):
            today = board.local_today()
            end = tracker.get('period_end') or date_end_of_year(today)
            SquadGoal.objects.create(board=board, tracker=metric, unit=metric.unit, target=Decimal(str(tracker['goal'])),
                                     period_start=today, period_end=end, created_by_id=owner_id,
                                     title=f'Together we\'ll hit {tracker["goal"]} {metric.unit or metric.name}')
    if focus and focus.get('start_at'):
        from squads import focus as focus_mod
        focus_mod.schedule(board, owner_id, start_at=focus['start_at'], block_minutes=focus.get('block_minutes', 50),
                           blocks=focus.get('blocks', 1))
    track('squad_created', owner_id, template=template, member_count=1, board_id=board.id)
    return board


def date_end_of_year(today):
    return today.replace(month=12, day=31)


def next_weekday_at(board, weekday, hour):
    today = board.local_today()
    days = (weekday - today.weekday()) % 7 or 7
    return board.local_datetime(today + timedelta(days=days), time(hour, 0))


# ──────────────────────────────────────
# Invites (B2, B3)
# ──────────────────────────────────────

def current_invite(board, user_id, regenerate=False):
    if not is_member(board, user_id):
        raise _forbid('Not a member of this squad')
    inv = board.invites.filter(revoked=False, expires_at__gt=timezone.now()).order_by('-created_at').first()
    if regenerate and not can_edit(board, user_id):
        raise _forbid()
    if inv is None or regenerate:
        if regenerate and inv:
            board.invites.filter(revoked=False).update(revoked=True)
        inv = Invite.objects.create(board=board, created_by_id=user_id)
    return inv


def revoke_invites(board, user_id):
    if not can_edit(board, user_id):
        raise _forbid()
    board.invites.update(revoked=True)


def invite_preview(invite):
    board = invite.board
    members = list(board.active_memberships().select_related('user')[:8])
    streak = getattr(board, 'streak', None)
    from board.models import Habit, HabitStatus
    return {
        'name': board.name, 'emoji': board.emoji, 'member_count': board.active_memberships().count(),
        'members': [items.display_name(m.user) for m in members],
        'streak': streak.current if streak else 0,
        'items': list(Habit.objects.filter(board=board, status=HabitStatus.ACTIVE.value)
                      .values('habit', 'is_core')),
        'valid': invite.is_valid and board.is_writable,
    }


def _blocked_between(a, b):
    from squads.models import Block
    return Block.objects.filter(blocker_id=a, blocked_id=b).exists() or Block.objects.filter(
        blocker_id=b, blocked_id=a).exists()


def _blocked_with_members(board, user_id):
    from squads.models import Block
    ids = list(board.active_memberships().values_list('user_id', flat=True))
    return Block.objects.filter(blocker_id__in=ids, blocked_id=user_id).exists()


def _add_member(board, user_id, added_by=None, direct=False):
    if not board.is_writable:
        raise SquadError('This squad is read-only')
    m = membership(board, user_id)
    if m and m.status == MembershipStatus.ACTIVE:
        return m, False
    # Joining is never limited for the joiner; the owner's plan caps the size
    limits.check(board.owner_id, 'squad_members', board.active_memberships().count())
    with transaction.atomic():
        return _activate_member(board, user_id, m, added_by, direct)


def _activate_member(board, user_id, m, added_by, direct):
    if m:
        m.status, m.role, m.joined_at, m.left_at = MembershipStatus.ACTIVE, Role.MEMBER, timezone.now(), None
        m.added_by_id, m.added_directly, m.add_acknowledged = added_by, direct, not direct
        m.save()
    else:
        m = BoardMembership.objects.create(board=board, user_id=user_id, added_by_id=added_by,
                                           added_directly=direct, add_acknowledged=not direct)
    user = User.objects.get(pk=user_id)
    FeedItem.objects.create(board=board, user_id=user_id, kind='joined', text=f'{items.display_name(user)} joined')
    return m, True


def join_with_invite(token, user):
    inv = Invite.objects.select_related('board').filter(token=token).first()
    if inv is None or not inv.is_valid:
        raise SquadError('This invite link has expired. Ask for a new one.', 410)
    if _blocked_with_members(inv.board, user.id):
        raise SquadError('You can\'t join this squad', 403)
    m, created = _add_member(inv.board, user.id)
    if created:
        Invite.objects.filter(pk=inv.pk).update(uses=inv.uses + 1)
        method = 'otp' if not user.socialaccount_set.exists() else 'google'
        track('invite_accepted', user.id, board_id=inv.board_id, auth_method=method)
    overlaps = items.find_overlaps(inv.board, user.id)
    items.materialize_all(inv.board, user.id)
    return m, overlaps


def are_friends(a, b):
    return Friend.objects.filter(user_id=a, friend_id=b).exists()


def add_friend_directly(board, admin_id, friend_id):
    """B4: accepted friends only, blocked users can't be added; the friend sees Stay / Leave."""
    if not can_edit(board, admin_id):
        raise _forbid()
    if not are_friends(admin_id, friend_id):
        raise SquadError('You can only add accepted friends')
    if _blocked_between(admin_id, friend_id) or _blocked_with_members(board, friend_id):
        raise SquadError('You can\'t add this person', 403)
    m, created = _add_member(board, friend_id, added_by=admin_id, direct=True)
    if created:
        items.materialize_all(board, friend_id)
        admin = User.objects.get(pk=admin_id)
        from squads.notify import notify
        notify(friend_id, 'added', f'{items.display_name(admin)} added you to {board.name}',
               'Stay or leave: leaving is one tap and notifies no one.', url=f'/board/#squad/{board.id}', board=board)
        track('friend_added_direct', admin_id, board_id=board.id)
    return m


def suggest_friend(board, member_id, friend_id):
    if not is_member(board, member_id):
        raise _forbid('Not a member of this squad')
    if not are_friends(member_id, friend_id):
        raise SquadError('You can only suggest accepted friends')
    if is_member(board, friend_id):
        raise SquadError('Already in the squad')
    s, _ = MemberSuggestion.objects.update_or_create(board=board, user_id=friend_id,
                                                     defaults={'suggested_by_id': member_id, 'status': 'pending'})
    return s


def decide_suggestion(board, admin_id, suggestion_id, approve):
    if not can_edit(board, admin_id):
        raise _forbid()
    s = MemberSuggestion.objects.get(pk=suggestion_id, board=board, status='pending')
    s.status = 'approved' if approve else 'declined'
    s.save(update_fields=['status'])
    if approve:
        if _blocked_with_members(board, s.user_id):
            raise SquadError('You can\'t add this person', 403)
        _add_member(board, s.user_id, added_by=admin_id, direct=True)
        items.materialize_all(board, s.user_id)
        from squads.notify import notify
        notify(s.user_id, 'added', f'You were added to {board.name}',
               'Stay or leave: leaving is one tap and notifies no one.', url=f'/board/#squad/{board.id}', board=board)
    return s


def acknowledge_add(board, user_id, stay=True):
    m = membership(board, user_id)
    if not m:
        raise SquadError('Not a member', 404)
    if stay:
        m.add_acknowledged = True
        m.save(update_fields=['add_acknowledged'])
        return m
    return leave(board, user_id, quiet=True)


# ──────────────────────────────────────
# Membership management (H1, H2)
# ──────────────────────────────────────

def leave(board, user_id, quiet=False):
    """One tap; personal links and history stay; contributions remain as 'Former member'."""
    m = membership(board, user_id)
    if not m or m.status != MembershipStatus.ACTIVE:
        raise SquadError('Not a member', 404)
    with transaction.atomic():
        if m.role == Role.OWNER:
            successor = (board.active_memberships().exclude(user_id=user_id)
                         .order_by('-role', 'joined_at').first())
            admins = board.active_memberships().exclude(user_id=user_id).filter(role=Role.ADMIN).order_by('joined_at')
            successor = admins.first() or successor
            if successor is None:
                board.status = BoardStatus.ARCHIVED
                board.save(update_fields=['status'])
            else:
                successor.role = Role.OWNER
                successor.save(update_fields=['role'])
                board.owner_id = successor.user_id
                board.save(update_fields=['owner'])
        m.status, m.left_at, m.role = MembershipStatus.LEFT, timezone.now(), Role.MEMBER
        m.save(update_fields=['status', 'left_at', 'role'])
    if not quiet:
        FeedItem.objects.create(board=board, kind='left', text='A member left the squad')
    return m


def remove_member(board, admin_id, user_id):
    if not can_edit(board, admin_id):
        raise _forbid()
    m = membership(board, user_id)
    if not m or m.status != MembershipStatus.ACTIVE:
        raise SquadError('Not a member', 404)
    if m.role == Role.OWNER:
        raise _forbid('The owner can\'t be removed; transfer ownership first')
    m.status, m.left_at = MembershipStatus.REMOVED, timezone.now()
    m.save(update_fields=['status', 'left_at'])
    return m


def set_role(board, admin_id, user_id, role):
    if not can_edit(board, admin_id):
        raise _forbid()
    if role not in (Role.ADMIN, Role.MEMBER):
        raise SquadError('Role must be admin or member')
    m = membership(board, user_id)
    if not m or m.status != MembershipStatus.ACTIVE or m.role == Role.OWNER:
        raise SquadError('Can\'t change that member\'s role')
    m.role = role
    m.save(update_fields=['role'])
    return m


@transaction.atomic
def transfer_ownership(board, owner_id, user_id):
    if board.owner_id != owner_id:
        raise _forbid('Only the owner can transfer ownership')
    target = membership(board, user_id)
    if not target or target.status != MembershipStatus.ACTIVE:
        raise SquadError('Pick an active member')
    if limits.hosted() and limits.plan_of(owner_id) != 'free' and limits.plan_of(user_id) == 'free':
        raise SquadError('Transfer to a member on a paid plan to keep this squad\'s limits')
    BoardMembership.objects.filter(board=board, user_id=owner_id).update(role=Role.ADMIN)
    target.role = Role.OWNER
    target.save(update_fields=['role'])
    board.owner_id = user_id
    board.save(update_fields=['owner'])
    return board


def archive(board, user_id):
    if board.owner_id != user_id and not can_edit(board, user_id):
        raise _forbid()
    board.status = BoardStatus.ARCHIVED
    board.save(update_fields=['status'])
    return board


def unarchive(board, user_id):
    if board.owner_id != user_id:
        raise _forbid('Only the owner can restore this squad')
    board.status = BoardStatus.ACTIVE
    board.save(update_fields=['status'])
    limits.apply_downgrade(user_id, keep_board_id=board.id)
    return board


def delete_squad(board, user_id, confirm_name):
    if board.owner_id != user_id:
        raise _forbid('Only the owner can delete this squad')
    if (confirm_name or '').strip() != board.name:
        raise SquadError('Type the squad\'s name to confirm')
    from board.models import Habit, Metric
    # Members keep their personal copies; they just stop being linked
    Habit.objects.filter(linked_squad_habit__board=board).update(linked_squad_habit=None)
    Metric.objects.filter(linked_squad_tracker__board=board).update(linked_squad_tracker=None)
    board.delete()


def update_settings(board, user_id, data):
    if not can_edit(board, user_id):
        raise _forbid()
    if 'name' in data and data['name'].strip():
        board.name = data['name'].strip()[:80]
    if 'emoji' in data:
        board.emoji = (data['emoji'] or '')[:16]
    if 'timezone' in data and data['timezone']:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(data['timezone'])
        except Exception:
            raise SquadError('Unknown timezone')
        board.timezone = data['timezone']
    if 'late_log_cutoff_hour' in data:
        hour = int(data['late_log_cutoff_hour'])
        if not 0 <= hour <= 23:
            raise SquadError('Cutoff hour must be 0-23')
        board.settings = {**(board.settings or {}), 'late_log_cutoff_hour': hour}
    board.save()
    if 'streak_threshold_pct' in data:
        pct = data['streak_threshold_pct']
        if pct not in (None, '') and not (10 <= int(pct) <= 100):
            raise SquadError('Threshold must be 10-100%')
        items.schedule_threshold(board, int(pct) if pct not in (None, '') else None)   # from the next day
    return board


# ──────────────────────────────────────
# Away mode (C6) and member settings
# ──────────────────────────────────────

def set_away(board, user_id, until, from_day=None):
    m = membership(board, user_id)
    if not m or m.status != MembershipStatus.ACTIVE:
        raise SquadError('Not a member', 404)
    if until is None:
        m.away_from = m.away_until = None
    else:
        m.away_from = from_day or board.local_today()
        m.away_until = until
    m.save(update_fields=['away_from', 'away_until'])
    return m


def set_muted(board, user_id, muted):
    m = membership(board, user_id)
    if not m:
        raise SquadError('Not a member', 404)
    m.muted = bool(muted)
    m.save(update_fields=['muted'])
    return m


# ──────────────────────────────────────
# Nudges (C4)
# ──────────────────────────────────────

def nudge(board, from_id, to_id, now=None):
    """Only a member who is in can nudge a pending friend; max one per pair per day."""
    from squads.evaluator import member_state
    now = now or timezone.now()
    if from_id == to_id:
        raise SquadError('You can\'t nudge yourself')
    if not (is_member(board, from_id) and is_member(board, to_id)):
        raise _forbid('Both of you need to be in the squad')
    if _blocked_between(from_id, to_id):
        raise SquadError('You can\'t nudge this person', 403)
    day = board.local_today(now)
    mine = member_state(board, membership(board, from_id), day)[0]
    theirs = member_state(board, membership(board, to_id), day)[0]
    if mine != 'in':
        raise SquadError('Check in first, then nudge')
    if theirs in ('in', 'away', 'off', 'none'):
        raise SquadError('They don\'t need a nudge today')
    n, created = Nudge.objects.get_or_create(board=board, from_user_id=from_id, to_user_id=to_id, day=day)
    if not created:
        raise SquadError('You already nudged them today', 429)
    sender = User.objects.get(pk=from_id)
    from squads.notify import notify
    notify(to_id, 'nudge', f'{items.display_name(sender)} nudged you',
           f'{board.emoji} {board.name} is waiting on your check-in.', url=f'/board/#squad/{board.id}', board=board)
    track('nudge_sent', from_id, board_id=board.id)
    return n

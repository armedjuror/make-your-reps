"""
One place that decides which items a user can see and change.

Every view reads Habit, Task, Metric and FocusSession through
``visible_items``; no view filters those models by ``user_id`` directly.

* Personal board: the user's own items (what ``user_id=`` used to mean).
* Squad boards: items on boards where the user has an active membership and
  is an assignee, or the item has no assignees.

Habits and trackers reach Today through the member's *linked* personal copy,
so lists of habits and trackers use ``squads=False``; squad todos have no
copy and are listed with ``squads=True``.
"""
from django.db.models import Q

from squads.models import Board, BoardMembership, BoardType, MembershipStatus, Role

def personal_board_id(user_or_id):
    user_id = getattr(user_or_id, 'id', user_or_id)
    return Board.personal_for(user_id).id if user_id is not None else None


def member_boards_q(user_or_id, types=(BoardType.SQUAD, BoardType.CHALLENGE)):
    """Subquery of board ids where the user is an active member (no extra query)."""
    user_id = getattr(user_or_id, 'id', user_or_id)
    return BoardMembership.objects.filter(
        user_id=user_id, status=MembershipStatus.ACTIVE, board__type__in=types,
    ).values('board_id')


def member_board_ids(user_or_id, types=(BoardType.SQUAD, BoardType.CHALLENGE)):
    return list(member_boards_q(user_or_id, types).values_list('board_id', flat=True))


def _model_name(model):
    return model._meta.model_name


def visible_items(user_or_id, model, squads=True, boards=None):
    """
    Items of ``model`` the user can see.

    ``squads=False``: personal board only. ``boards``: limit to these board ids
    (still checked against membership).
    """
    user_id = getattr(user_or_id, 'id', user_or_id)
    own_q = Q(board__owner_id=user_id, board__type=BoardType.PERSONAL)
    if not squads:
        qs = model.objects.filter(own_q)
        return qs if boards is None else qs.filter(board_id__in=boards)

    name = _model_name(model)
    squad_q = Q(board_id__in=member_boards_q(user_id))
    if name == 'habit':
        squad_q &= Q(assignees__isnull=True) | Q(assignees__id=user_id)
    elif name == 'task':
        squad_q &= Q(assignee__isnull=True) | Q(assignee_id=user_id)
    qs = model.objects.filter(own_q | squad_q)
    if name == 'habit':
        qs = qs.distinct()   # the assignee join can repeat rows
    return qs if boards is None else qs.filter(board_id__in=boards)


def membership(board, user_or_id):
    user_id = getattr(user_or_id, 'id', user_or_id)
    board_id = getattr(board, 'id', board)
    return BoardMembership.objects.filter(board_id=board_id, user_id=user_id).select_related('board').first()


def is_member(board, user_or_id):
    m = membership(board, user_or_id)
    return bool(m and m.status == MembershipStatus.ACTIVE)


def role_of(board, user_or_id):
    if board.type == BoardType.PERSONAL:
        return Role.OWNER if board.owner_id == getattr(user_or_id, 'id', user_or_id) else None
    m = membership(board, user_or_id)
    return m.role if m and m.status == MembershipStatus.ACTIVE else None


def can_view(board, user_or_id):
    return role_of(board, user_or_id) is not None


def can_edit(board, user_or_id):
    """Change the board's items and settings: owner or admin, and the board is not read-only."""
    if not board.is_writable:
        return False
    return role_of(board, user_or_id) in (Role.OWNER, Role.ADMIN)


def can_log(board, user_or_id):
    """Log against the board's items (members edit their own logs only)."""
    return board.is_writable and role_of(board, user_or_id) is not None


def can_close_todo(task, user_or_id):
    user_id = getattr(user_or_id, 'id', user_or_id)
    board = task.board
    if board.type == BoardType.PERSONAL:
        return board.owner_id == user_id
    if not can_log(board, user_id):
        return False
    if task.completion_mode == 'assigned' and task.assignee_id:
        return task.assignee_id == user_id
    return True


class BoardScopedMixin:
    """
    For views and DRF viewsets. ``board_model`` and ``board_squads`` say what
    ``scoped()`` returns; it is the only way a view reads those models.
    """
    board_model = None
    board_squads = True

    def scoped_user_id(self):
        return self.request.session.get('user_id')

    def scoped(self, model=None, squads=None):
        return visible_items(
            self.scoped_user_id(), model or self.board_model,
            squads=self.board_squads if squads is None else squads,
        )

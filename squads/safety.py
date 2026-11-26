"""
Block, report, account deletion and export.

* Blocking ends the friendship, prevents adds, invites and nudges from that
  person, and hides them in shared challenges.
* Reports (users, squads, public challenges) reach the admin queue.
* Account deletion: personal data deleted; contributions kept as 'Former
  member' so squad totals stay correct.
* Export: a member downloads their own squad history as CSV or JSON.
"""
import csv
import io
import json

from django.db import transaction
from django.db.models import Q

from board.models import AccountabilityPartner, Friend, FriendRequest
from squads.models import (
    Block, BoardMembership, BoardType, ChallengeParticipant, Contribution, FocusAttendance, MembershipStatus,
    Report, Role,
)

REPORT_TARGETS = ('user', 'squad', 'challenge')


def hidden_user_ids(viewer_id):
    if not viewer_id:
        return set()
    rows = Block.objects.filter(Q(blocker_id=viewer_id) | Q(blocked_id=viewer_id)).values_list('blocker_id', 'blocked_id')
    return {b if a == viewer_id else a for a, b in rows}


@transaction.atomic
def block(blocker_id, blocked_id):
    if blocker_id == blocked_id:
        raise ValueError('You can\'t block yourself')
    b, _ = Block.objects.get_or_create(blocker_id=blocker_id, blocked_id=blocked_id)
    Friend.objects.filter(Q(user_id=blocker_id, friend_id=blocked_id) | Q(user_id=blocked_id, friend_id=blocker_id)).delete()
    FriendRequest.objects.filter(Q(from_user_id=blocker_id, to_user_id=blocked_id)
                                 | Q(from_user_id=blocked_id, to_user_id=blocker_id)).delete()
    AccountabilityPartner.objects.filter(
        Q(habit__user_id=blocker_id, partner_id=blocked_id) | Q(habit__user_id=blocked_id, partner_id=blocker_id)).delete()
    return b


def unblock(blocker_id, blocked_id):
    Block.objects.filter(blocker_id=blocker_id, blocked_id=blocked_id).delete()


def report(reporter_id, target_type, target_id, reason):
    if target_type not in REPORT_TARGETS:
        raise ValueError('Unknown report target')
    if not (reason or '').strip():
        raise ValueError('Tell us what happened')
    return Report.objects.create(reporter_id=reporter_id, target_type=target_type, target_id=int(target_id),
                                 reason=reason.strip()[:2000])


def anonymise_user(user):
    """Before an account is deleted: keep totals, drop the name, hand on owned squads."""
    Contribution.objects.filter(user=user).update(member_label='Former member')
    for m in BoardMembership.objects.filter(user=user, role=Role.OWNER, status=MembershipStatus.ACTIVE,
                                            board__type__in=[BoardType.SQUAD, BoardType.CHALLENGE]).select_related('board'):
        board = m.board
        successor = (board.active_memberships().exclude(user=user).order_by('role', 'joined_at')
                     .filter(role=Role.ADMIN).first()
                     or board.active_memberships().exclude(user=user).order_by('joined_at').first())
        if successor:
            successor.role = Role.OWNER
            successor.save(update_fields=['role'])
            board.owner_id = successor.user_id
            board.save(update_fields=['owner'])


def export_rows(user_id):
    rows = []
    for c in Contribution.objects.filter(user_id=user_id).select_related('board').order_by('day', 'id'):
        rows.append({'type': 'contribution', 'squad': c.board.name, 'day': c.day.isoformat(), 'reason': c.reason,
                     'points': c.points, 'value': str(c.value), 'late': c.late,
                     'reversal': bool(c.reversal_of_id), 'created_at': c.created_at.isoformat()})
    for m in BoardMembership.objects.filter(user_id=user_id).select_related('board'):
        rows.append({'type': 'membership', 'squad': m.board.name, 'board_type': m.board.type, 'role': m.role,
                     'status': m.status, 'joined_at': m.joined_at.isoformat(),
                     'left_at': m.left_at.isoformat() if m.left_at else ''})
    for a in FocusAttendance.objects.filter(user_id=user_id).select_related('session__board'):
        rows.append({'type': 'focus', 'squad': a.session.board.name, 'start_at': a.session.start_at.isoformat(),
                     'minutes': a.minutes, 'completed': a.completed})
    for p in ChallengeParticipant.objects.filter(user_id=user_id).select_related('challenge'):
        rows.append({'type': 'challenge', 'challenge': p.challenge.title, 'status': p.status,
                     'days_done': p.days_done, 'skips_used': p.skips_used,
                     'joined_at': p.joined_at.isoformat()})
    return rows


def export(user_id, fmt='json'):
    rows = export_rows(user_id)
    if fmt == 'csv':
        keys = sorted({k for r in rows for k in r})
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue(), 'text/csv'
    return json.dumps({'squad_history': rows}, indent=2), 'application/json'

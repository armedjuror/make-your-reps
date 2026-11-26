"""
Plan-limit hooks. Prices and tier values are decided separately: every number
lives in settings.PLAN_LIMITS so it can change without code changes.
Self-hosted installs (settings.HOSTED is false) are unlimited.

Joining a squad or challenge, logging, nudging and inviting are never limited.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from squads.events import track

GRACE_DAYS = 7
LIMIT_KEYS = (
    'squad_members',             # add member
    'squads_owned',              # create squad
    'challenge_link',            # create challenge with link visibility
    'challenge_public',          # create public challenge
    'challenge_participants',    # participant cap
    'focus_sessions_per_week',
    'history_days',              # heatmap and leaderboard window
)


class LimitBlocked(Exception):
    def __init__(self, trigger, limit, plan):
        self.trigger, self.limit, self.plan = trigger, limit, plan
        super().__init__(f'{trigger} limit ({limit}) reached on the {plan} plan')

    def payload(self):
        return {'status': 'failed', 'error': 'limit_reached', 'upgrade_trigger': self.trigger,
                'limit': self.limit, 'plan': self.plan,
                'message': f'Your plan allows {self.limit}. Upgrade to go further.'}


def hosted():
    return bool(getattr(settings, 'HOSTED', False))


def plan_of(user_or_id):
    """Effective plan, after the 7-day grace period on a lapsed subscription."""
    from squads.models import UserPlan
    user_id = getattr(user_or_id, 'id', user_or_id)
    state = UserPlan.objects.filter(user_id=user_id).first()
    if not state:
        return 'free'
    if state.plan != 'free' and state.paid_until and timezone.now() > state.paid_until + timedelta(days=GRACE_DAYS):
        return 'free'
    return state.plan


def limit_for(user_or_id, key):
    """None = unlimited."""
    if not hosted():
        return None
    from squads import flags
    if not flags.enabled('plan_limits'):
        return None
    table = getattr(settings, 'PLAN_LIMITS', {})
    return table.get(plan_of(user_or_id), table.get('free', {})).get(key)


def check(user_or_id, key, current):
    """Raise LimitBlocked when ``current`` (the count before this action) is already at the limit."""
    limit = limit_for(user_or_id, key)
    if limit is not None and current >= limit:
        record_block(user_or_id, key, limit)
        raise LimitBlocked(key, limit, plan_of(user_or_id))


def record_block(user_or_id, key, limit):
    from squads.models import UserPlan
    user_id = getattr(user_or_id, 'id', user_or_id)
    state, _ = UserPlan.objects.get_or_create(user_id=user_id)
    state.upgrade_trigger = key   # carried onto the resulting checkout and subscription
    state.save(update_fields=['upgrade_trigger', 'updated_at'])
    track('limit_blocked', user_id, trigger=key, limit=limit)
    try:
        from squads.notify import notify
        notify(user_id, 'upgrade', 'You hit a plan limit',
               f'Your plan allows {limit} for {key.replace("_", " ")}. Upgrade to go further.',
               url='/board/#squads')
    except Exception:
        pass


def history_start(user_or_id, today):
    days = limit_for(user_or_id, 'history_days')
    return None if days is None else today - timedelta(days=days - 1)


def apply_downgrade(user_or_id, keep_board_id=None):
    """
    Downgrade never removes anything: squads over the member limit keep everyone
    (adding is blocked), extra squads become read-only (the owner picks which
    stays active), history outside the window is hidden, not deleted.
    """
    from squads.models import Board, BoardStatus, BoardType
    user_id = getattr(user_or_id, 'id', user_or_id)
    limit = limit_for(user_id, 'squads_owned')
    owned = list(Board.objects.filter(owner_id=user_id, type=BoardType.SQUAD)
                 .exclude(status=BoardStatus.ARCHIVED).order_by('created_at'))
    if limit is None or len(owned) <= limit:
        Board.objects.filter(owner_id=user_id, type=BoardType.SQUAD, status=BoardStatus.READ_ONLY) \
            .update(status=BoardStatus.ACTIVE)
        return []
    keep = [b for b in owned if b.id == keep_board_id][:1]
    keep += [b for b in owned if b not in keep][:max(0, limit - len(keep))]
    frozen = []
    for b in owned:
        status = BoardStatus.ACTIVE if b in keep else BoardStatus.READ_ONLY
        if b.status != status:
            b.status = status
            b.save(update_fields=['status'])
        if status == BoardStatus.READ_ONLY:
            frozen.append(b.id)
    return frozen

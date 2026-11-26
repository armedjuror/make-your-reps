"""
Challenges: a time-boxed board whose rules lock at start.

Kinds:
* streak: do the item every day.
* target: hit a tracker value every day (rules.daily_target).
* ladder: the daily target climbs by rules.ladder_step each day.
* versus: squads compete; team score = sum of members' done days, or members'
  average completion % (rules.team_mode).

Days are evaluated in each participant's own timezone after the same late-log
cutoff as squads. A miss uses a skip token automatically; with none left the
participant is dropped and offered "continue unofficially".
"""
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from board.models import Habit, HabitLog, Metric, MetricEntry
from squads import items, limits
from squads.events import track
from squads.models import (
    Board, BoardMembership, BoardType, Challenge, ChallengeDay, ChallengeKind, ChallengeParticipant,
    ChallengeVisibility, FeedItem, MembershipStatus, ParticipantStatus, Role,
)

logger = logging.getLogger(__name__)
CUTOFF_HOUR = 10


class ChallengeError(Exception):
    pass


# ──────────────────────────────────────
# Create and edit
# ──────────────────────────────────────

def _hosted_count(user_id, visibility):
    return Challenge.objects.filter(host_id=user_id, visibility=visibility, ended=False).count()


def create_challenge(host, *, title, kind=ChallengeKind.STREAK, visibility=ChallengeVisibility.SQUAD,
                     start_date, days=None, end_date=None, item_name='', unit='', daily_target=None,
                     ladder_step=None, skip_tokens=0, parent_board=None, join_deadline=None,
                     late_join='prorate', team_mode='sum', participant_cap=None, tz=None, emoji='🏁'):
    host_id = getattr(host, 'id', host)
    if kind not in ChallengeKind.values or visibility not in ChallengeVisibility.values:
        raise ChallengeError('Unknown challenge kind or visibility')
    if end_date is None:
        end_date = start_date + timedelta(days=int(days or 30) - 1)
    if end_date < start_date:
        raise ChallengeError('The challenge must end after it starts')
    if visibility == ChallengeVisibility.SQUAD or kind == ChallengeKind.VERSUS:
        if parent_board is None:
            raise ChallengeError('Pick the squad this challenge belongs to')
        from squads.scoping import is_member
        if not is_member(parent_board, host_id):
            raise ChallengeError('You are not in that squad')
    if visibility == ChallengeVisibility.LINK:
        limits.check(host_id, 'challenge_link', _hosted_count(host_id, visibility))
    if visibility == ChallengeVisibility.PUBLIC:
        limits.check(host_id, 'challenge_public', _hosted_count(host_id, visibility))
        if participant_cap is None:
            participant_cap = limits.limit_for(host_id, 'challenge_participants')
            from squads.models import UserPlan
            if UserPlan.objects.filter(user_id=host_id, verified_host=True).exists():
                participant_cap = None
    with transaction.atomic():
        return _create(host_id, title, kind, visibility, start_date, end_date, item_name, unit, daily_target,
                       ladder_step, skip_tokens, parent_board, join_deadline, late_join, team_mode,
                       participant_cap, tz, emoji)


def _create(host_id, title, kind, visibility, start_date, end_date, item_name, unit, daily_target, ladder_step,
            skip_tokens, parent_board, join_deadline, late_join, team_mode, participant_cap, tz, emoji):
    board = Board.objects.create(type=BoardType.CHALLENGE, name=title[:80], emoji=emoji, owner_id=host_id,
                                 timezone=tz or (parent_board.timezone if parent_board else Board.personal_for(host_id).timezone))
    BoardMembership.objects.create(board=board, user_id=host_id, role=Role.OWNER)
    rules = {
        'item_template': {'name': item_name or title, 'unit': unit},
        'daily_target': float(daily_target) if daily_target else (1 if kind == ChallengeKind.STREAK else None),
        'ladder_step': float(ladder_step) if ladder_step else (1 if kind == ChallengeKind.LADDER else None),
        'skip_tokens': int(skip_tokens or 0),
        'scoring': 'cooperative' if visibility == ChallengeVisibility.SQUAD else 'individual',
        'team_mode': team_mode if team_mode in ('sum', 'completion') else 'sum',
        'late_join': late_join if late_join in ('prorate', 'ineligible') else 'prorate',
    }
    ch = Challenge.objects.create(
        board=board, parent_board=parent_board, host_id=host_id, kind=kind, visibility=visibility,
        title=title[:120], start_date=start_date, end_date=end_date, join_deadline=join_deadline,
        rules=rules, participant_cap=participant_cap,
    )
    _create_item(ch, host_id)
    track('challenge_created', host_id, challenge_id=ch.id, visibility=visibility, kind=kind)
    return ch


def _create_item(ch, host_id):
    name = ch.rule('item_template', {}).get('name') or ch.title
    if ch.kind in (ChallengeKind.TARGET, ChallengeKind.LADDER):
        Metric.objects.create(board=ch.board, user_id=host_id, name=name[:64],
                              unit=(ch.rule('item_template', {}).get('unit') or '')[:16], kind='additive')
    else:
        Habit.objects.create(board=ch.board, user_id=host_id, habit=name[:255], identity=name[:255], is_core=True)


def challenge_item(ch):
    if ch.kind in (ChallengeKind.TARGET, ChallengeKind.LADDER):
        return Metric.objects.filter(board=ch.board).first()
    return Habit.objects.filter(board=ch.board).first()


def lock_rules_if_started(ch, today=None):
    today = today or timezone.localdate()
    if ch.rules_locked_at is None and today >= ch.start_date:
        ch.rules_locked_at = timezone.now()
        ch.save(update_fields=['rules_locked_at'])


def update_challenge(ch, user_id, data):
    """Before start the host can change anything; after, only extend the end date."""
    if ch.host_id != user_id:
        raise ChallengeError('Only the host can edit this challenge')
    lock_rules_if_started(ch)
    if ch.rules_locked_at:
        if set(data) - {'end_date'}:
            raise ChallengeError('Rules are locked: only the end date can be extended')
        new_end = date.fromisoformat(str(data['end_date']))
        if new_end < ch.end_date:
            raise ChallengeError('The end date can only be extended')
        ch.end_date = new_end
        ch.save(update_fields=['end_date'])
        return ch
    for key in ('title', 'join_deadline', 'participant_cap'):
        if key in data:
            setattr(ch, key, data[key] or None if key != 'title' else data[key])
    for key in ('start_date', 'end_date'):
        if key in data:
            setattr(ch, key, date.fromisoformat(str(data[key])))
    for key in ('daily_target', 'ladder_step', 'skip_tokens', 'late_join', 'team_mode'):
        if key in data:
            ch.rules[key] = data[key]
    ch.save()
    return ch


# ──────────────────────────────────────
# Joining
# ──────────────────────────────────────

def can_see(ch, user_id):
    if ch.visibility != ChallengeVisibility.SQUAD:
        return True
    from squads.scoping import is_member
    return bool(user_id) and (is_member(ch.parent_board, user_id) or is_member(ch.board, user_id))


def join_open(ch, today=None):
    today = today or timezone.localdate()
    if ch.phase(today) == 'ended':
        return False
    if today < ch.start_date:
        return True
    return bool(ch.join_deadline and today <= ch.join_deadline)


def join(ch, user, tz=None, team_board=None):
    user_id = getattr(user, 'id', user)
    if not can_see(ch, user_id):
        raise ChallengeError('This challenge is for squad members only')
    existing = ChallengeParticipant.objects.filter(challenge=ch, user_id=user_id).first()
    if existing and existing.status != ParticipantStatus.REMOVED:
        return existing
    if existing and existing.status == ParticipantStatus.REMOVED:
        raise ChallengeError('The host removed you from this challenge')
    if not join_open(ch):
        raise ChallengeError('Joining has closed for this challenge')
    if ch.participant_cap and ch.participants.exclude(status=ParticipantStatus.REMOVED).count() >= ch.participant_cap:
        if ch.host_id:
            limits.record_block(ch.host_id, 'challenge_participants', ch.participant_cap)
        raise ChallengeError('This challenge is full')
    with transaction.atomic():
        return _join(ch, user_id, tz, team_board)


def _join(ch, user_id, tz, team_board):
    today = timezone.localdate()
    late = today > ch.start_date
    eligible = not late or ch.rule('late_join', 'prorate') == 'prorate'
    m, _ = BoardMembership.objects.get_or_create(board=ch.board, user_id=user_id, defaults={'role': Role.MEMBER})
    if m.status != MembershipStatus.ACTIVE:
        m.status = MembershipStatus.ACTIVE
        m.save(update_fields=['status'])
    p = ChallengeParticipant.objects.create(
        challenge=ch, user_id=user_id, team_board=team_board, timezone=tz or ch.board.timezone,
        eligible=eligible, status=ParticipantStatus.ACTIVE,
    )
    item = challenge_item(ch)
    if isinstance(item, Habit):
        p.habit = items.materialize_habit(item, user_id)
    elif isinstance(item, Metric):
        p.metric = items.materialize_tracker(item, user_id)
    p.save(update_fields=['habit', 'metric'])
    track('challenge_joined', user_id, challenge_id=ch.id, visibility=ch.visibility, late=late)
    return p


def enter_team(ch, team_board, admin_id, tz=None):
    """F6: an admin enters their squad in a versus challenge; every active member joins on that team."""
    from squads.scoping import can_edit
    if ch.kind != ChallengeKind.VERSUS:
        raise ChallengeError('Only versus challenges take teams')
    if not can_edit(team_board, admin_id):
        raise ChallengeError('Only a squad admin can enter the squad')
    joined = []
    for m in team_board.active_memberships():
        try:
            joined.append(join(ch, m.user_id, tz=tz, team_board=team_board))
        except ChallengeError:
            continue
    return joined


def continue_unofficially(p):
    if p.status == ParticipantStatus.DROPPED:
        p.status = ParticipantStatus.UNOFFICIAL
        p.save(update_fields=['status'])
    return p


def remove_participant(ch, host_id, user_id):
    if ch.host_id != host_id:
        raise ChallengeError('Only the host can remove participants')
    ChallengeParticipant.objects.filter(challenge=ch, user_id=user_id).update(status=ParticipantStatus.REMOVED)
    BoardMembership.objects.filter(board=ch.board, user_id=user_id).update(status=MembershipStatus.REMOVED)


# ──────────────────────────────────────
# Evaluation
# ──────────────────────────────────────

def day_number(ch, day):
    return (day - ch.start_date).days + 1


def _done_on(ch, p, day):
    """(done, value) for the participant's linked item on ``day``."""
    if ch.kind in (ChallengeKind.TARGET, ChallengeKind.LADDER):
        if not p.metric_id:
            return False, Decimal(0)
        value = MetricEntry.objects.filter(metric_id=p.metric_id, date=day).aggregate(v=Sum('value'))['v'] or Decimal(0)
        return float(value) >= ch.target_for_day(day_number(ch, day)), Decimal(value)
    if not p.habit_id:
        return False, Decimal(0)
    done = HabitLog.objects.filter(habit_id=p.habit_id, date=day, is_done=True).exists()
    return done, Decimal(1 if done else 0)


def _last_closed_day(p, now):
    local = now.astimezone(p.tz)
    y = local.date() - timedelta(days=1)
    return y if local.hour >= CUTOFF_HOUR else y - timedelta(days=1)


def evaluate_participant(p, now=None):
    now = now or timezone.now()
    ch = p.challenge
    if p.status in (ParticipantStatus.DROPPED, ParticipantStatus.REMOVED, ParticipantStatus.COMPLETED):
        return 0
    first = max(ch.start_date, p.joined_at.astimezone(p.tz).date())
    last = min(ch.end_date, _last_closed_day(p, now))
    done_days = set(ChallengeDay.objects.filter(participant=p).values_list('day', flat=True))
    n = 0
    day = first
    while day <= last:
        if day not in done_days:
            if not _evaluate_day(p, ch, day):
                break
            n += 1
        day += timedelta(days=1)
    p.refresh_from_db()
    if p.status == ParticipantStatus.ACTIVE and last >= ch.end_date and _last_closed_day(p, now) >= ch.end_date:
        _complete(p, ch)
    return n


def _evaluate_day(p, ch, day):
    """Record one day. Returns False when the participant was dropped."""
    done, value = _done_on(ch, p, day)
    official = p.status == ParticipantStatus.ACTIVE
    if done:
        outcome = 'done'
    elif official and p.skips_used < int(ch.rule('skip_tokens', 0) or 0):
        outcome = 'skip'
    else:
        outcome = 'miss'
    try:
        with transaction.atomic():
            ChallengeDay.objects.create(participant=p, day=day, outcome=outcome, value=value)
            if outcome == 'done':
                p.days_done += 1
            elif outcome == 'skip':
                p.skips_used += 1
            if outcome == 'miss' and official:
                p.status = ParticipantStatus.DROPPED
            p.save(update_fields=['days_done', 'skips_used', 'status'])
    except IntegrityError:
        return True
    if outcome == 'miss' and official:
        track('challenge_dropped', p.user_id, challenge_id=ch.id, visibility=ch.visibility)
        if p.user_id:
            from squads.notify import notify
            notify(p.user_id, 'challenge_dropped', f'You missed a day of {ch.title}',
                   'No skips left, so you are out of the official run. Continue unofficially?',
                   url=f'/c/{ch.slug}/', board=ch.board)
        return False
    return True


def _complete(p, ch):
    official = p.eligible
    p.status = ParticipantStatus.COMPLETED if official else ParticipantStatus.UNOFFICIAL
    p.completed_at = timezone.now()
    p.save(update_fields=['status', 'completed_at'])
    if not official or not p.user_id:
        return
    track('challenge_completed', p.user_id, challenge_id=ch.id, visibility=ch.visibility)
    FeedItem.objects.create(board=ch.parent_board or ch.board, user_id=p.user_id, kind='milestone', reactable=True,
                            text=f'{items.display_name(p.user)} finished {ch.title} 🎉', ref={'challenge': ch.id})
    from squads.notify import notify
    notify(p.user_id, 'challenge_completed', f'You finished {ch.title}!',
           'Your completion card is ready to share. Start your own challenge or squad next?',
           url=f'/c/{ch.slug}/card/{p.id}/', board=ch.board)


def evaluate_all(now=None):
    now = now or timezone.now()
    n = 0
    today = timezone.localtime(now).date()
    for ch in Challenge.objects.filter(ended=False, start_date__lte=today):
        lock_rules_if_started(ch, today)
        for p in ch.participants.filter(status__in=[ParticipantStatus.ACTIVE, ParticipantStatus.UNOFFICIAL]):
            try:
                n += evaluate_participant(p, now)
            except Exception:
                logger.exception('Evaluating participant %s failed', p.id)
        if today > ch.end_date + timedelta(days=2) and not ch.participants.filter(status=ParticipantStatus.ACTIVE).exists():
            ch.ended = True
            ch.save(update_fields=['ended'])
    return n


# ──────────────────────────────────────
# Progress and leaderboards
# ──────────────────────────────────────

def _ranked(ch, viewer_id=None):
    from squads.safety import hidden_user_ids
    hidden = hidden_user_ids(viewer_id) if viewer_id else set()
    qs = (ch.participants.exclude(status=ParticipantStatus.REMOVED).exclude(user_id__in=hidden)
          .select_related('user').order_by('-days_done', 'skips_used', 'joined_at'))
    return list(qs)


def percentile(ch, p):
    """Share of other participants this one is ahead of."""
    others = ch.participants.exclude(pk=p.pk).exclude(status=ParticipantStatus.REMOVED)
    total = others.count()
    if not total:
        return 100
    behind = others.filter(days_done__lt=p.days_done).count()
    return round(100 * behind / total)


def progress(ch, p, today=None):
    today = today or p.local_today()
    n = max(0, min(ch.days, day_number(ch, today)))
    done_today, value_today = _done_on(ch, p, today) if ch.start_date <= today <= ch.end_date else (False, 0)
    return {
        'participant_id': p.id, 'status': p.status, 'day': n, 'days': ch.days, 'days_done': p.days_done,
        'skips_left': max(0, int(ch.rule('skip_tokens', 0) or 0) - p.skips_used),
        'percentile': percentile(ch, p), 'eligible': p.eligible, 'done_today': done_today,
        'value_today': float(value_today), 'target_today': ch.target_for_day(max(1, n)),
    }


def team_scores(ch):
    teams = {}
    for p in ch.participants.exclude(status=ParticipantStatus.REMOVED).exclude(team_board__isnull=True) \
            .select_related('team_board'):
        t = teams.setdefault(p.team_board_id, {'board_id': p.team_board_id, 'name': p.team_board.name,
                                               'emoji': p.team_board.emoji, 'members': 0, 'days_done': 0})
        t['members'] += 1
        t['days_done'] += p.days_done
    elapsed = max(1, min(ch.days, day_number(ch, timezone.localdate()) - 1))
    for t in teams.values():
        t['completion_pct'] = round(100 * t['days_done'] / (elapsed * max(1, t['members'])))
        t['score'] = t['completion_pct'] if ch.rule('team_mode') == 'completion' else t['days_done']
    return sorted(teams.values(), key=lambda t: -t['score'])


def leaderboard(ch, viewer_id=None):
    ranked = _ranked(ch, viewer_id)
    rows = [{'user_id': p.user_id, 'name': items.display_name(p.user), 'days_done': p.days_done,
             'status': p.status} for p in ranked]
    out = {'top': rows[:10], 'count': len(rows)}
    if ch.visibility == ChallengeVisibility.SQUAD:
        possible = max(1, len(ranked)) * max(1, min(ch.days, day_number(ch, timezone.localdate()) - 1))
        out['team'] = {'days_done': sum(p.days_done for p in ranked),
                       'completion_pct': round(100 * sum(p.days_done for p in ranked) / possible)}
        out['top'] = rows   # cooperative: everyone, no ranks emphasised
    if viewer_id:
        from board.models import Friend
        friend_ids = set(Friend.objects.filter(user_id=viewer_id).values_list('friend_id', flat=True))
        out['friends'] = [r for r in rows if r['user_id'] in friend_ids]
        me = next((p for p in ranked if p.user_id == viewer_id), None)
        if me:
            out['me'] = progress(ch, me)
    if ch.kind == ChallengeKind.VERSUS:
        out['teams'] = team_scores(ch)
    return out


def discover(limit=30, today=None):
    today = today or timezone.localdate()
    qs = (Challenge.objects.filter(visibility=ChallengeVisibility.PUBLIC, ended=False, end_date__gte=today)
          .annotate(n=Count('participants', filter=~Q(participants__status=ParticipantStatus.REMOVED))))
    starting_soon = list(qs.filter(start_date__gte=today).order_by('start_date', '-n')[:limit])
    most_joined = list(qs.order_by('-n', 'start_date')[:limit])
    return starting_soon, most_joined


def serialize(ch, viewer_id=None):
    p = ch.participants.filter(user_id=viewer_id).first() if viewer_id else None
    return {
        'id': ch.id, 'slug': ch.slug, 'title': ch.title, 'kind': ch.kind, 'visibility': ch.visibility,
        'start_date': ch.start_date.isoformat(), 'end_date': ch.end_date.isoformat(), 'days': ch.days,
        'join_deadline': ch.join_deadline.isoformat() if ch.join_deadline else None,
        'rules': ch.rules, 'locked': bool(ch.rules_locked_at), 'phase': ch.phase(),
        'host': items.display_name(ch.host) if ch.host_id else 'Former member', 'host_id': ch.host_id,
        'participant_count': ch.participants.exclude(status=ParticipantStatus.REMOVED).count(),
        'participant_cap': ch.participant_cap, 'parent_board': ch.parent_board_id, 'board_id': ch.board_id,
        'emoji': ch.board.emoji, 'join_open': join_open(ch),
        'me': progress(ch, p) if p else None,
        'url': f'/c/{ch.slug}/',
    }

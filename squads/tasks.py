"""Celery jobs for squads. All are idempotent; beat runs them every 5 / 15 minutes."""
import logging
from datetime import datetime, time, timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

AT_RISK_WINDOW_MIN = 30      # 20:00-20:30 local, the job runs every 5 minutes
RECAP_WEEKDAY, RECAP_HOUR = 6, 19   # Sunday evening, board time
FOCUS_REMIND_MIN = 10


@shared_task
def evaluate_days():
    from squads.evaluator import evaluate_all
    return evaluate_all()


@shared_task
def periodic():
    from squads import flags, notify
    now = timezone.now()
    for job in (at_risk_alerts, challenge_at_risk_alerts, focus_jobs, weekly_recaps):
        try:
            job(now)
        except Exception:
            logger.exception('%s failed', job.__name__)
    if flags.enabled('notifications'):
        notify.deliver_queued(now)


def _in_window(local, hour, minutes=AT_RISK_WINDOW_MIN):
    start = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    return start <= local < start + timedelta(minutes=minutes)


def _sent_today(user_id, kind, board, local_day, tz):
    from squads.models import NotificationLog
    start = datetime.combine(local_day, time(0, 0), tzinfo=tz)
    return NotificationLog.objects.filter(user_id=user_id, kind=kind, board=board, created_at__gte=start).exists()


def at_risk_alerts(now):
    """C3: at 20:00 squad time, pending members get one alert if the day is below threshold."""
    from squads.evaluator import day_snapshot, streak_start_day
    from squads.models import Board, BoardStatus, BoardType
    from squads.notify import notify
    for board in Board.objects.filter(type=BoardType.SQUAD, status=BoardStatus.ACTIVE):
        local = board.local_now(now)
        if not _in_window(local, int(board.setting('at_risk_hour'))):
            continue
        start = streak_start_day(board)
        if start is None or start > local.date():
            continue
        snap = day_snapshot(board, local.date())
        if not snap['counted'] or snap['survives']:
            continue
        for uid in snap['counted']:
            if snap['states'][uid][0] == 'in' or _sent_today(uid, 'at_risk', board, local.date(), board.tz):
                continue
            notify(uid, 'at_risk', f'{board.emoji} {board.name} streak at risk',
                   f"{len(snap['members_in'])}/{len(snap['counted'])} in so far. Your check-in could save it.",
                   url=f'/board/#squad/{board.id}', board=board, now=now)


def challenge_at_risk_alerts(now):
    from squads.challenges import _done_on
    from squads.models import ChallengeParticipant, ParticipantStatus
    from squads.notify import notify
    today = timezone.localdate()
    for p in ChallengeParticipant.objects.filter(
            status=ParticipantStatus.ACTIVE, challenge__start_date__lte=today + timedelta(days=1),
            challenge__end_date__gte=today - timedelta(days=1), user__isnull=False).select_related('challenge'):
        local = now.astimezone(p.tz)
        ch = p.challenge
        if not (ch.start_date <= local.date() <= ch.end_date) or not _in_window(local, 20):
            continue
        if _done_on(ch, p, local.date())[0] or _sent_today(p.user_id, 'challenge_at_risk', ch.board, local.date(), p.tz):
            continue
        day = (local.date() - ch.start_date).days + 1
        notify(p.user_id, 'challenge_at_risk', f'{ch.title}: day {day}/{ch.days} still open',
               'Log it before midnight to keep your run going.', url=f'/c/{ch.slug}/', board=ch.board, now=now)


def focus_jobs(now):
    """T-10 push, then close sessions that have ended."""
    from squads import focus
    from squads.models import FocusSession, FocusStatus
    from squads.notify import notify
    soon = FocusSession.objects.filter(status=FocusStatus.SCHEDULED, reminded=False,
                                       start_at__lte=now + timedelta(minutes=FOCUS_REMIND_MIN), start_at__gt=now)
    for s in soon.select_related('board'):
        FocusSession.objects.filter(pk=s.pk).update(reminded=True)
        for m in s.board.active_memberships():
            if s.rsvps.filter(user_id=m.user_id, response='no').exists():
                continue
            notify(m.user_id, 'focus_start', f'{s.board.emoji} Focus session in 10 minutes',
                   f'{s.blocks} x {s.block_minutes} min with {s.board.name}.', url=f'/squads/focus/{s.id}/room/',
                   board=s.board, now=now)
    for s in FocusSession.objects.filter(status__in=[FocusStatus.SCHEDULED, FocusStatus.LIVE],
                                         start_at__lte=now - timedelta(minutes=5)):
        if s.end_at <= now:
            focus.close(s, now)


def weekly_recaps(now):
    """I1: every Sunday evening, push + email the recap with a shareable image."""
    from squads import share
    from squads.evaluator import week_start
    from squads.models import Board, BoardStatus, BoardType, NotificationLog
    from squads.notify import notify
    for board in Board.objects.filter(type=BoardType.SQUAD, status=BoardStatus.ACTIVE):
        local = board.local_now(now)
        if local.weekday() != RECAP_WEEKDAY or not _in_window(local, RECAP_HOUR, 60):
            continue
        if board.active_memberships().count() < 2:
            continue
        ws = week_start(local.date())
        token = share.token_for('recap', b=board.id, w=ws.isoformat())
        if NotificationLog.objects.filter(board=board, kind='recap', url__contains=token[:24]).exists():
            continue
        data = share.recap(board, ws)
        for m in board.active_memberships():
            notify(m.user_id, 'recap', f'{board.emoji} {board.name}: your week',
                   f"{data['streak']}-day streak · team score {data['team_score']}"
                   + (f" · MVP {data['mvp']}" if data['mvp'] else ''),
                   url=f'/s/recap/{token}/', board=board, now=now)


def generate_timeline_for_squad_todo(task_id):
    """A squad todo due today shows in each member's (or the assignee's) Today."""
    from board.models import Task, TimelineEvent, TimelineEventType
    task = Task.objects.filter(pk=task_id, is_deleted=False, is_done=False).select_related('board').first()
    if not task or not task.deadline:
        return
    today = timezone.localdate()
    if timezone.localtime(task.deadline).date() != today:
        return
    users = [task.assignee_id] if task.assignee_id else list(
        task.board.active_memberships().values_list('user_id', flat=True))
    for uid in users:
        if not TimelineEvent.objects.filter(user_id=uid, event_type=TimelineEventType.TODO, reference__model='Task',
                                            reference__id=task.id, timestamp__date=today).exists():
            TimelineEvent.objects.create(user_id=uid, timestamp=task.deadline, event_type=TimelineEventType.TODO,
                                         event=f'Due today: {task.task_name}', reference={'model': 'Task', 'id': task.id},
                                         action={'mark_done': [True, False]})

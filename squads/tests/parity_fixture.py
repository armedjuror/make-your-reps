"""
Board-migration parity fixture.

``build()`` creates a rich personal account (habits with logs and steps, todos
in groups, trackers with entries, journals, day plans) plus a second user with
their own data, using only models that exist before the Board migration.
``snapshot(client, ids)`` reads every list and detail endpoint.

The committed snapshot (parity_snapshot.json) was produced from main, before
the migration, by squads/tests/make_parity_snapshot.py. The parity test
rebuilds the same account on this branch and requires identical responses.

A real account dump can be used instead: set PARITY_FIXTURE to a dumpdata
JSON file of that account (for example user 7) and regenerate the snapshot
from main with the same file.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone

TODAY = date(2026, 11, 5)      # a Thursday
NOW = timezone.make_aware(datetime(2026, 11, 5, 18, 30))


def _aware(d, h, m=0):
    return timezone.make_aware(datetime.combine(d, time(h, m)))


def build():
    from board.models import (
        DailyData, DayPlan, Habit, HabitLog, HabitStep, Journal, JournalEntry, Metric, MetricEntry, RoutineEntry,
        Task, TaskGroup, UserDetail,
    )
    me = User.objects.create_user('arjun', 'arjun@example.com', 'pw', first_name='Arjun')
    other = User.objects.create_user('meera', 'meera@example.com', 'pw', first_name='Meera')
    UserDetail.objects.create(user=me, day_start=time(4, 0))
    UserDetail.objects.create(user=other)

    seq = iter(range(1000))

    def habit(user, name, **kw):
        h = Habit.objects.create(user=user, habit=name, identity=name, **kw)
        Habit.objects.filter(pk=h.pk).update(created_at=NOW - timedelta(days=40, minutes=next(seq)))
        h.refresh_from_db()
        return h

    study = habit(me, 'Solve 2 problems', detail='LeetCode', frequency=[0, 1, 2, 3, 4], notify_at=time(7, 0))
    gym = habit(me, 'Workout', detail='Bands', notify_at=time(18, 0))
    private = habit(me, 'Private one', is_private=True)
    habit(me, 'Old habit', status='completed')
    theirs = habit(other, 'Meera habit', notify_at=time(9, 0))
    HabitStep.objects.create(habit=gym, order=0, name='Glute bridges', target='2 x 12')
    HabitStep.objects.create(habit=gym, order=1, name='Rows', target='3 x 10')
    for i in range(30):
        d = TODAY - timedelta(days=i)
        HabitLog.objects.create(habit=study, date=d, is_done=i % 3 != 0)
        HabitLog.objects.create(habit=gym, date=d, is_done=i % 2 == 0)
        HabitLog.objects.create(habit=theirs, date=d, is_done=True)
    HabitLog.objects.create(habit=private, date=TODAY, is_done=True)

    g1 = TaskGroup.objects.create(user=me, name='Personal Works')
    g2 = TaskGroup.objects.create(user=me, name='General')
    TaskGroup.objects.create(user=other, name='Meera group')
    Task.objects.create(user=me, group=g1, task_name='File taxes', deadline=_aware(TODAY, 17))
    Task.objects.create(user=me, group=g1, task_name='Overdue thing', deadline=_aware(TODAY - timedelta(days=3), 10))
    Task.objects.create(user=me, group=g2, task_name='Done thing', is_done=True)
    Task.objects.create(user=me, group=g2, task_name='No deadline')
    Task.objects.create(user=me, task_name='Deleted', is_deleted=True)
    Task.objects.create(user=other, task_name='Meera task', deadline=_aware(TODAY, 12))
    for i, t in enumerate(Task.objects.order_by('id')):   # distinct times keep list order deterministic
        Task.objects.filter(pk=t.pk).update(created_at=NOW - timedelta(hours=10 - i))

    walk = Metric.objects.create(user=me, name='Walk', unit='min', kind='additive', target=Decimal('30'),
                                 quick_steps=[Decimal('10'), Decimal('20')])
    coffee = Metric.objects.create(user=me, name='Coffee', unit='cups', kind='counter', direction='at_most',
                                   target=Decimal('3'))
    Metric.objects.create(user=other, name='Meera metric', unit='x')
    for i in range(10):
        d = TODAY - timedelta(days=i)
        MetricEntry.objects.create(metric=walk, date=d, at=_aware(d, 8), value=Decimal(10 + i))
        MetricEntry.objects.create(metric=coffee, date=d, at=_aware(d, 9), value=Decimal(1))

    j = Journal.objects.create(user=me, name='Daily', is_default=True)
    JournalEntry.objects.create(journal=j, date=TODAY, at=_aware(TODAY, 21), text='Good day')
    DailyData.objects.create(user=me, date=TODAY, journal='Good day', sleep_hours=Decimal('7.5'), focus_minutes=50)
    DayPlan.objects.create(user=me, date=TODAY - timedelta(days=1), template='workday', mode='light', source='manual')
    RoutineEntry.objects.create(user=me, routine_type='workday', title='Wake', time=time(5, 0), tier='essential')
    RoutineEntry.objects.create(user=me, routine_type='workday', title='DSA', time=time(7, 0))
    # Today's habit and todo cards, as the daily job creates them
    from board.tasks import generate_daily_timeline
    generate_daily_timeline(user_id=me.id)
    generate_daily_timeline(user_id=other.id)
    return {'me': me.id, 'other': other.id, 'study': study.id, 'gym': gym.id, 'walk': walk.id, 'theirs': theirs.id}


def endpoints(ids):
    d = TODAY.isoformat()
    return [
        '/board/api/tasks/', '/board/api/tasks/?done=false', f'/board/api/tasks/?group=1',
        '/board/api/task_groups/', '/board/api/habits/', '/board/api/habits/?status=completed',
        f'/board/api/habits/{ids["study"]}/logs/', f'/board/api/habits/{ids["theirs"]}/logs/',
        f'/board/api/habits/{ids["gym"]}/steps/',
        '/board/api/metrics/', f'/board/api/metrics/{ids["walk"]}/', f'/board/api/metrics/{ids["walk"]}/insights/',
        '/board/api/journal_books/', f'/board/api/journal_entries/?date={d}',
        f'/board/api/productivity_score/?date={d}', '/board/api/productivity_score_history/',
        '/board/api/gamification/', f'/board/api/day_plans/{d}/', '/board/api/user_details/',
        '/board/api/routine_entries/', f'/board/api/timeline/?date={d}',
        f'/board/api/timeline/?date={(TODAY - timedelta(days=1)).isoformat()}', '/board/api/day_plans/',
    ]


def snapshot(client, ids):
    out = {}
    for url in endpoints(ids):
        resp = client.get(url)
        try:
            body = resp.json()
        except ValueError:
            body = resp.content.decode()[:200]
        out[url] = {'status': resp.status_code, 'body': body}
    return out


# Keys this branch adds to responses. Parity is checked on everything else.
ADDED_KEYS = {'squad', 'board', 'completion_mode', 'assignee', 'completed_by',   # tasks, habits
              'source', 'logged_at', 'late'}                                       # habit logs


def strip_added(obj):
    if isinstance(obj, dict):
        return {k: strip_added(v) for k, v in obj.items() if k not in ADDED_KEYS}
    if isinstance(obj, list):
        return [strip_added(v) for v in obj]
    return obj

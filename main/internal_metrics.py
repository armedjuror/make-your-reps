"""
Numbers for the /internal/ admin dashboard.

Two sources, kept apart on purpose:

* Postgres ("doers"): users who did something (ticked a habit, wrote a journal entry,
  logged a tracker...). History goes back to launch, works with no PostHog at all.
* PostHog ("openers"): users who opened the app, time per pane/modal, which controls
  get clicked, and which client they used. Starts from the day analytics.js ships.

Openers minus doers = people who look at the board and leave, which is the gap worth
watching. Staff and superusers are left out unless include_staff is set.
"""
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import F, Max, Q
from django.utils import timezone

from board.models import (
    AccountabilityPartner, BlockLog, DailyData, DayPlan, Feedback, Friend, GoogleCalendarToken,
    Habit, HabitLog, HabitStepLog, JournalEntry, MetricEntry, ReadingListItem, RoutineEntry,
    Task, TaskGroup, UserDetail,
)

log = logging.getLogger(__name__)

CACHE_SECONDS = 15 * 60
RETENTION_WEEKS = 8
LOW_USE_SHARE = 0.10        # under 10% of monthly doers = candidate to simplify or cut
MIN_MAU_TO_JUDGE = 10       # below this, adoption shares are noise


# ── Activity sources ─────────────────────────────────────────────────────

def _not_seed(qs):
    """Signup seeds rows (todos, routine) with bulk_create; skip rows the user never touched."""
    return qs.exclude(
        created_at__lt=F('user__date_joined') + timedelta(minutes=2),
        updated_at__lt=F('created_at') + timedelta(seconds=60),
    )


# (feature label, what counts, queryset, user path, timestamp field)
FEATURES = [
    ('Habits', 'Ticked a habit', lambda: HabitLog.objects.filter(is_done=True, habit__is_system=False), 'habit__user_id', 'updated_at'),
    ('Habit checklists', 'Ticked a habit step', lambda: HabitStepLog.objects.filter(done=True), 'step__habit__user_id', 'date'),
    ('Todos', 'Added or edited a todo', lambda: _not_seed(Task.objects.all()), 'user_id', 'updated_at'),
    ('Todo groups', 'Created a todo group', lambda: TaskGroup.objects.all(), 'user_id', 'created_at'),
    ('Routine timeline', 'Edited a routine block', lambda: _not_seed(RoutineEntry.objects.all()), 'user_id', 'updated_at'),
    ('Block check-offs', 'Marked a routine block done/missed', lambda: BlockLog.objects.all(), 'user_id', 'logged_at'),
    ('Day types', 'Switched a day to Light/Disrupted/Off', lambda: DayPlan.objects.exclude(mode='normal'), 'user_id', 'date'),
    ('Trackers', 'Logged a custom tracker', lambda: MetricEntry.objects.filter(metric__is_system=False), 'metric__user_id', 'at'),
    ('Sleep tracker', 'Logged sleep', lambda: MetricEntry.objects.filter(metric__system_key='sleep'), 'metric__user_id', 'at'),
    ('Journals', 'Wrote a journal entry', lambda: JournalEntry.objects.all(), 'journal__user_id', 'at'),
    ('Pomodoro', 'Logged focus minutes', lambda: DailyData.objects.filter(focus_minutes__gt=0), 'user_id', 'date'),
    ('Bookmarks', 'Saved a bookmark', lambda: ReadingListItem.objects.all(), 'user_id', 'created_at'),
    ('Accountability partners', 'Invited a partner', lambda: AccountabilityPartner.objects.all(), 'habit__user_id', 'created_at'),
    ('Friends', 'Added a friend', lambda: Friend.objects.all(), 'user_id', 'created_at'),
    ('Google Calendar', 'Connected a calendar', lambda: GoogleCalendarToken.objects.all(), 'user_id', 'created_at'),
    ('Privacy mode', 'Set a PIN', lambda: UserDetail.objects.exclude(private_pin_hash=''), 'user_id', 'updated_at'),
    ('Feedback', 'Sent feedback', lambda: Feedback.objects.filter(user__isnull=False), 'user_id', 'created_at'),
]

# Everything that counts as "did something" for doer DAU and retention
ACTIVITY = [f for f in FEATURES if f[0] not in ('Privacy mode', 'Feedback', 'Google Calendar')] + [
    ('Habit created', '', lambda: Habit.objects.filter(is_system=False), 'user_id', 'created_at'),
]


def _to_date(value):
    if hasattr(value, 'hour'):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def excluded_user_ids(include_staff):
    if include_staff:
        return set()
    return set(User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).values_list('id', flat=True))


def _activity_by_user(since, exclude):
    """{user_id: set(dates)} of doer activity on or after `since`."""
    out = defaultdict(set)
    for _, _, qs, user_path, ts in ACTIVITY:
        rows = qs().filter(**{f'{ts}__gte': since}).values_list(user_path, ts)
        for uid, when in rows.iterator():
            if uid and uid not in exclude:
                out[uid].add(_to_date(when))
    return out


# ── Postgres metrics ─────────────────────────────────────────────────────

def db_metrics(days, include_staff=False):
    today = timezone.localdate()
    exclude = excluded_user_ids(include_staff)
    users = User.objects.filter(is_active=True).exclude(id__in=exclude)
    joined = {uid: timezone.localtime(dj).date() for uid, dj in users.values_list('id', 'date_joined')}

    span = max(days, RETENTION_WEEKS * 7 * 2)
    since = today - timedelta(days=span)
    activity = _activity_by_user(since, exclude)
    activity = {uid: d for uid, d in activity.items() if uid in joined}

    def active_between(start, end):
        return {uid for uid, ds in activity.items() if any(start <= d <= end for d in ds)}

    dau = len(active_between(today, today))
    wau = len(active_between(today - timedelta(days=6), today))
    mau_set = active_between(today - timedelta(days=29), today)
    mau = len(mau_set)

    # Daily series
    labels = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    per_day = defaultdict(int)
    for ds in activity.values():
        for d in ds:
            per_day[d] += 1
    signups_per_day = defaultdict(int)
    for d in joined.values():
        signups_per_day[d] += 1

    # Weekly cohorts by signup week, retention in user-relative weeks
    week_start = today - timedelta(days=today.weekday())
    cohorts = []
    for w in range(RETENTION_WEEKS - 1, -1, -1):
        c_start = week_start - timedelta(weeks=w)
        c_end = c_start + timedelta(days=6)
        members = [uid for uid, d in joined.items() if c_start <= d <= c_end]
        row = {'week': c_start, 'size': len(members), 'cells': []}
        for k in range(RETENTION_WEEKS):
            # Show a cell only once week k has ended for the cohort's last joiner
            if c_end + timedelta(days=7 * k + 6) >= today:
                row['cells'].append(None)
                continue
            kept = 0
            for uid in members:
                lo = joined[uid] + timedelta(days=7 * k)
                hi = lo + timedelta(days=6)
                if any(lo <= d <= hi for d in activity.get(uid, ())):
                    kept += 1
            row['cells'].append(round(100 * kept / len(members)) if members else None)
        cohorts.append(row)

    # Activation funnel for people who signed up in the window
    window_joiners = [uid for uid, d in joined.items() if d >= today - timedelta(days=days - 1)]
    onboarded = set(UserDetail.objects.filter(user_id__in=window_joiners, is_onboarded=True).values_list('user_id', flat=True))
    acted = {u for u in window_joiners if activity.get(u)}
    second_day = {u for u in acted if len({d for d in activity[u] if d < joined[u] + timedelta(days=7)}) >= 2}
    week2 = {u for u in acted if any(joined[u] + timedelta(days=7) <= d < joined[u] + timedelta(days=14) for d in activity[u])}
    n = len(window_joiners)
    funnel = [
        ('Signed up', n),
        ('Finished setup', len(onboarded)),
        ('Did something', len(acted)),
        ('Came back on a 2nd day (week 1)', len(second_day)),
        ('Active in week 2', len(week2)),
    ]
    funnel = [{'label': lbl, 'count': c, 'pct': round(100 * c / n) if n else 0} for lbl, c in funnel]

    # Feature adoption: who has ever used it, who used it in the last 30 days
    cutoff = today - timedelta(days=29)
    features = []
    for label, what, qs, user_path, ts in FEATURES:
        last_by_user = {}
        for uid, last in qs().values(user_path).annotate(last=Max(ts)).values_list(user_path, 'last'):
            if uid in joined:
                last_by_user[uid] = _to_date(last)
        recent = sum(1 for d in last_by_user.values() if d and d >= cutoff)
        share = recent / mau if mau else 0
        features.append({
            'label': label,
            'what': what,
            'ever': len(last_by_user),
            'ever_pct': round(100 * len(last_by_user) / len(joined)) if joined else 0,
            'recent': recent,
            'share': round(100 * share),
            'last_used': max((d for d in last_by_user.values() if d), default=None),
            'flag': ('low' if share < LOW_USE_SHARE else '') if mau >= MIN_MAU_TO_JUDGE else 'thin',
        })
    features.sort(key=lambda f: (-f['recent'], -f['ever']))

    from allauth.socialaccount.models import SocialAccount
    google = SocialAccount.objects.filter(provider='google', user_id__in=list(joined)).values('user_id').distinct().count()

    return {
        'total_users': len(joined),
        'signups_today': signups_per_day.get(today, 0),
        'signups_7d': sum(1 for d in joined.values() if d >= today - timedelta(days=6)),
        'signups_30d': sum(1 for d in joined.values() if d >= today - timedelta(days=29)),
        'signups_google': google,
        'dau': dau, 'wau': wau, 'mau': mau,
        'stickiness': round(100 * dau / mau) if mau else 0,
        'labels': [d.isoformat() for d in labels],
        'doers_series': [per_day.get(d, 0) for d in labels],
        'signups_series': [signups_per_day.get(d, 0) for d in labels],
        'cohorts': cohorts,
        'funnel': funnel,
        'features': features,
        'excluded': len(exclude),
    }


# ── PostHog metrics ──────────────────────────────────────────────────────

def posthog_configured():
    return bool(settings.POSTHOG_PERSONAL_API_KEY and settings.POSTHOG_PROJECT_ID)


def _hogql(sql):
    url = f"{settings.POSTHOG_APP_HOST.rstrip('/')}/api/projects/{settings.POSTHOG_PROJECT_ID}/query/"
    res = requests.post(
        url,
        json={'query': {'kind': 'HogQLQuery', 'query': sql}, 'name': 'myr-internal-dashboard'},
        headers={'Authorization': f'Bearer {settings.POSTHOG_PERSONAL_API_KEY}'},
        timeout=25,
    )
    res.raise_for_status()
    return res.json().get('results') or []


def _web_handlers():
    """onclick handler names in the board template, to spot controls nobody clicks."""
    path = Path(settings.BASE_DIR) / 'templates' / 'board' / 'dashboard.html'
    try:
        html = path.read_text()
    except OSError:
        return set()
    names = set(re.findall(r'onclick="\s*(?:return\s+)?([\w$.]+)\s*\(', html))
    return {n for n in names if not n.startswith(('event.', 'this.', 'window.'))}


def posthog_metrics(days, exclude):
    days = int(days)
    excl = ''
    if exclude:
        excl = 'AND distinct_id NOT IN (' + ', '.join(f"'{int(i)}'" for i in sorted(exclude)) + ')'
    window = f"timestamp >= now() - INTERVAL {days} DAY {excl}"
    opened = "event IN ('app_opened', 'view_time', 'ui_click')"

    queries = {
        'headline': f"""
            SELECT count(DISTINCT if(timestamp >= now() - INTERVAL 1 DAY, distinct_id, NULL)),
                   count(DISTINCT if(timestamp >= now() - INTERVAL 7 DAY, distinct_id, NULL)),
                   count(DISTINCT if(timestamp >= now() - INTERVAL 30 DAY, distinct_id, NULL)),
                   sum(if(event = 'view_time', toFloat(properties.seconds), 0)) / 60
            FROM events WHERE {opened} AND timestamp >= now() - INTERVAL 30 DAY {excl}""",
        'daily': f"""
            SELECT toDate(timestamp) AS d, count(DISTINCT distinct_id),
                   sum(if(event = 'view_time', toFloat(properties.seconds), 0)) / 60
            FROM events WHERE {opened} AND {window}
            GROUP BY d ORDER BY d""",
        'views': f"""
            SELECT properties.view AS v, any(properties.kind), count(DISTINCT distinct_id),
                   count(), sum(toFloat(properties.seconds)) / 60, median(toFloat(properties.seconds))
            FROM events WHERE event = 'view_time' AND {window}
            GROUP BY v ORDER BY sum(toFloat(properties.seconds)) DESC LIMIT 80""",
        'clicks': f"""
            SELECT properties.action AS a, sum(toInt(properties.count)), count(DISTINCT distinct_id),
                   any(properties.view)
            FROM events WHERE event = 'ui_click' AND {window}
            GROUP BY a ORDER BY sum(toInt(properties.count)) DESC LIMIT 400""",
        'clients': f"""
            SELECT properties.client AS c, count(DISTINCT distinct_id), count()
            FROM events WHERE event = 'app_opened' AND {window}
            GROUP BY c ORDER BY count(DISTINCT distinct_id) DESC""",
        'features': f"""
            SELECT event, count(DISTINCT distinct_id), count()
            FROM events WHERE event NOT IN ('app_opened', 'view_time', 'ui_click', '$set', '$identify')
              AND {window}
            GROUP BY event ORDER BY count(DISTINCT distinct_id) DESC LIMIT 50""",
    }
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = {k: pool.submit(_hogql, q) for k, q in queries.items()}
        raw = {k: f.result() for k, f in futures.items()}

    h = (raw['headline'] or [[0, 0, 0, 0]])[0]
    total_views_min = sum(r[4] or 0 for r in raw['views']) or 1
    views = [{
        'view': r[0], 'kind': r[1], 'users': r[2], 'visits': r[3],
        'minutes': round(r[4] or 0, 1), 'share': round(100 * (r[4] or 0) / total_views_min),
        'median_s': round(r[5] or 0), 'per_user_min': round((r[4] or 0) / r[2], 1) if r[2] else 0,
    } for r in raw['views'] if r[0]]

    clicks = [{'action': r[0], 'count': int(r[1] or 0), 'users': r[2], 'seen_on': r[3] or ''}
              for r in raw['clicks'] if r[0]]
    clicked = {c['action'] for c in clicks}
    never = sorted(_web_handlers() - clicked)

    daily = {str(r[0]): (r[1], round(r[2] or 0, 1)) for r in raw['daily']}
    return {
        'dau': h[0], 'wau': h[1], 'mau': h[2],
        'minutes_30d': round(h[3] or 0),
        'minutes_per_user': round((h[3] or 0) / h[2], 1) if h[2] else 0,
        'daily': daily,
        'views': views,
        'top_clicks': clicks[:25],
        'rare_clicks': [c for c in reversed(clicks) if c['count'] <= 3][:25],
        'never_clicked': never,
        'clients': [{'client': r[0] or 'unknown', 'users': r[1], 'opens': r[2]} for r in raw['clients']],
        'feature_events': [{'event': r[0], 'users': r[1], 'count': r[2]} for r in raw['features']],
    }


# ── Entry point ──────────────────────────────────────────────────────────

def dashboard_data(days=30, include_staff=False, refresh=False):
    days = 90 if int(days) >= 90 else 30
    key = f'internal-dash:{days}:{int(bool(include_staff))}'
    if not refresh:
        hit = cache.get(key)
        if hit:
            return hit

    data = {'days': days, 'include_staff': include_staff, 'db': db_metrics(days, include_staff),
            'posthog': None, 'posthog_error': None, 'posthog_configured': posthog_configured(),
            'generated_at': timezone.localtime()}
    if data['posthog_configured']:
        try:
            ph = posthog_metrics(days, excluded_user_ids(include_staff))
            ph['openers_series'] = [ph['daily'].get(d, (0, 0))[0] for d in data['db']['labels']]
            ph['minutes_series'] = [ph['daily'].get(d, (0, 0))[1] for d in data['db']['labels']]
            data['posthog'] = ph
        except Exception as exc:
            log.exception('PostHog query failed')
            data['posthog_error'] = str(exc)[:300]
    cache.set(key, data, CACHE_SECONDS)
    return data

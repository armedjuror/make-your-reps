"""
API for resilient days: day plans, block logs, running late, slips and
resets, travel; plus metrics, habit checklists, journals and privacy mode.
"""
from datetime import date, datetime, timedelta
from functools import wraps

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import status as http
from rest_framework.response import Response
from rest_framework.views import APIView

from board import metrics as mx
from board import privacy
from board.days import (
    SYSTEM_SOURCES, day_payload, default_template, get_detail, logical_today,
    resolve_day,
)
from board.gamification import award_points, deduct_points, update_daily_streak
from board.models import (
    BlockLog, DayMode, DayPlan, Habit, HabitLog, HabitStatus, HabitStep, HabitStepLog,
    Journal, JournalEntry, Metric, MetricEntry, MetricKind, RoutineEntry, RoutineType, Tier,
)
from board.streaks import refresh_streak

LATE_CHOICES = (15, 30, 60)
EDIT_AHEAD_DAYS = 3
TRAVEL_MAX_DAYS = 60
RESET_STEPS = ['Drink some water', 'Eat a proper meal', 'Walk for 10 minutes', 'Start the next block']


def fail(msg, code=http.HTTP_400_BAD_REQUEST, **extra):
    return Response({'status': 'failed', 'error': msg, **extra}, status=code)


def ok(data=None, **extra):
    return Response({'status': 'success', 'data': data, **extra})


def auth(fn):
    """Session-authenticated view method; passes ``user_id`` through."""
    @wraps(fn)
    def wrapper(self, request, *args, **kwargs):
        user_id = request.session.get('user_id')
        if not user_id:
            return fail('Not authenticated', http.HTTP_401_UNAUTHORIZED)
        return fn(self, request, user_id, *args, **kwargs)
    return wrapper


def parse_date(value):
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        return None


def hidden_ids(request, user_id):
    """Ids of private habits and metrics the request may not see (empty when unlocked)."""
    if privacy.include_private(request):
        return set(), set()
    return (
        set(Habit.objects.filter(user_id=user_id, is_private=True).values_list('id', flat=True)),
        set(Metric.objects.filter(user_id=user_id, is_private=True).values_list('id', flat=True)),
    )


# ── Reset habit (hidden system habit) ──────────────────────

def ensure_reset_habit(user_id):
    habit = Habit.objects.filter(user_id=user_id, is_system=True).first()
    if not habit:
        habit = Habit.objects.create(
            user_id=user_id, habit='Reset', identity='Someone who gets back on track',
            frequency=[], is_system=True, complete_when='all',
            on_light='excused', on_disrupted='excused',
        )
        for i, name in enumerate(RESET_STEPS):
            HabitStep.objects.create(habit=habit, order=i, name=name)
    return habit


def reset_state(user_id, resolved, now=None):
    """
    Whether today needs a reset card and when it appeared. Triggers: a slip, a
    missed essential block, or an 'at most' metric over its limit.
    """
    target_date = resolved['date']
    plan = resolved['plan']
    now = now or timezone.now()
    times = []
    if plan and plan.slips:
        for s in plan.slips:
            try:
                times.append(datetime.fromisoformat(s['at']))
            except (KeyError, ValueError):
                pass
    for b in resolved['blocks']:
        if b['tier'] == Tier.ESSENTIAL and b['status'] == 'missed':
            times.append(b['end'] + timedelta(minutes=30))
    for m in Metric.objects.filter(user_id=user_id, direction='at_most', target__isnull=False):
        if mx.breached(m, user_id, target_date):
            last = MetricEntry.objects.filter(metric=m, date=target_date).order_by('-at').first()
            times.append(last.at if last else now)
    times = [t for t in times if t <= now]
    if not times:
        return None
    ts = max(times)
    done = bool(plan and plan.reset_done_at and plan.reset_done_at >= ts)
    return {'at': ts, 'done': done}


def reset_event(user_id, target_date, state):
    habit = ensure_reset_habit(user_id)
    stage_steps = HabitStep.objects.filter(habit=habit)
    done_ids = set(HabitStepLog.objects.filter(step__habit=habit, date=target_date, done=True)
                   .values_list('step_id', flat=True))
    ts = timezone.localtime(state['at']).isoformat()
    return {
        'id': f'reset-{target_date}',
        'timestamp': ts,
        'event_type': 'text',
        'event': 'Take a minute to reset. The rest of the day is still yours.',
        'reference': {'model': 'Habit', 'id': habit.id},
        'action': None if state['done'] else {'reset': ['done', 'light']},
        'action_response': {'reset': 'done'} if state['done'] else None,
        'reset': {
            'habit_id': habit.id,
            'steps': [{'id': s.id, 'name': s.name, 'done': s.id in done_ids} for s in stage_steps],
        },
        'created_at': ts,
        'updated_at': ts,
    }


def freeze_event(user_id, today):
    """Next morning: 'Freeze used for Tue 4 Nov - 1 left'."""
    from board.models import DaySummary
    y = today - timedelta(days=1)
    if not DaySummary.objects.filter(user_id=user_id, date=y, outcome='frozen').exists():
        return None
    left = get_detail(user_id).freezes
    detail = get_detail(user_id)
    ts = timezone.make_aware(datetime.combine(today, detail.day_start)).isoformat()
    return {
        'id': f'freeze-{today}',
        'timestamp': ts,
        'event_type': 'text',
        'event': f"Freeze used for {y.strftime('%a')} {y.day} {y.strftime('%b')} — {left} left",
        'reference': None, 'action': None, 'action_response': None,
        'created_at': ts, 'updated_at': ts,
    }


# ── Day plans ──────────────────────────────────────────────

def _get_or_make_plan(user_id, detail, target_date, source):
    plan = DayPlan.objects.filter(user_id=user_id, date=target_date).first()
    if plan:
        return plan
    return DayPlan.objects.create(
        user_id=user_id, date=target_date,
        template=default_template(detail, target_date), mode=DayMode.NORMAL, source=source,
    )


class DayPlansView(APIView):
    @auth
    def get(self, request, user_id):
        start, end = parse_date(request.GET.get('from')), parse_date(request.GET.get('to'))
        detail = get_detail(user_id)
        today = logical_today(user_id, detail=detail)
        start = start or today
        end = end or start + timedelta(days=EDIT_AHEAD_DAYS)
        if end < start or (end - start).days > 31:
            return fail('from/to must be a range of at most 31 days')
        days, d = [], start
        while d <= end:
            days.append(day_payload(resolve_day(user_id, d, detail=detail)))
            d += timedelta(days=1)
        return ok(days)


class DayPlanDetailView(APIView):
    @auth
    def put(self, request, user_id, date):
        target = parse_date(date)
        if not target:
            return fail('Invalid date')
        detail = get_detail(user_id)
        today = logical_today(user_id, detail=detail)
        if target < today:
            return fail('That day has closed')
        if target > today + timedelta(days=EDIT_AHEAD_DAYS):
            return fail(f'Plans can be set up to {EDIT_AHEAD_DAYS} days ahead')
        template, mode = request.data.get('template'), request.data.get('mode')
        if template is not None and template not in RoutineType.values:
            return fail('template must be workday or holiday')
        if mode is not None and mode not in DayMode.values:
            return fail('mode must be normal, light or disrupted')
        if template is None and mode is None:
            return fail('template or mode is required')
        source = request.data.get('source', 'manual')
        if source not in ('manual', 'checkin'):
            source = 'manual'
        plan = DayPlan.objects.filter(user_id=user_id, date=target).first()
        if plan is None:
            plan = DayPlan(user_id=user_id, date=target, template=default_template(detail, target))
        if template:
            plan.template = template
        if mode:
            plan.mode = mode
        plan.source = source
        plan.save()
        if target == today:
            refresh_streak(user_id)
        return ok(day_payload(resolve_day(user_id, target, detail=detail)))


class BlockLogView(APIView):
    """PUT marks a routine block done or skipped; DELETE undoes it. Open until the date closes."""

    def _check(self, user_id, date, entry_id):
        target = parse_date(date)
        if not target:
            return None, None, fail('Invalid date')
        today = logical_today(user_id)
        if target != today:
            return None, None, fail('Only today can be logged; closed days are read-only', http.HTTP_409_CONFLICT)
        entry = RoutineEntry.objects.filter(pk=entry_id, user_id=user_id).first()
        if not entry:
            return None, None, fail('Routine block not found', http.HTTP_404_NOT_FOUND)
        return target, entry, None

    @auth
    def put(self, request, user_id, date, entry_id):
        target, entry, err = self._check(user_id, date, entry_id)
        if err:
            return err
        status = request.data.get('status')
        if status not in ('done', 'skipped'):
            return fail('status must be done or skipped')
        reason = str(request.data.get('reason', ''))[:120]
        BlockLog.objects.update_or_create(
            user_id=user_id, date=target, entry=entry,
            defaults={'title': entry.title, 'scheduled_time': entry.time, 'tier': entry.tier,
                      'status': status, 'reason': reason if status == 'skipped' else ''},
        )
        refresh_streak(user_id)
        return ok(day_payload(resolve_day(user_id, target)))

    @auth
    def delete(self, request, user_id, date, entry_id):
        target = parse_date(date)
        if not target or target != logical_today(user_id):
            return fail('Only today can be changed', http.HTTP_409_CONFLICT)
        BlockLog.objects.filter(user_id=user_id, date=target, entry_id=entry_id).delete()
        refresh_streak(user_id)
        return ok(day_payload(resolve_day(user_id, target)))


class RunningLateView(APIView):
    @auth
    def post(self, request, user_id, date):
        target = parse_date(date)
        detail = get_detail(user_id)
        if not target or target != logical_today(user_id, detail=detail):
            return fail('Running late applies to today only')
        try:
            minutes = int(request.data.get('minutes'))
        except (TypeError, ValueError):
            minutes = None
        if minutes not in LATE_CHOICES:
            return fail('minutes must be 15, 30 or 60')
        plan = _get_or_make_plan(user_id, detail, target, 'late')
        plan.shifts = [*plan.shifts, {'at': timezone.now().isoformat(), 'minutes': minutes}]
        plan.save(update_fields=['shifts'])
        return ok(day_payload(resolve_day(user_id, target, detail=detail)))

    @auth
    def delete(self, request, user_id, date):
        target = parse_date(date)
        detail = get_detail(user_id)
        if not target or target != logical_today(user_id, detail=detail):
            return fail('Running late applies to today only')
        plan = DayPlan.objects.filter(user_id=user_id, date=target).first()
        if plan and plan.shifts:
            plan.shifts = plan.shifts[:-1]
            plan.save(update_fields=['shifts'])
        return ok(day_payload(resolve_day(user_id, target, detail=detail)))


class ResetView(APIView):
    """Finishing the reset card saves the day: points, and Normal moves to Light."""

    @auth
    @transaction.atomic
    def put(self, request, user_id, date):
        target = parse_date(date)
        detail = get_detail(user_id)
        if not target or target != logical_today(user_id, detail=detail):
            return fail('Reset applies to today only')
        resolved = resolve_day(user_id, target, detail=detail)
        state = reset_state(user_id, resolved)
        if not state:
            return fail('Nothing to reset', http.HTTP_409_CONFLICT)
        plan = resolved['plan'] or _get_or_make_plan(user_id, detail, target, 'reset')
        already = plan.reset_done_at and plan.reset_done_at >= state['at']
        plan.reset_done_at = timezone.now()
        if plan.mode == DayMode.NORMAL and plan.source in (SYSTEM_SOURCES | {'late'}):
            plan.mode, plan.source = DayMode.LIGHT, 'reset'
        plan.save()
        points = {} if already else award_points(user_id, 'reset')
        update_daily_streak(user_id)
        refresh_streak(user_id)
        return ok(day_payload(resolve_day(user_id, target, detail=detail)), gamification=points)


class SlipView(APIView):
    """'I slipped': private, adds one to the Slips tracker, and brings the reset card."""

    @auth
    def post(self, request, user_id):
        detail = get_detail(user_id)
        target = logical_today(user_id, detail=detail)
        note = str(request.data.get('note', '')).strip()[:280]
        plan = _get_or_make_plan(user_id, detail, target, 'slip')
        plan.slips = [*plan.slips, {'at': timezone.now().isoformat(), 'note': note}]
        plan.save(update_fields=['slips'])
        # Every slip counts on the built-in private Slips tracker; the note goes to its journal
        mx.log_entry(mx.ensure_slip_metric(user_id), value=1, note=note)
        return ok(day_payload(resolve_day(user_id, target, detail=detail)))


class TravelView(APIView):
    """
    Off days (travel, night shift, unwell…): the dates become Light or Disrupted,
    with the reason on the plan and in that day's journal. After a Disrupted
    stretch, the next ``travel_ramp_days`` are Light. Never overwrites a manual row.
    """

    @auth
    def post(self, request, user_id):
        detail = get_detail(user_id)
        today = logical_today(user_id, detail=detail)
        start = parse_date(request.data.get('start')) or today
        end = parse_date(request.data.get('end')) or start
        reason = request.data.get('reason') or 'travel'
        if reason not in mx.OFF_REASONS:
            return fail('Unknown reason')
        note = str(request.data.get('note', '')).strip()[:120]
        mode = request.data.get('mode') or (DayMode.DISRUPTED if reason == 'travel' else DayMode.LIGHT)
        if mode not in (DayMode.LIGHT, DayMode.DISRUPTED):
            return fail('mode must be light or disrupted')
        if end < start or start < today:
            return fail('Off days must be today or later, and end after start')
        if (end - start).days + 1 > TRAVEL_MAX_DAYS:
            return fail(f'Off days can span at most {TRAVEL_MAX_DAYS} days')
        label = mx.OFF_REASONS[reason] + (f': {note}' if note else '')
        applied, skipped = [], []
        dates = [(start + timedelta(days=i), mode, 'travel') for i in range((end - start).days + 1)]
        if mode == DayMode.DISRUPTED:
            dates += [(end + timedelta(days=i + 1), DayMode.LIGHT, 'ramp') for i in range(detail.travel_ramp_days)]
        for d, m, source in dates:
            plan = DayPlan.objects.filter(user_id=user_id, date=d).first()
            if plan and plan.source in ('manual', 'checkin'):
                skipped.append(d.isoformat())
                continue
            if plan is None:
                plan = DayPlan(user_id=user_id, date=d, template=default_template(detail, d))
            elif source == 'ramp' and plan.source == 'travel':
                continue  # a later off day already covers it
            plan.mode, plan.source = m, source
            plan.reason = label[:160] if source == 'travel' else ''
            plan.save()
            if source == 'travel':
                mx.note_off_day(user_id, d, reason, note)
            applied.append(d.isoformat())
        return ok({'applied': applied, 'skipped': skipped})

    @auth
    def delete(self, request, user_id):
        detail = get_detail(user_id)
        today = logical_today(user_id, detail=detail)
        start = parse_date(request.GET.get('from') or request.data.get('start')) or today
        end = parse_date(request.GET.get('to') or request.data.get('end')) or start
        last = end + timedelta(days=detail.travel_ramp_days)
        deleted, _ = DayPlan.objects.filter(
            user_id=user_id, date__gte=max(start, today), date__lte=last, source__in=('travel', 'ramp'),
        ).delete()
        return ok({'deleted': deleted})


# ── Metrics ────────────────────────────────────────────────

def metric_json(metric, request=None):
    today = logical_today(metric.user_id)
    target = mx.effective_target(metric, metric.user_id, today)
    return {
        'id': metric.id, 'name': metric.name, 'unit': metric.unit, 'kind': metric.kind,
        'direction': metric.direction,
        'target': float(metric.target) if metric.target is not None else None,
        'target_light': float(metric.target_light) if metric.target_light is not None else None,
        'quick_steps': [float(x) for x in metric.quick_steps],
        'fields': metric.fields, 'is_private': metric.is_private, 'is_system': metric.is_system,
        'system_key': metric.system_key,
        'remind_at': (lambda t: t.strftime('%H:%M') if t else None)(mx.reminder_time(metric)),
        'habit_ids': list(Habit.objects.filter(user_id=metric.user_id, metric_id=metric.id).values_list('id', flat=True)),
        'today': float(mx.day_value(metric, today)),
        'today_target': float(target) if target is not None else None,
        'chips': mx.chips(metric),
    }


def apply_metric_payload(metric, data):
    """Copy writable fields from a request body onto a metric; raises ValueError."""
    if 'name' in data:
        name = str(data['name']).strip()
        if not name:
            raise ValueError('name is required')
        metric.name = name[:64]
    if 'unit' in data:
        metric.unit = str(data['unit'])[:16]
    if 'kind' in data:
        if data['kind'] not in MetricKind.values:
            raise ValueError('invalid kind')
        metric.kind = data['kind']
    if 'direction' in data:
        if data['direction'] not in ('at_least', 'at_most'):
            raise ValueError('direction must be at_least or at_most')
        metric.direction = data['direction']
    for key in ('target', 'target_light'):
        if key in data:
            metric_val = data[key]
            setattr(metric, key, None if metric_val in (None, '') else mx.Decimal(str(metric_val)))
    if 'quick_steps' in data:
        metric.quick_steps = [mx.Decimal(str(x)) for x in (data['quick_steps'] or [])][:8]
    if 'fields' in data:
        metric.fields = mx.clean_fields(data['fields'])
    if 'is_private' in data:
        metric.is_private = bool(data['is_private'])
    if 'remind_at' in data:
        v = data['remind_at']
        if v in (None, ''):
            metric.remind_at = None
        else:
            from datetime import datetime as _dt
            try:
                metric.remind_at = _dt.strptime(str(v)[:5], '%H:%M').time()
            except ValueError:
                raise ValueError('remind_at must be HH:MM')


class MetricsView(APIView):
    @auth
    def get(self, request, user_id):
        mx.ensure_sleep_metric(user_id)
        mx.ensure_slip_metric(user_id)
        _, hidden = hidden_ids(request, user_id)
        qs = Metric.objects.filter(user_id=user_id).exclude(id__in=hidden)
        return ok([metric_json(m) for m in qs])

    @auth
    def post(self, request, user_id):
        metric = Metric(user_id=user_id)
        try:
            apply_metric_payload(metric, request.data)
            if not metric.name:
                raise ValueError('name is required')
            metric.save()
        except (ValueError, ArithmeticError) as e:
            return fail(str(e))
        if metric.kind == MetricKind.COUNTER and not metric.quick_steps:
            metric.quick_steps = [1]
            metric.save(update_fields=['quick_steps'])
        return Response({'status': 'success', 'data': metric_json(metric)}, status=http.HTTP_201_CREATED)


def _own_metric(request, user_id, pk):
    _, hidden = hidden_ids(request, user_id)
    if int(pk) in hidden:
        return None
    return Metric.objects.filter(pk=pk, user_id=user_id).first()


class MetricDetailView(APIView):
    @auth
    def get(self, request, user_id, pk):
        metric = _own_metric(request, user_id, pk)
        return ok(metric_json(metric)) if metric else fail('Metric not found', http.HTTP_404_NOT_FOUND)

    @auth
    def put(self, request, user_id, pk):
        metric = _own_metric(request, user_id, pk)
        if not metric:
            return fail('Metric not found', http.HTTP_404_NOT_FOUND)
        try:
            apply_metric_payload(metric, request.data)
            metric.save()
        except (ValueError, ArithmeticError) as e:
            return fail(str(e))
        Journal.objects.filter(metric=metric).update(is_private=metric.is_private)
        return ok(metric_json(metric))

    @auth
    def delete(self, request, user_id, pk):
        metric = _own_metric(request, user_id, pk)
        if not metric:
            return fail('Metric not found', http.HTTP_404_NOT_FOUND)
        if metric.is_system:
            return fail(f'{metric.name} is built in and cannot be deleted')
        metric.delete()
        return ok(message='Metric deleted')


class MetricLogView(APIView):
    """POST logs a value; DELETE undoes the last entry for the day."""

    @auth
    def post(self, request, user_id, pk):
        metric = _own_metric(request, user_id, pk)
        if not metric:
            return fail('Metric not found', http.HTTP_404_NOT_FOUND)
        at = timezone.now()
        if request.data.get('at'):
            try:
                at = datetime.fromisoformat(str(request.data['at']))
                if timezone.is_naive(at):
                    at = timezone.make_aware(at)
            except ValueError:
                return fail('Invalid at')
            if at > timezone.now() + timedelta(minutes=1):
                return fail('Cannot log in the future')
        try:
            entry = mx.log_entry(metric, value=request.data.get('value'), data=request.data.get('data'),
                                 note=request.data.get('note', ''), at=at)
        except (ValueError, ArithmeticError) as e:
            return fail(str(e))
        update_daily_streak(user_id)
        return Response({'status': 'success', 'data': {**metric_json(metric), 'entry_id': entry.id}},
                        status=http.HTTP_201_CREATED)

    @auth
    def delete(self, request, user_id, pk):
        metric = _own_metric(request, user_id, pk)
        if not metric:
            return fail('Metric not found', http.HTTP_404_NOT_FOUND)
        target = parse_date(request.GET.get('date')) or logical_today(user_id)
        mx.undo_last(metric, target)
        return ok(metric_json(metric))


class MetricInsightsView(APIView):
    @auth
    def get(self, request, user_id, pk):
        metric = _own_metric(request, user_id, pk)
        if not metric:
            return fail('Metric not found', http.HTTP_404_NOT_FOUND)
        days = max(1, min(int(request.GET.get('days', 30) or 30), 180))
        return ok(mx.insights(metric, days))


# ── Habit checklists ───────────────────────────────────────

def step_json(step, done_ids, values, stage):
    return {
        'id': step.id, 'order': step.order, 'name': step.name, 'target': step.target,
        'how_to': step.how_to, 'stage': step.stage, 'metric': step.metric_id,
        'visible': step.stage <= stage, 'done': step.id in done_ids,
        'value': values.get(step.id),
    }


def _habit_for(request, user_id, habit_id):
    hidden, _ = hidden_ids(request, user_id)
    if int(habit_id) in hidden:
        return None
    return Habit.objects.filter(pk=habit_id, user_id=user_id).exclude(status=HabitStatus.DELETED.value).first()


class HabitStepsView(APIView):
    @auth
    def get(self, request, user_id, habit_id):
        habit = _habit_for(request, user_id, habit_id)
        if not habit:
            return fail('Habit not found', http.HTTP_404_NOT_FOUND)
        if habit.is_system:
            ensure_reset_habit(user_id)
        target = parse_date(request.GET.get('date')) or logical_today(user_id)
        logs = HabitStepLog.objects.filter(step__habit=habit, date=target)
        done_ids = {l.step_id for l in logs if l.done}
        values = {l.step_id: float(l.value) for l in logs if l.value is not None}
        return ok({
            'current_stage': habit.current_stage, 'complete_when': habit.complete_when,
            'steps': [step_json(s, done_ids, values, habit.current_stage) for s in habit.steps.all()],
        })

    @auth
    def post(self, request, user_id, habit_id):
        habit = _habit_for(request, user_id, habit_id)
        if not habit:
            return fail('Habit not found', http.HTTP_404_NOT_FOUND)
        name = str(request.data.get('name', '')).strip()
        if not name:
            return fail('name is required')
        metric = None
        if request.data.get('metric'):
            metric = Metric.objects.filter(pk=request.data['metric'], user_id=user_id).first()
            if not metric:
                return fail('Metric not found', http.HTTP_404_NOT_FOUND)
        last = habit.steps.order_by('-order').first()
        try:
            stage = max(1, int(request.data.get('stage', 1)))
        except (TypeError, ValueError):
            return fail('stage must be a number')
        step = HabitStep.objects.create(
            habit=habit, name=name[:120], target=str(request.data.get('target', ''))[:60],
            how_to=str(request.data.get('how_to', '')), stage=stage, metric=metric,
            order=int(request.data['order']) if str(request.data.get('order', '')).isdigit() else (last.order + 1 if last else 0),
        )
        return Response({'status': 'success', 'data': step_json(step, set(), {}, habit.current_stage)},
                        status=http.HTTP_201_CREATED)


def _own_step(request, user_id, pk):
    step = HabitStep.objects.select_related('habit').filter(pk=pk, habit__user_id=user_id).first()
    if step and _habit_for(request, user_id, step.habit_id) is None:
        return None
    return step


class HabitStepDetailView(APIView):
    @auth
    def put(self, request, user_id, pk):
        step = _own_step(request, user_id, pk)
        if not step:
            return fail('Step not found', http.HTTP_404_NOT_FOUND)
        for key, limit in (('name', 120), ('target', 60)):
            if key in request.data:
                setattr(step, key, str(request.data[key]).strip()[:limit])
        if 'how_to' in request.data:
            step.how_to = str(request.data['how_to'])
        for key in ('stage', 'order'):
            if key in request.data:
                try:
                    setattr(step, key, max(0, int(request.data[key])))
                except (TypeError, ValueError):
                    return fail(f'{key} must be a number')
        if 'metric' in request.data:
            if request.data['metric']:
                step.metric = Metric.objects.filter(pk=request.data['metric'], user_id=user_id).first()
                if not step.metric:
                    return fail('Metric not found', http.HTTP_404_NOT_FOUND)
            else:
                step.metric = None
        if not step.name:
            return fail('name is required')
        step.save()
        return ok(step_json(step, set(), {}, step.habit.current_stage))

    @auth
    def delete(self, request, user_id, pk):
        step = _own_step(request, user_id, pk)
        if not step:
            return fail('Step not found', http.HTTP_404_NOT_FOUND)
        step.delete()
        return ok(message='Step deleted')


class HabitStepLogView(APIView):
    """Tick a step. The habit is marked done according to ``complete_when``."""

    @auth
    def put(self, request, user_id, pk):
        step = _own_step(request, user_id, pk)
        if not step:
            return fail('Step not found', http.HTTP_404_NOT_FOUND)
        habit = step.habit
        today = logical_today(user_id)
        target = parse_date(request.data.get('date')) or today
        if target > today:
            return fail('This date is in future')
        if target < habit.created_at.date():
            return fail('This date is before the habit creation')
        done = bool(request.data.get('done', True))
        log, _ = HabitStepLog.objects.get_or_create(step=step, date=target)
        log.done = done
        value = request.data.get('value')
        if value not in (None, ''):
            try:
                log.value = mx.Decimal(str(value))
            except ArithmeticError:
                return fail('Invalid value')
        log.save()
        if step.metric_id and done and log.value is not None and target == today:
            try:
                mx.log_entry(step.metric, value=log.value, note='')
            except ValueError:
                pass
        habit_done = self._settle(habit, target, today, user_id)
        return ok({'step_id': step.id, 'done': log.done, 'habit_done': habit_done})

    @staticmethod
    def _settle(habit, target, today, user_id):
        steps = list(habit.steps.filter(stage__lte=habit.current_stage))
        if not steps:
            return None
        done_ids = set(HabitStepLog.objects.filter(step__in=steps, date=target, done=True)
                       .values_list('step_id', flat=True))
        complete = (len(done_ids) == len(steps)) if habit.complete_when == 'all' else bool(done_ids)
        hl, _ = HabitLog.objects.get_or_create(habit=habit, date=target)
        if hl.is_done != complete:
            hl.is_done = complete
            hl.save()
            if target == today and not habit.is_system:
                if complete:
                    update_daily_streak(user_id)
                    award_points(user_id, 'habit')
                else:
                    deduct_points(user_id, 'habit')
        return complete


# ── Journals ───────────────────────────────────────────────

def journal_json(j):
    return {'id': j.id, 'name': j.name, 'metric': j.metric_id, 'is_default': j.is_default,
            'is_private': j.is_private}


def entry_json(e):
    data = None
    if e.metric_entry_id:
        data = {'value': float(e.metric_entry.value), **e.metric_entry.data}
    return {'id': e.id, 'journal': e.journal_id, 'date': e.date.isoformat(),
            'at': timezone.localtime(e.at).isoformat(), 'text': e.text, 'metric': data}


def _visible_journals(request, user_id):
    qs = Journal.objects.filter(user_id=user_id)
    if not privacy.include_private(request):
        qs = qs.filter(is_private=False)
    return qs


class JournalsView(APIView):
    @auth
    def get(self, request, user_id):
        mx.ensure_default_journal(user_id)
        return ok([journal_json(j) for j in _visible_journals(request, user_id)])

    @auth
    def post(self, request, user_id):
        name = str(request.data.get('name', '')).strip()
        if not name:
            return fail('name is required')
        j = Journal.objects.create(user_id=user_id, name=name[:64],
                                   is_private=bool(request.data.get('is_private', False)))
        return Response({'status': 'success', 'data': journal_json(j)}, status=http.HTTP_201_CREATED)


class JournalDetailView(APIView):
    @auth
    def put(self, request, user_id, pk):
        j = _visible_journals(request, user_id).filter(pk=pk).first()
        if not j:
            return fail('Journal not found', http.HTTP_404_NOT_FOUND)
        if 'name' in request.data and str(request.data['name']).strip():
            j.name = str(request.data['name']).strip()[:64]
        if 'is_private' in request.data and not j.metric_id:
            j.is_private = bool(request.data['is_private'])
        j.save()
        return ok(journal_json(j))

    @auth
    def delete(self, request, user_id, pk):
        j = _visible_journals(request, user_id).filter(pk=pk).first()
        if not j:
            return fail('Journal not found', http.HTTP_404_NOT_FOUND)
        if j.is_default or j.metric_id:
            return fail('The default and metric journals cannot be deleted')
        j.delete()
        return ok(message='Journal deleted')


class JournalEntriesView(APIView):
    @auth
    def get(self, request, user_id, pk):
        j = _visible_journals(request, user_id).filter(pk=pk).first()
        if not j:
            return fail('Journal not found', http.HTTP_404_NOT_FOUND)
        limit = max(1, min(int(request.GET.get('limit', 100) or 100), 500))
        qs = j.entries.select_related('metric_entry')[:limit]
        return ok([entry_json(e) for e in qs])

    @auth
    def post(self, request, user_id, pk):
        j = _visible_journals(request, user_id).filter(pk=pk).first()
        if not j:
            return fail('Journal not found', http.HTTP_404_NOT_FOUND)
        text = str(request.data.get('text', '')).strip()
        if not text:
            return fail('text is required')
        at = timezone.now()
        e = JournalEntry.objects.create(journal=j, date=mx.logical_date_of(user_id, at), at=at, text=text)
        return Response({'status': 'success', 'data': entry_json(e)}, status=http.HTTP_201_CREATED)


class JournalEntriesByDateView(APIView):
    """
    Entries from tracker journals (notes logged with a tracker) for a date or a
    range, for the Journal pane. The default journal is the pane's own editor,
    so it is left out here.
    """

    @auth
    def get(self, request, user_id):
        start = parse_date(request.GET.get('date') or request.GET.get('from') or '')
        end = parse_date(request.GET.get('date') or request.GET.get('to') or '') or start
        if not start or end < start or (end - start).days > 62:
            return fail('date, or from/to of at most 62 days, is required')
        qs = (JournalEntry.objects.filter(journal__in=_visible_journals(request, user_id).filter(is_default=False),
                                          date__gte=start, date__lte=end)
              .select_related('journal', 'journal__metric', 'metric_entry').order_by('date', 'at'))
        out = []
        for e in qs:
            item = entry_json(e)
            item['journal_name'] = e.journal.name
            item['unit'] = e.journal.metric.unit if e.journal.metric_id else ''
            out.append(item)
        return ok(out)


class JournalEntryDetailView(APIView):
    @auth
    def put(self, request, user_id, pk):
        e = JournalEntry.objects.filter(pk=pk, journal__in=_visible_journals(request, user_id)).first()
        if not e:
            return fail('Entry not found', http.HTTP_404_NOT_FOUND)
        text = str(request.data.get('text', '')).strip()
        if not text:
            return fail('text is required')
        e.text = text
        e.save(update_fields=['text'])
        return ok(entry_json(e))

    @auth
    def delete(self, request, user_id, pk):
        e = JournalEntry.objects.filter(pk=pk, journal__in=_visible_journals(request, user_id)).first()
        if not e:
            return fail('Entry not found', http.HTTP_404_NOT_FOUND)
        e.delete()
        return ok(message='Entry deleted')


# ── Privacy mode ───────────────────────────────────────────

class PrivateStatusView(APIView):
    @auth
    def get(self, request, user_id):
        detail = get_detail(user_id)
        return ok({'has_pin': bool(detail.private_pin_hash), 'unlocked': privacy.is_unlocked(request),
                   'unlock_minutes': detail.private_unlock_minutes})


class PrivatePinView(APIView):
    """Set or change the PIN (4-6 digits). Changing needs the current PIN."""

    @auth
    def post(self, request, user_id):
        detail = get_detail(user_id)
        pin = request.data.get('pin')
        if not privacy.valid_pin(pin):
            return fail('PIN must be 4 to 6 digits')
        if detail.private_pin_hash:
            ok_, err, wait = privacy.try_unlock(request, detail, request.data.get('current_pin'))
            if not ok_:
                return fail('Current PIN is wrong' if err == 'wrong_pin' else err,
                            http.HTTP_403_FORBIDDEN, retry_after=wait)
        privacy.set_pin(detail, pin)
        minutes = request.data.get('unlock_minutes')
        if str(minutes).isdigit() and 1 <= int(minutes) <= 120:
            detail.private_unlock_minutes = int(minutes)
            detail.save(update_fields=['private_unlock_minutes'])
        return ok({'has_pin': True})


class PrivateUnlockView(APIView):
    @auth
    def post(self, request, user_id):
        detail = get_detail(user_id)
        ok_, err, wait = privacy.try_unlock(request, detail, request.data.get('pin'))
        if not ok_:
            code = http.HTTP_429_TOO_MANY_REQUESTS if err == 'locked_out' else http.HTTP_403_FORBIDDEN
            return fail(err, code, retry_after=wait)
        return ok({'unlocked': True, 'unlock_minutes': detail.private_unlock_minutes})


class PrivateLockView(APIView):
    @auth
    def post(self, request, user_id):
        privacy.lock(request)
        return ok({'unlocked': False})


class PrivateResetRequestView(APIView):
    @auth
    def post(self, request, user_id):
        user = User.objects.get(pk=user_id)
        sent = privacy.send_reset_code(user)
        return ok({'sent': sent}) if sent else fail('No email address on this account')


class PrivateResetConfirmView(APIView):
    @auth
    def post(self, request, user_id):
        pin = request.data.get('pin')
        if not privacy.valid_pin(pin):
            return fail('PIN must be 4 to 6 digits')
        if not privacy.check_reset_code(user_id, request.data.get('code', '')):
            return fail('Invalid or expired code', http.HTTP_403_FORBIDDEN)
        privacy.set_pin(get_detail(user_id), pin)
        privacy.lock(request)
        return ok({'has_pin': True})


# ── New-user setup ─────────────────────────────────────────

SERIOUSNESS = {'trying': 'activity', 'steady': 'activity', 'all_in': 'routine'}


def _hhmm(v, default):
    try:
        return datetime.strptime(str(v)[:5], '%H:%M').time()
    except (TypeError, ValueError):
        return default


class OnboardingSetupView(APIView):
    """
    The setup questions: how serious, habits to start, things to track, and the
    shape of a usual day. Creates them in one go and marks the user onboarded.
    """

    @auth
    @transaction.atomic
    def post(self, request, user_id):
        from datetime import time as t
        from board.models import RoutineEntry
        data = request.data
        detail = get_detail(user_id)
        detail.streak_rule = SERIOUSNESS.get(data.get('seriousness'), 'activity')

        habits = []
        for h in (data.get('habits') or [])[:12]:
            name = str(h.get('habit', '')).strip()[:120]
            if not name:
                continue
            habits.append(Habit.objects.create(
                user_id=user_id, habit=name, detail=str(h.get('detail', ''))[:200] or 'every day',
                identity=str(h.get('identity', ''))[:120] or 'someone who shows up',
                notify_at=_hhmm(h.get('notify_at'), None), frequency=[],
            ))

        for m in (data.get('trackers') or [])[:12]:
            metric = Metric(user_id=user_id)
            try:
                apply_metric_payload(metric, m)
                if metric.name:
                    if metric.kind == MetricKind.COUNTER and not metric.quick_steps:
                        metric.quick_steps = [1]
                    metric.save()
            except (ValueError, ArithmeticError):
                continue

        day = data.get('routine') or {}
        wake, sleep = _hhmm(day.get('wake'), t(6, 0)), _hhmm(day.get('sleep'), t(22, 30))
        work_from, work_to = _hhmm(day.get('work_from'), None), _hhmm(day.get('work_to'), None)
        weekend = [d for d in (day.get('weekend_days') or [5, 6]) if isinstance(d, int) and 0 <= d <= 6]
        detail.weekend_days = sorted(set(weekend))
        detail.sleep_time = sleep
        if not RoutineEntry.objects.filter(user_id=user_id).exists():
            def add(rt, at, title, tier, minutes=None):
                RoutineEntry.objects.get_or_create(user_id=user_id, routine_type=rt, time=at, title=title,
                                                   defaults={'tier': tier, 'duration_min': minutes})
            for rt in ('workday', 'holiday'):
                add(rt, wake, 'Wake up', Tier.ESSENTIAL, 15)
                add(rt, sleep, 'Sleep', Tier.ESSENTIAL)
            if work_from and work_to and work_to > work_from:
                minutes = (datetime.combine(date.today(), work_to) - datetime.combine(date.today(), work_from)).seconds // 60
                add('workday', work_from, 'Work', Tier.ANCHOR, minutes)
        detail.is_onboarded = True
        detail.save()
        if detail.journal_habit_id is None:
            j = next((h for h in habits if 'journal' in h.habit.lower()), None)
            if j:
                detail.journal_habit = j
                detail.save(update_fields=['journal_habit'])
        return ok({'habits': len(habits)})

"""Fitness tab API: overview for a day, month calendar, exercise detail."""
import calendar
from datetime import date as Date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from django.conf import settings
from django.templatetags.static import static
from rest_framework import status as http
from rest_framework.views import APIView

from board import metrics as mx
from board.day_views import auth, fail, fitness_steps_payload, hidden_ids, ok, parse_date
from board.days import logical_today
from board.models import HabitKind, HabitLog, Metric
from fitness.models import DayKind, Exercise, FitnessProfile, FitnessTick, SessionStatus, WorkoutSession
from fitness.program import (
    active_program, expand, fitness_habits, program_day, program_end, session_exercises, week_of,
)


def asset_url(rel):
    """Static URL for an asset under static/fitness/, or None when the file is not there."""
    if not rel:
        return None
    if not (Path(settings.BASE_DIR) / 'static' / 'fitness' / rel).exists():
        return None
    return static(f'fitness/{rel}')


def exercise_json(ex, full=False):
    anim = ex.animation or {}
    data = {
        'id': ex.id, 'name': ex.name, 'pattern': ex.pattern, 'measure': ex.measure,
        'default_reps': ex.default_reps, 'default_seconds': ex.default_seconds,
        'unilateral': ex.unilateral, 'level': ex.level, 'intensity': ex.intensity,
        'primary_muscles': ex.primary_muscles, 'secondary_muscles': ex.secondary_muscles,
        'still': asset_url(anim.get('still')), 'retired': ex.retired,
    }
    if full:
        data.update({
            'aliases': ex.aliases, 'equipment': ex.equipment, 'settings': ex.settings,
            'sec_per_rep': ex.sec_per_rep, 'met': ex.met, 'contraindications': ex.contraindications,
            'regression': ex.regression_id, 'progression': ex.progression_id,
            'steps': ex.steps, 'avoid': ex.avoid, 'breathing': ex.breathing,
            'video_url': f'https://www.youtube.com/results?search_query={quote_plus(ex.video_query)}' if ex.video_query else None,
            'animation': {**anim, 'clip_url': asset_url(anim.get('clip')),
                          'side': anim.get('side') or ('right' if ex.unilateral else 'both')},
            'mannequin_url': asset_url('mannequin.glb'),
        })
    return data


def day_summary(habit, d):
    """{kind, name} for an Activity habit on a date (no writes)."""
    program = active_program(habit)
    if not program:
        return {'kind': None, 'name': ''}
    _, day = program_day(program, d)
    if day is None:
        return {'kind': None, 'name': ''}
    return {'kind': day.kind, 'name': day.name or day.get_kind_display()}


def session_payload(habit, d):
    program = active_program(habit)
    if not program:
        return None
    phase, day = program_day(program, d)
    if not day or day.kind != DayKind.SESSION:
        return None
    exs = session_exercises(day)
    lib = Exercise.objects.in_bulk([e for e, _, _ in exs] + [
        i.get('exercise') for b in day.blocks for i in b.get('items', []) if i.get('exercise')])
    blocks = []
    for b in day.blocks:
        items = []
        for it in b.get('items', []):
            ex = lib.get(it.get('exercise'))
            items.append({**it, 'name': ex.name if ex else it.get('exercise'),
                          'still': asset_url((ex.animation or {}).get('still')) if ex else None,
                          'dose': ex.dose_label(b.get('rounds', 1), it.get('reps'), it.get('seconds')) if ex else ''})
        blocks.append({**b, 'items': items})
    return {'name': day.name, 'phase': phase.name, 'blocks': blocks, 'exercise_count': len(exs)}


def tracker_json(m, d):
    target = mx.effective_target(m, m.user_id, d)
    return {'id': m.id, 'key': m.fitness_key, 'name': m.name, 'unit': m.unit, 'kind': m.kind,
            'today': float(mx.day_value(m, d)), 'target': float(target) if target is not None else None,
            'quick_steps': [float(x) for x in m.quick_steps], 'is_private': m.is_private}


class OverviewView(APIView):
    @auth
    def get(self, request, user_id):
        today = logical_today(user_id)
        d = parse_date(request.GET.get('date')) or today
        hidden_habits, hidden_metrics = hidden_ids(request, user_id)
        profile = FitnessProfile.objects.filter(user_id=user_id).first()
        out = {'date': d.isoformat(), 'today': today.isoformat(), 'onboarded': bool(profile),
               'profile': {'targets': profile.targets, 'why': profile.why, 'explanation': profile.explanation,
                           'track_calories': profile.track_calories, 'times': profile.times,
                           'answered': bool(profile.answers)} if profile else None,
               'program': None, 'activity': None, 'health': None, 'trackers': [], 'preview': []}
        for habit in fitness_habits(user_id):
            if habit.id in hidden_habits:
                continue
            block = {'habit_id': habit.id, 'name': habit.habit, 'streak': habit.current_streak,
                     **fitness_steps_payload(habit, d)}
            if habit.kind == HabitKind.ACTIVITY:
                block['day'] = day_summary(habit, d)
                block['session'] = session_payload(habit, d)
                if block['session']:
                    from fitness.workouts import expire_stale, program_steps
                    expire_stale(user_id)
                    program = active_program(habit)
                    _, day = program_day(program, d)
                    block['session']['minutes'] = max(1, round(sum(x['est_seconds'] for x in program_steps(program, day)) / 60))
                    last = WorkoutSession.objects.filter(user_id=user_id, date=d).exclude(
                        status=SessionStatus.ABANDONED).order_by('-started_at').first()
                    block['workout'] = {'id': last.id, 'status': last.status, 'xp': last.xp} if last else None
                out['activity'] = block
                program = active_program(habit)
                if program:
                    phase, _ = program_day(program, d)
                    end = program_end(program)
                    out['program'] = {'id': program.id, 'name': program.name,
                                      'start_date': program.start_date.isoformat(),
                                      'end_date': end.isoformat() if end else None,
                                      'week': week_of(program, d), 'phase': phase.name if phase else None}
                out['preview'] = [{'date': (today + timedelta(days=i)).isoformat(),
                                   **day_summary(habit, today + timedelta(days=i))} for i in range(1, 7)]
            else:
                out['health'] = block
        out['trackers'] = [tracker_json(m, d) for m in
                           Metric.objects.filter(user_id=user_id, domain='fitness').exclude(id__in=hidden_metrics)]
        return ok(out)


class CalendarView(APIView):
    """Month calendar of the Activity program: {date, kind, name, done} per day."""

    @auth
    def get(self, request, user_id):
        month = request.GET.get('month') or logical_today(user_id).strftime('%Y-%m')
        try:
            y, m = (int(x) for x in month.split('-'))
            first = Date(y, m, 1)
        except ValueError:
            return fail('month must be YYYY-MM')
        habit = fitness_habits(user_id).filter(kind=HabitKind.ACTIVITY).first()
        if not habit:
            return ok({'month': month, 'days': []})
        last = Date(y, m, calendar.monthrange(y, m)[1])
        done = set(HabitLog.objects.filter(habit=habit, date__gte=first, date__lte=last, is_done=True)
                   .values_list('date', flat=True))
        days = []
        d = first
        while d <= last:
            days.append({'date': d.isoformat(), **day_summary(habit, d), 'done': d in done})
            d += timedelta(days=1)
        return ok({'month': month, 'days': days})


class DayView(APIView):
    """One day's session and subtasks (calendar tap); future dates are a preview."""

    @auth
    def get(self, request, user_id, date):
        d = parse_date(date)
        if not d:
            return fail('Invalid date')
        habit = fitness_habits(user_id).filter(kind=HabitKind.ACTIVITY).first()
        if not habit:
            return fail('No fitness plan yet', http.HTTP_404_NOT_FOUND)
        return ok({'date': d.isoformat(), 'day': day_summary(habit, d), 'session': session_payload(habit, d),
                   'steps': [{'key': i.key, 'name': i.name, 'target': i.target} for i in expand(habit, d)]})


class ExerciseView(APIView):
    @auth
    def get(self, request, user_id, pk):
        ex = Exercise.objects.filter(pk=pk).first()
        if not ex:
            return fail('Exercise not found', http.HTTP_404_NOT_FOUND)
        return ok(exercise_json(ex, full=True))


class ExerciseListView(APIView):
    @auth
    def get(self, request, user_id):
        qs = Exercise.objects.filter(retired=False)
        if request.GET.get('pattern'):
            qs = qs.filter(pattern=request.GET['pattern'])
        return ok([exercise_json(e) for e in qs])


class TickView(APIView):
    """Tick a timeline-only fitness item (the pre-workout snack)."""

    @auth
    def post(self, request, user_id):
        key = request.data.get('key')
        if key not in ('snack',):
            return fail('Unknown item')
        d = parse_date(request.data.get('date')) or logical_today(user_id)
        if request.data.get('done', True):
            FitnessTick.objects.get_or_create(user_id=user_id, date=d, key=key)
        else:
            FitnessTick.objects.filter(user_id=user_id, date=d, key=key).delete()
        return ok(message='Saved')


class OnboardingView(APIView):
    """GET: the latest answers (Edit my answers). POST: preview, or install with confirm=true."""

    @auth
    def get(self, request, user_id):
        from fitness.onboarding import latest_answers
        return ok({'answers': latest_answers(user_id)})

    @auth
    def post(self, request, user_id):
        from fitness import onboarding
        from fitness.rules import AnswerError
        data = dict(request.data)
        confirm = bool(data.pop('confirm', False))
        try:
            out = onboarding.confirm(user_id, data) if confirm else onboarding.plan(data)[-1]
        except AnswerError as e:
            return fail(str(e))
        return ok(out)

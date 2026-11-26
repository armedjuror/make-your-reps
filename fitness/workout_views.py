"""Workout player API: start/resume, state, sets, finish, skip, log without the player, 'something hurts'."""
from django.utils import timezone
from rest_framework import status as http
from rest_framework.views import APIView

from board.day_views import auth, fail, ok, parse_date
from board.days import logical_today
from fitness import workouts as wk
from fitness.models import FitnessProfile, SessionStatus, WorkoutSession
from fitness.views import exercise_json

JOINTS = ('knee', 'lower_back', 'shoulder', 'wrist', 'neck', 'hip', 'ankle')


def player_payload(session, resumed=False):
    lib = wk.library_for(session.steps)
    ex_ids = [i for i in lib]
    profile = FitnessProfile.objects.filter(user_id=session.user_id).first()
    regressions = {e.id: {'id': e.regression_id, 'name': e.regression.name}
                   for e in lib.values() if e.regression_id}
    work = [s for s in session.steps if s['kind'] in ('exercise_set', 'exercise_timed') and not s.get('warmup')]
    return {
        'session': session_json(session),
        'resumed': resumed,
        'steps': session.steps,
        'meta': {
            'mode': 'workout', 'name': session.name, 'why': profile.why if profile else '',
            'minutes': max(1, round(session.est_seconds / 60)),
            'exercise_count': len({s['exercise_id'] for s in work}),
            'last': wk.last_performance(session.user_id, ex_ids, exclude_session=session),
            'suggestions': wk.suggestions_for(session.user_id, ex_ids),
            'regressions': regressions,
            'exercises': {i: exercise_json(e, full=True) for i, e in lib.items()},
        },
        'sets': [{'exercise': s.exercise_id, 'set_index': s.set_index, 'side': s.side, 'reps_done': s.reps_done,
                  'seconds_done': s.seconds_done, 'load': s.load, 'rir': s.rir, 'skipped': s.skipped}
                 for s in session.sets.all()],
    }


def session_json(s):
    return {'id': s.id, 'date': s.date.isoformat(), 'name': s.name, 'status': s.status, 'source': s.source,
            'started_at': s.started_at.isoformat(), 'ended_at': s.ended_at.isoformat() if s.ended_at else None,
            'paused': bool(s.paused_at), 'paused_at': s.paused_at.isoformat() if s.paused_at else None,
            'now': timezone.now().isoformat(), 'state': s.state, 'est_seconds': s.est_seconds,
            'est_kcal': s.est_kcal, 'xp': s.xp, 'summary': s.summary}


def _own(user_id, pk):
    return WorkoutSession.objects.filter(pk=pk, user_id=user_id).first()


class WorkoutStartView(APIView):
    @auth
    def post(self, request, user_id):
        try:
            session, resumed = wk.start_session(user_id)
        except wk.WorkoutError as e:
            return fail(str(e))
        return ok(player_payload(session, resumed))


class WorkoutActiveView(APIView):
    @auth
    def get(self, request, user_id):
        s = wk.active_session(user_id)
        return ok(player_payload(s, True) if s else None)


class WorkoutStateView(APIView):
    @auth
    def put(self, request, user_id, pk):
        s = _own(user_id, pk)
        if not s:
            return fail('Session not found', http.HTTP_404_NOT_FOUND)
        d = request.data
        try:
            wk.save_state(s, index=d.get('index'), paused=d.get('paused'),
                          steps=d.get('steps') if isinstance(d.get('steps'), list) else None, extra=d)
        except wk.WorkoutError as e:
            return fail(str(e))
        return ok(session_json(s))


class WorkoutSetView(APIView):
    @auth
    def post(self, request, user_id, pk):
        s = _own(user_id, pk)
        if not s:
            return fail('Session not found', http.HTTP_404_NOT_FOUND)
        try:
            log, pr = wk.log_set(s, request.data)
        except wk.WorkoutError as e:
            return fail(str(e))
        return ok({'set_index': log.set_index, 'exercise': log.exercise_id, 'side': log.side, 'pr': pr})


class WorkoutFinishView(APIView):
    @auth
    def post(self, request, user_id, pk):
        s = _own(user_id, pk)
        if not s:
            return fail('Session not found', http.HTTP_404_NOT_FOUND)
        mode = request.data.get('mode', 'finish')
        if mode not in ('finish', 'end', 'lighter'):
            return fail('mode must be finish, lighter or end')
        try:
            wk.finish_session(s, mode=mode)
        except wk.WorkoutError as e:
            return fail(str(e))
        return ok(session_json(s))


class WorkoutSkipView(APIView):
    @auth
    def post(self, request, user_id):
        try:
            wk.skip_today(user_id)
        except wk.WorkoutError as e:
            return fail(str(e))
        return ok(message='Skipped')


class WorkoutPlanView(APIView):
    """The planned sets for a day, for the log-without-player form."""

    @auth
    def get(self, request, user_id):
        d = parse_date(request.GET.get('date')) or logical_today(user_id)
        try:
            _, _, day, steps = wk.planned_session(user_id, d)
        except wk.WorkoutError as e:
            return fail(str(e))
        lib = wk.library_for(steps)
        rows = [{'exercise': s['exercise_id'], 'name': lib[s['exercise_id']].name if s['exercise_id'] in lib else s['exercise_id'],
                 'set_index': s['set_index'], 'set_total': s['set_total'], 'side': s.get('side') or '',
                 'target': s['target']}
                for s in steps if s['kind'] in ('exercise_set', 'exercise_timed') and not s.get('warmup')]
        last = wk.last_performance(user_id, [r['exercise'] for r in rows])
        logged = WorkoutSession.objects.filter(user_id=user_id, date=d, status=SessionStatus.COMPLETED).exists()
        return ok({'date': d.isoformat(), 'name': day.name, 'minutes': max(1, round(sum(s['est_seconds'] for s in steps) / 60)),
                   'rows': rows, 'last': last, 'logged': logged})


class WorkoutManualLogView(APIView):
    @auth
    def post(self, request, user_id):
        d = parse_date(request.data.get('date')) or logical_today(user_id)
        try:
            s = wk.manual_log(user_id, d, as_planned=bool(request.data.get('as_planned', True)),
                              sets=request.data.get('sets') or [], start_time=request.data.get('start_time'),
                              duration_min=request.data.get('duration_min'))
        except wk.WorkoutError as e:
            return fail(str(e))
        return ok(session_json(s))


class PainView(APIView):
    """'Something hurts': pick the joint; affected moves switch to a regression or drop out."""

    @auth
    def post(self, request, user_id):
        joint = request.data.get('joint')
        if joint not in JOINTS:
            return fail(f'joint must be one of {", ".join(JOINTS)}')
        changes = wk.contraindicate(user_id, joint)
        s = wk.active_session(user_id)
        if s:
            # Rebuild what's left of the open session with the new swaps
            from fitness.program import program_day
            _, day = program_day(s.program, s.date) if s.program else (None, None)
            if day:
                new = wk.program_steps(s.program, day)
                done_ids = {x.get('exercise_id') for x in s.steps[:s.state.get('index', 0) + 1]}
                ahead = [x for x in new if x.get('exercise_id') not in done_ids or x['kind'] == 'rest']
                wk.save_state(s, steps=s.steps[:s.state.get('index', 0) + 1] + ahead)
        return ok({'changes': changes, 'session': player_payload(s, True) if s else None})

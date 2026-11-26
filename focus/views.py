from django.utils import timezone
from rest_framework import status as http
from rest_framework.views import APIView

from board.day_views import auth, fail, ok
from focus import service as fs
from focus.models import FocusSession


def focus_json(s):
    return {'id': s.id, 'title': s.title, 'date': s.date.isoformat(), 'plan': s.plan, 'status': s.status,
            'started_at': s.started_at.isoformat(), 'ended_at': s.ended_at.isoformat() if s.ended_at else None,
            'paused': bool(s.paused_at), 'paused_at': s.paused_at.isoformat() if s.paused_at else None,
            'now': timezone.now().isoformat(), 'state': s.state, 'completed_cycles': s.completed_cycles,
            'interruptions': s.interruptions, 'focus_minutes': s.focus_minutes, 'xp': s.xp,
            'parked': len(s.parked or []), 'task': s.task_id, 'habit': s.habit_id,
            'routine_entry': s.routine_entry_id}


def payload(s, resumed=False):
    return {'session': focus_json(s), 'steps': s.steps, 'resumed': resumed,
            'meta': {'mode': 'focus', 'name': s.title or 'Focus', 'plan': s.plan,
                     'minutes': round(sum(x['est_seconds'] for x in s.steps) / 60)}}


def _own(user_id, pk):
    return FocusSession.objects.filter(pk=pk, user_id=user_id).first()


class FocusStartView(APIView):
    @auth
    def get(self, request, user_id):
        """The default plan, for the editable pre-start screen."""
        return ok(fs.default_plan(user_id))

    @auth
    def post(self, request, user_id):
        try:
            s, resumed = fs.start(user_id, request.data)
        except fs.FocusError as e:
            return fail(str(e))
        return ok(payload(s, resumed))


class FocusActiveView(APIView):
    @auth
    def get(self, request, user_id):
        s = fs.active(user_id)
        return ok(payload(s, True) if s else None)


class FocusActionView(APIView):
    """PUT state; POST park / distracted / finish."""

    @auth
    def put(self, request, user_id, pk):
        s = _own(user_id, pk)
        if not s:
            return fail('Session not found', http.HTTP_404_NOT_FOUND)
        try:
            fs.save_state(s, index=request.data.get('index'), paused=request.data.get('paused'))
        except fs.FocusError as e:
            return fail(str(e))
        return ok(focus_json(s))

    @auth
    def post(self, request, user_id, pk, action):
        s = _own(user_id, pk)
        if not s:
            return fail('Session not found', http.HTTP_404_NOT_FOUND)
        try:
            if action == 'park':
                t = fs.park(s, request.data.get('text'))
                return ok({'task': t.id, 'parked': len(s.parked)})
            if action == 'distracted':
                fs.distracted(s)
            elif action == 'finish':
                fs.finish(s, tick=bool(request.data.get('tick')))
            elif action == 'tick':
                fs.tick_linked(s)
            else:
                return fail('Unknown action', http.HTTP_404_NOT_FOUND)
        except fs.FocusError as e:
            return fail(str(e))
        return ok(focus_json(s))

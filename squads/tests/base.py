from datetime import date, datetime, time, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from board.models import Friend, HabitLog, UserDetail

IST = ZoneInfo('Asia/Kolkata')
MON = date(2026, 11, 2)   # a Monday


def at(day, h, m=0):
    return datetime.combine(day, time(h, m), tzinfo=IST)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', HOSTED=False,
                   VAPID_PRIVATE_KEY='')
class SquadTestCase(TestCase):
    start = at(MON - timedelta(days=7), 9)

    def setUp(self):
        self.now = self.start
        patcher = mock.patch('django.utils.timezone.now', side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.arjun = self.user('arjun', 'Arjun')
        self.meera = self.user('meera', 'Meera')
        self.kabir = self.user('kabir', 'Kabir')

    def user(self, username, first):
        u = User.objects.create_user(username, f'{username}@example.com', 'pw', first_name=first)
        UserDetail.objects.create(user=u, day_start=time(0, 0))
        return u

    def travel(self, when):
        self.now = when

    def befriend(self, a, b):
        Friend.objects.get_or_create(user=a, friend=b)
        Friend.objects.get_or_create(user=b, friend=a)

    def squad(self, *members, core=('Solve 2 problems',), optional=()):
        from squads import core as core_mod, items
        b = core_mod.create_squad(self.arjun, name='DSA grind', template='custom')
        for name in core:
            items.create_squad_habit(b, self.arjun.id, habit=name, is_core=True)
        for name in optional:
            items.create_squad_habit(b, self.arjun.id, habit=name, is_core=False)
        inv = core_mod.current_invite(b, self.arjun.id)
        for m in members:
            core_mod.join_with_invite(inv.token, m)
        return b

    def check_in(self, board, user, day, habit_name='Solve 2 problems', done=True):
        from board.models import Habit
        from squads.items import linked_copy
        squad_habit = Habit.objects.get(board=board, habit=habit_name)
        copy = linked_copy(squad_habit, user.id)
        log, _ = HabitLog.objects.get_or_create(habit=copy, date=day)
        log.is_done = done
        log.save()
        return log

    def evaluate(self, board, when):
        from squads.evaluator import evaluate_board
        self.travel(when)
        return evaluate_board(board, when)

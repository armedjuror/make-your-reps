"""
Board-migration gate: every list and detail endpoint returns identical data
before and after the switch to visible_items / BoardScopedMixin. This test
must pass before any squad track merges.
"""
import json
from pathlib import Path

from squads.tests import parity_fixture as fx
from squads.tests.make_parity_snapshot import ParityHarness

SNAPSHOT = Path(__file__).with_name('parity_snapshot.json')


class BoardMigrationParityTest(ParityHarness):
    def test_endpoints_match_pre_migration_snapshot(self):
        expected = json.loads(SNAPSHOT.read_text())
        ids, actual = self.capture()
        actual = json.loads(json.dumps(actual, sort_keys=True, default=str))
        self.assertEqual(sorted(expected), sorted(actual), 'endpoint list changed')
        for url in expected:
            with self.subTest(url=url):
                self.assertEqual(expected[url]['status'], actual[url]['status'])
                self.assertEqual(fx.strip_added(expected[url]['body']), fx.strip_added(actual[url]['body']))

    def test_every_item_is_on_its_creators_personal_board(self):
        from board.models import Habit, Metric, Task
        from squads.models import Board
        ids, _ = self.capture()
        for model in (Habit, Task, Metric):
            for obj in model.objects.select_related('board'):
                self.assertEqual(obj.board.type, 'personal')
                self.assertEqual(obj.board.owner_id, obj.user_id)
        self.assertEqual(Board.objects.filter(type='personal').count(), 2)

    def test_squad_items_do_not_leak_into_personal_lists(self):
        """A squad habit the user created is a definition, not a personal habit."""
        from django.contrib.auth.models import User
        from squads import core, items
        ids, before = self.capture()
        me = User.objects.get(pk=ids['me'])
        self.client.force_login(me)   # the capture's session was made under the frozen clock
        squad = core.create_squad(me, name='DSA grind', template='custom')
        items.create_squad_habit(squad, me.id, habit='Squad only habit', is_core=True)
        resp = self.client.get('/board/api/habits/').json()
        self.assertIn('data', resp, resp)
        habits = resp['data']
        names = [h['habit'] for h in habits]
        self.assertEqual(names.count('Squad only habit'), 1)          # the linked copy, once
        copy = next(h for h in habits if h['habit'] == 'Squad only habit')
        self.assertEqual(copy['squad']['name'], 'DSA grind')

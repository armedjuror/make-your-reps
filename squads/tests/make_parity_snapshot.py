"""
Regenerate parity_snapshot.json from main (before the Board migration):

    git worktree add /tmp/main-wt main
    cp squads/tests/parity_fixture.py squads/tests/make_parity_snapshot.py /tmp/main-wt/board/
    cd /tmp/main-wt && PARITY_OUT=/path/to/parity_snapshot.json \\
        python manage.py test board.make_parity_snapshot

The same harness (reset sequences, frozen clock, logged-in client) runs on
this branch in test_parity.py.
"""
import json
import os
from unittest import mock

from django.test import TransactionTestCase

try:
    from squads.tests import parity_fixture as fx
except ImportError:          # copied next to main's board app
    from board import parity_fixture as fx


class ParityHarness(TransactionTestCase):
    reset_sequences = True

    def capture(self):
        with mock.patch('django.utils.timezone.now', return_value=fx.NOW):
            ids = fx.build()
            from django.contrib.auth.models import User
            self.client.force_login(User.objects.get(pk=ids['me']))
            with mock.patch('board.calendar_views.sync_calendar_events_for_user_date', return_value=None):
                return ids, fx.snapshot(self.client, ids)


class MakeSnapshot(ParityHarness):
    def test_write_snapshot(self):
        out = os.environ.get('PARITY_OUT')
        if not out:
            self.skipTest('PARITY_OUT not set')
        _, snap = self.capture()
        with open(out, 'w') as f:
            json.dump(snap, f, indent=1, sort_keys=True, default=str)

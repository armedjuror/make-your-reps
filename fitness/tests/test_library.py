"""import_exercises: schema validation, link and asset checks, upsert, retire, dry run."""
import copy
import json
import struct
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from fitness.library import glb_names, import_items, validate
from fitness.models import Exercise

from .base import FIXTURE

ITEMS = json.loads(FIXTURE.read_text())


def make_glb(path, names):
    doc = json.dumps({'asset': {'version': '2.0'}, 'nodes': [{'name': n} for n in names]}).encode()
    doc += b' ' * (-len(doc) % 4)
    data = struct.pack('<4sII', b'glTF', 2, 20 + len(doc)) + struct.pack('<I4s', len(doc), b'JSON') + doc
    Path(path).write_bytes(data)


class LibraryTest(TestCase):
    def items(self):
        return copy.deepcopy(ITEMS)

    def test_fixture_is_valid_and_imports(self):
        report = import_items(self.items())
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(Exercise.objects.count(), 12)
        self.assertEqual(report.version, 1)

    def test_reimport_is_a_noop(self):
        import_items(self.items())
        report = import_items(self.items())
        self.assertEqual(len(report.unchanged), 12)
        self.assertEqual(report.version, 0)

    def test_schema_errors_reject_the_whole_file(self):
        items = self.items()
        items[3]['pattern'] = 'pushup'
        del items[4]['steps']
        items[5]['extra_field'] = 1
        report = import_items(items)
        self.assertFalse(report.ok)
        self.assertEqual(len(report.errors), 3)
        self.assertEqual(Exercise.objects.count(), 0)

    def test_measure_needs_its_default(self):
        items = self.items()
        items[1]['default_reps'] = None
        self.assertFalse(validate(items).ok)

    def test_unknown_link_and_duplicate_id(self):
        items = self.items()
        items[1]['progression'] = 'band_jump_squat'
        items.append(copy.deepcopy(items[2]))
        errors = ' '.join(validate(items).errors)
        self.assertIn('duplicate id', errors)
        items.pop()
        errors = ' '.join(validate(items).errors)
        self.assertIn('band_jump_squat', errors)

    def test_links_resolve_within_the_file(self):
        items = self.items()
        items[1]['regression'] = 'glute_bridge'
        import_items(items)
        self.assertEqual(Exercise.objects.get(id='band_squat').regression_id, 'glute_bridge')

    def test_missing_still_is_an_error_missing_clip_a_warning(self):
        with tempfile.TemporaryDirectory() as root:
            report = validate(self.items()[:1], root=root)
            self.assertIn('arm_circles: still stills/arm_circles.png missing', report.errors)
            (Path(root) / 'stills').mkdir()
            (Path(root) / 'stills' / 'arm_circles.png').write_bytes(b'png')
            report = validate(self.items()[:1], root=root)
            self.assertTrue(report.ok)
            self.assertTrue(any('clip' in w for w in report.warnings))

    def test_unilateral_needs_right_side(self):
        items = self.items()
        squat = next(i for i in items if i['id'] == 'split_squat')
        squat['animation']['side'] = 'both'
        self.assertFalse(validate(items).ok)

    def test_muscles_checked_against_mannequin(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'stills').mkdir()
            (Path(root) / 'stills' / 'band_squat.png').write_bytes(b'png')
            item = next(i for i in self.items() if i['id'] == 'band_squat')
            make_glb(Path(root) / 'mannequin.glb', ['quads_l', 'quads_r', 'glutes', 'abs', 'band_tube'])
            self.assertEqual(glb_names(Path(root) / 'mannequin.glb') >= {'abs'}, True)
            report = validate([item], root=root)
            self.assertEqual(report.errors, ['band_squat: muscle "adductors" has no mesh on the mannequin'])

    def test_retire_not_delete_and_revive(self):
        import_items(self.items())
        report = import_items(self.items()[:-1])
        self.assertEqual(report.retired, ['glute_bridge'])
        self.assertTrue(Exercise.objects.get(id='glute_bridge').retired)
        self.assertEqual(Exercise.objects.count(), 12)
        report = import_items(self.items())
        self.assertEqual(report.revived, ['glute_bridge'])
        self.assertFalse(Exercise.objects.get(id='glute_bridge').retired)

    def test_keep_missing(self):
        import_items(self.items())
        report = import_items(self.items()[:3], retire_missing=False)
        self.assertEqual(report.retired, [])

    def test_changed_fields_bump_version(self):
        import_items(self.items())
        items = self.items()
        items[1]['level'] = 2
        report = import_items(items)
        self.assertEqual(report.changed, {'band_squat': ['level']})
        self.assertEqual(Exercise.objects.get(id='band_squat').library_version, 2)
        self.assertEqual(Exercise.objects.get(id='band_row').library_version, 1)

    def test_dry_run_command_writes_nothing(self):
        out = StringIO()
        call_command('import_exercises', str(FIXTURE), '--dry-run', stdout=out)
        self.assertIn('+ band_squat', out.getvalue())
        self.assertEqual(Exercise.objects.count(), 0)

    def test_command_fails_on_errors(self):
        items = self.items()
        items[0]['level'] = 9
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(items, f)
        with self.assertRaises(CommandError):
            call_command('import_exercises', f.name, stdout=StringIO())

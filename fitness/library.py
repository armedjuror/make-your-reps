"""
Exercise library import: validate exercises.json against the frozen contract,
check its assets, then upsert by id. Never deletes; ids missing from the file
are marked ``retired`` so old logs and programs stay valid.
"""
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Max

SCHEMA_PATH = Path(__file__).resolve().parent / 'schemas' / 'exercise.schema.json'
DATA_FIELDS = [
    'name', 'aliases', 'pattern', 'primary_muscles', 'secondary_muscles', 'equipment', 'settings',
    'level', 'intensity', 'measure', 'default_reps', 'default_seconds', 'sec_per_rep', 'unilateral',
    'met', 'contraindications', 'steps', 'avoid', 'breathing', 'video_query', 'animation',
]
LINK_FIELDS = ['regression', 'progression']
# Library muscle names that the mannequin draws with a differently named mesh
MESH_ALIASES = {'core': 'abs'}


def asset_root():
    return Path(settings.BASE_DIR) / 'static' / 'fitness'


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    created: list = field(default_factory=list)
    changed: dict = field(default_factory=dict)     # id -> [field, ...]
    unchanged: list = field(default_factory=list)
    retired: list = field(default_factory=list)
    revived: list = field(default_factory=list)
    version: int = 0

    @property
    def ok(self):
        return not self.errors

    def lines(self):
        out = [f'library_version -> {self.version}' if self.version else 'library_version unchanged']
        out += [f'+ {i}' for i in self.created]
        out += [f'~ {i}: {", ".join(f)}' for i, f in self.changed.items()]
        out += [f'^ {i} (un-retired)' for i in self.revived]
        out += [f'- {i} (retired)' for i in self.retired]
        out.append(f'{len(self.unchanged)} unchanged')
        out += [f'WARNING {w}' for w in self.warnings]
        out += [f'ERROR {e}' for e in self.errors]
        return out


# ── Validation ─────────────────────────────────────────────

def load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def glb_names(path):
    """Node, mesh and material names inside a .glb (reads the JSON chunk only)."""
    data = Path(path).read_bytes()
    magic, _version, _length = struct.unpack_from('<4sII', data, 0)
    if magic != b'glTF':
        raise ValueError(f'{path} is not a GLB file')
    chunk_len, chunk_type = struct.unpack_from('<I4s', data, 12)
    if chunk_type != b'JSON':
        raise ValueError(f'{path} has no JSON chunk')
    doc = json.loads(data[20:20 + chunk_len])
    return {x.get('name') for key in ('nodes', 'meshes', 'materials') for x in doc.get(key, []) if x.get('name')}


def mesh_has_muscle(names, muscle):
    m = MESH_ALIASES.get(muscle, muscle)
    return any(n in names for n in (m, f'{m}_l', f'{m}_r', f'{m}_L', f'{m}_R', f'muscle_{m}'))


def validate(items, root=None, existing_ids=()):
    """Return a Report with errors/warnings for ``items`` (the parsed JSON array)."""
    import jsonschema
    report = Report()
    root = Path(root) if root else asset_root()
    if not isinstance(items, list):
        report.errors.append('exercises.json must be a JSON array')
        return report

    validator = jsonschema.Draft202012Validator(load_schema())
    ids, seen = [], set()
    for n, item in enumerate(items):
        label = item.get('id', f'#{n}') if isinstance(item, dict) else f'#{n}'
        for err in sorted(validator.iter_errors(item), key=lambda e: list(e.path)):
            where = '.'.join(str(p) for p in err.path) or '(object)'
            report.errors.append(f'{label}: {where}: {err.message}')
        if isinstance(item, dict) and isinstance(item.get('id'), str):
            if item['id'] in seen:
                report.errors.append(f'{item["id"]}: duplicate id')
            seen.add(item['id'])
            ids.append(item['id'])
    if report.errors:
        return report

    known = seen | set(existing_ids)
    by_id = {i['id']: i for i in items}
    for i in items:
        for f in LINK_FIELDS:
            target = i.get(f)
            if target and target not in known:
                report.errors.append(f'{i["id"]}: {f} "{target}" is not in the library')
            if target == i['id']:
                report.errors.append(f'{i["id"]}: {f} points to itself')
        if i['measure'] == 'reps' and i['default_reps'][0] > i['default_reps'][1]:
            report.errors.append(f'{i["id"]}: default_reps min is above max')
        side = i['animation'].get('side')
        if i['unilateral'] and side == 'both':
            report.errors.append(f'{i["id"]}: unilateral exercise with side "both"')

    # Assets: every exercise needs its still; a missing clip falls back to the still
    mannequin = root / 'mannequin.glb'
    names = None
    if mannequin.exists():
        try:
            names = glb_names(mannequin)
        except (ValueError, struct.error) as e:
            report.errors.append(str(e))
    else:
        report.warnings.append('static/fitness/mannequin.glb missing: muscle and prop names not checked')
    for i in by_id.values():
        anim = i['animation']
        if not (root / anim['still']).exists():
            report.errors.append(f'{i["id"]}: still {anim["still"]} missing')
        if anim['clip'] != f'clips/{i["id"]}.glb':
            report.errors.append(f'{i["id"]}: clip must be clips/{i["id"]}.glb')
        if anim['still'] != f'stills/{i["id"]}.png':
            report.errors.append(f'{i["id"]}: still must be stills/{i["id"]}.png')
        if not (root / anim['clip']).exists():
            report.warnings.append(f'{i["id"]}: clip {anim["clip"]} missing (still shown instead)')
        if names is not None:
            for m in i['primary_muscles'] + i['secondary_muscles']:
                if m != 'full_body' and not mesh_has_muscle(names, m):
                    report.errors.append(f'{i["id"]}: muscle "{m}" has no mesh on the mannequin')
            for eq in i['equipment']:
                if eq != 'none' and not any(n in names for n in (eq, f'prop_{eq}')):
                    report.warnings.append(f'{i["id"]}: no prop named "{eq}" on the mannequin')
    return report


# ── Import ─────────────────────────────────────────────────

def import_items(items, dry_run=False, retire_missing=True, root=None):
    from fitness.models import Exercise
    existing = {e.id: e for e in Exercise.objects.all()}
    report = validate(items, root=root, existing_ids=[i for i, e in existing.items() if not e.retired])
    if not report.ok:
        return report

    file_ids = {i['id'] for i in items}
    for item in items:
        ex = existing.get(item['id'])
        if ex is None:
            report.created.append(item['id'])
            continue
        diff = [f for f in DATA_FIELDS if getattr(ex, f) != item[f]]
        diff += [f for f in LINK_FIELDS if getattr(ex, f'{f}_id') != item[f]]
        if ex.retired:
            report.revived.append(item['id'])
        if diff:
            report.changed[item['id']] = diff
        elif not ex.retired:
            report.unchanged.append(item['id'])
    if retire_missing:
        report.retired = sorted(i for i, e in existing.items() if i not in file_ids and not e.retired)

    if not (report.created or report.changed or report.retired or report.revived):
        return report
    report.version = (Exercise.objects.aggregate(v=Max('library_version'))['v'] or 0) + 1
    if dry_run:
        return report

    with transaction.atomic():
        touched = set(report.created) | set(report.changed) | set(report.revived)
        for item in items:
            if item['id'] not in touched:
                continue
            defaults = {f: item[f] for f in DATA_FIELDS}
            defaults.update(retired=False, library_version=report.version)
            Exercise.objects.update_or_create(id=item['id'], defaults=defaults)
        # Links in a second pass, so an exercise can point at one created in this file
        for item in items:
            if item['id'] in touched:
                Exercise.objects.filter(id=item['id']).update(
                    regression_id=item['regression'], progression_id=item['progression'])
        if report.retired:
            Exercise.objects.filter(id__in=report.retired).update(retired=True, library_version=report.version)
    return report


def import_file(path, **kw):
    return import_items(json.loads(Path(path).read_text()), **kw)

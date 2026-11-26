"""
The 12 launch templates: {full body, upper/lower, push/pull/legs} x
{home-bands, home-bodyweight, gym} plus 3 gentle variants. Templates list
slots, not exercises; fitness.builder fills them from the library.

Slot = "pattern" or "pattern:muscle". Blocks:
  warmup / cooldown {"auto": true}  -> 2-3 timed warm-up / mobility moves, stretches for the day's muscles
  pair      heavy item + light item for a different muscle (A1 -> rest 30 s -> A2 -> rest 60-90 s)
  circuit   accessory: light isolation and core, rest 30 s between, 60 s between rounds
Every template runs 4 calendar weeks: 2 x 10-12 -> 2 x 12-15 -> 3 x 10-12 -> 3 x 12-15.
"""
WARM = {'block': 'warmup', 'auto': True}
COOL = {'block': 'cooldown', 'auto': True}
DOSES = [(1, 2, [10, 12]), (2, 2, [12, 15]), (3, 3, [10, 12]), (4, 3, [12, 15])]


def pair(a, b, a_int='heavy', b_int='light', rotate=False):
    return {'block': 'pair', 'items': [{'slot': a, 'intensity': a_int, 'rotate': rotate},
                                       {'slot': b, 'intensity': b_int, 'rotate': rotate}]}


def circuit(*slots):
    return {'block': 'circuit', 'items': [{'slot': s, 'intensity': 'light', 'rotate': True} for s in slots]}


# Each session keeps push and pull sets level (weekly balance rule) and puts heavy work first.
SESSIONS = {
    'full': ('Full body', [WARM,
                           pair('squat', 'horizontal_pull:rear_delts'),
                           pair('horizontal_push', 'horizontal_pull', b_int='heavy'),
                           pair('hinge', 'vertical_push', b_int='moderate'),
                           circuit('core_anti_extension', 'isolation_upper:biceps'), COOL]),
    'upper': ('Upper body', [WARM,
                             pair('horizontal_push', 'core_anti_extension'),
                             pair('horizontal_pull', 'core_anti_rotation'),
                             pair('vertical_push', 'vertical_pull', a_int='moderate', b_int='moderate'),
                             circuit('isolation_upper:biceps', 'isolation_upper:triceps'), COOL]),
    'lower': ('Lower body', [WARM,
                             pair('squat', 'core_anti_rotation'),
                             pair('hinge', 'isolation_lower:calves'),
                             pair('lunge', 'hinge:glutes', a_int='moderate'),
                             circuit('core_anti_extension', 'core_lateral'), COOL]),
    'push': ('Push', [WARM,
                      pair('horizontal_push', 'core_anti_extension'),
                      pair('vertical_push', 'isolation_lower:calves', a_int='moderate'),
                      circuit('isolation_upper:triceps', 'isolation_upper:side_delts'), COOL]),
    'pull': ('Pull', [WARM,
                      pair('horizontal_pull', 'core_anti_rotation'),
                      pair('vertical_pull', 'isolation_upper:biceps', a_int='moderate'),
                      circuit('core_flexion', 'hinge:glutes'), COOL]),
    'legs': ('Legs', [WARM,
                      pair('squat', 'core_anti_extension'),
                      pair('hinge', 'isolation_lower:calves'),
                      circuit('lunge', 'hinge:glutes'), COOL]),
    'gentle': ('Gentle full body', [WARM,
                                    {'block': 'circuit', 'items': [{'slot': 'squat', 'intensity': 'light'},
                                                                   {'slot': 'horizontal_push', 'intensity': 'light'},
                                                                   {'slot': 'hinge:glutes', 'intensity': 'light'},
                                                                   {'slot': 'horizontal_pull', 'intensity': 'light'},
                                                                   {'slot': 'core_anti_extension', 'intensity': 'light'}]},
                                    COOL]),
    'mobility': ('Mobility', [WARM, {'block': 'circuit', 'items': [{'slot': 'mobility'}, {'slot': 'mobility', 'rotate': True},
                                                                   {'slot': 'stretch'}]}, COOL]),
}

# weekday -> session key, 'walk' or 'rest'
WEEKS = {
    'full_body': {0: 'full', 1: 'walk', 2: 'full', 3: 'walk', 4: 'full', 5: 'walk', 6: 'rest'},
    'upper_lower': {0: 'upper', 1: 'lower', 2: 'walk', 3: 'upper', 4: 'lower', 5: 'walk', 6: 'rest'},
    'ppl': {0: 'push', 1: 'pull', 2: 'legs', 3: 'push', 4: 'pull', 5: 'legs', 6: 'rest'},
    'gentle': {0: 'gentle', 1: 'walk', 2: 'walk', 3: 'gentle', 4: 'walk', 5: 'walk', 6: 'rest'},
    'walk_mobility': {0: 'mobility', 1: 'walk', 2: 'mobility', 3: 'walk', 4: 'mobility', 5: 'walk', 6: 'rest'},
}
DAYS = {'full_body': 3, 'upper_lower': 4, 'ppl': 6, 'gentle': 2, 'walk_mobility': 3}
KINDS = {
    'home-bands': dict(setting='home', equipment_required=['band_tube']),
    'home-bodyweight': dict(setting='home', equipment_required=[]),
    'gym': dict(setting='gym', equipment_required=[]),
}


def phases_for(week_plan, gentle=False):
    out = []
    for week, rounds, reps in DOSES:
        if gentle:
            rounds, reps = min(rounds, 2), [10, 12]
        days = {}
        for wd, key in WEEKS[week_plan].items():
            if key in ('walk', 'rest'):
                days[str(wd)] = {'kind': key, 'name': 'Walk day' if key == 'walk' else 'Rest day'}
                continue
            name, blocks = SESSIONS[key]
            filled = []
            for b in blocks:
                b = {**b, 'items': [dict(i) for i in b.get('items', [])]}
                if b['block'] in ('pair', 'circuit'):
                    b['rounds'] = rounds
                    for i in b['items']:
                        i['reps'] = reps
                filled.append(b)
            days[str(wd)] = {'kind': 'session', 'name': name, 'blocks': filled}
        out.append({'name': f'Week {week} · {rounds} × {reps[0]}–{reps[1]}', 'weeks': [week, week], 'days': days})
    return out


def launch_templates():
    """[(slug, defaults)] for the 12 launch templates."""
    out = []
    names = {'full_body': 'Full body', 'upper_lower': 'Upper / lower', 'ppl': 'Push / pull / legs'}
    kind_names = {'home-bands': 'home, bands', 'home-bodyweight': 'home, bodyweight', 'gym': 'gym'}
    for fam in ('full_body', 'upper_lower', 'ppl'):
        for kind, extra in KINDS.items():
            slug = f'{fam.replace("_", "-")}-{kind}'
            out.append((slug, dict(name=f'{names[fam]} ({kind_names[kind]})', goal='general', level=1,
                                   days_per_week=DAYS[fam], session_minutes=45 if fam == 'ppl' else 30,
                                   gentle=False, phases=phases_for(fam), **extra)))
    out.append(('gentle-home-bodyweight', dict(name='Gentle start (home)', setting='home', equipment_required=[],
                                               goal='general', level=1, days_per_week=2, session_minutes=25, gentle=True,
                                               phases=phases_for('gentle', gentle=True))))
    out.append(('gentle-gym', dict(name='Gentle start (gym)', setting='gym', equipment_required=[], goal='general',
                                   level=1, days_per_week=2, session_minutes=25, gentle=True,
                                   phases=phases_for('gentle', gentle=True))))
    out.append(('walk-mobility', dict(name='Walking and mobility', setting='home', equipment_required=[],
                                      goal='general', level=1, days_per_week=3, session_minutes=15, gentle=True,
                                      phases=phases_for('walk_mobility', gentle=True))))
    return out


def ensure_templates():
    """Create or update the launch templates (idempotent)."""
    from fitness.models import ProgramTemplate
    for slug, defaults in launch_templates():
        ProgramTemplate.objects.update_or_create(slug=slug, defaults={**defaults, 'is_personal': False})
    return ProgramTemplate.objects.filter(is_personal=False)

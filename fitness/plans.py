"""
Hand-entered program templates. ``ajwad_bands_month`` is Ajwad's one-month
resistance-band plan (Dec 2026), entered by hand before the builder exists.

Weeks 1-2: full body Mon/Wed/Fri, 2 rounds (wk1 10-12 reps, wk2 12-15).
Weeks 3-4: Upper Mon/Thu, Lower Tue/Fri, 3 rounds (wk3 10-12, wk4 12-15).
Other days: walk (steps target). Sunday: rest. Program weeks are calendar
weeks, so starting Tue 1 Dec the last phase also covers 28 Dec - 3 Jan.
"""

WARMUP = {'block': 'warmup', 'rounds': 1, 'rest_between': 0, 'rest_after': 0,
          'items': [{'exercise': 'arm_circles', 'seconds': 40}]}


def _pair(a, b, rounds, reps):
    return {'block': 'pair', 'rounds': rounds, 'rest_between': 30, 'rest_after': 60,
            'items': [{'exercise': a, 'reps': reps}, {'exercise': b, 'reps': reps}]}


def full_body(rounds, reps):
    return [WARMUP,
            _pair('band_squat', 'band_face_pull', rounds, reps),
            _pair('band_chest_press', 'dead_bug', rounds, reps),
            _pair('band_rdl', 'band_row', rounds, reps)]


def upper(rounds, reps):
    return [WARMUP,
            _pair('band_chest_press', 'band_row', rounds, reps),
            _pair('band_overhead_press', 'band_lat_pulldown', rounds, reps),
            _pair('band_bicep_curl', 'band_face_pull', rounds, reps)]


def lower(rounds, reps):
    return [WARMUP,
            _pair('band_squat', 'dead_bug', rounds, reps),
            _pair('band_rdl', 'glute_bridge', rounds, reps),
            {'block': 'single', 'rounds': rounds, 'rest_between': 0, 'rest_after': 60,
             'items': [{'exercise': 'split_squat', 'reps': reps}]}]


WALK = {'kind': 'walk', 'name': 'Walk day'}
REST = {'kind': 'rest', 'name': 'Rest day'}


def _phase(name, week, days, until=None):
    return {'name': name, 'weeks': [week, until or week], 'days': {str(k): v for k, v in days.items()}}


def ajwad_bands_month():
    def fb(rounds, reps):
        s = {'kind': 'session', 'name': 'Full body', 'blocks': full_body(rounds, reps)}
        return {0: s, 1: WALK, 2: s, 3: WALK, 4: s, 5: WALK, 6: REST}

    def ul(rounds, reps):
        u = {'kind': 'session', 'name': 'Upper body', 'blocks': upper(rounds, reps)}
        lo = {'kind': 'session', 'name': 'Lower body', 'blocks': lower(rounds, reps)}
        return {0: u, 1: lo, 2: WALK, 3: u, 4: lo, 5: WALK, 6: REST}

    return [
        _phase('Full body · 2 × 10–12', 1, fb(2, [10, 12])),
        _phase('Full body · 2 × 12–15', 2, fb(2, [12, 15])),
        _phase('Upper / lower · 3 × 10–12', 3, ul(3, [10, 12])),
        _phase('Upper / lower · 3 × 12–15', 4, ul(3, [12, 15]), until=5),   # runs to the end of December
    ]


PERSONAL_TEMPLATES = {
    'ajwad-bands-month': dict(name='Lean muscle – bands, one month', goal='lean_gain', setting='home',
                              equipment_required=['band_tube', 'door_anchor', 'mat'], level=1,
                              days_per_week=3, session_minutes=30, phases=ajwad_bands_month),
}

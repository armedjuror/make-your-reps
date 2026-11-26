"""
Rule engine: onboarding answers -> daily targets and the template to build.
Pure functions, no database access. RULES_VERSION is stored on the profile
with the targets it produced.

General fitness guidance, not medical advice: any health-screen "yes" forces
the gentle path, and calories never go below the floor.
"""
from dataclasses import dataclass, field

RULES_VERSION = 1

GOALS = ('lose_fat', 'lean_muscle', 'general', 'strength')
ACTIVITY_BASE = {'sitting': 1.2, 'some': 1.375, 'most': 1.55}
ACTIVITY_WORDS = {'sitting': 'mostly sitting', 'some': 'some time on your feet', 'most': 'most of the day on your feet'}
SOUTH_ASIA_TZ = {'Asia/Kolkata', 'Asia/Calcutta', 'Asia/Karachi', 'Asia/Dhaka', 'Asia/Kathmandu',
                 'Asia/Katmandu', 'Asia/Colombo', 'Asia/Thimphu', 'Indian/Maldives', 'Asia/Kabul'}
OBESE_CUTOFF = {'south_asia': 25.0, 'who': 30.0}      # BMI; Asian cut-offs for South Asia
KCAL_FLOOR = {'male': 1500, 'female': 1200}
PROTEIN_PER_KG = 1.8
WATER_ML_PER_KG = 35
WORKOUT_DAY_WATER_ML = 500
GENTLE_FLAGS = ('heart', 'chest_pain', 'dizziness', 'meds')
JOINTS = ('knee', 'lower_back', 'shoulder', 'wrist', 'hip', 'ankle', 'neck')
EQUIPMENT = ('band_tube', 'band_loop', 'door_anchor', 'dumbbell', 'kettlebell', 'bench', 'pullup_bar', 'mat')
MINUTES = (15, 25, 45, 60)


class AnswerError(ValueError):
    pass


# ── Answers ────────────────────────────────────────────────

def _num(answers, key, lo, hi, cast=float):
    try:
        v = cast(answers[key])
    except (KeyError, TypeError, ValueError):
        raise AnswerError(f'{key} is required')
    if not lo <= v <= hi:
        raise AnswerError(f'{key} must be between {lo} and {hi}')
    return v


def _choice(answers, key, options, default=None):
    v = answers.get(key, default)
    if v not in options:
        raise AnswerError(f'{key} must be one of {", ".join(map(str, options))}')
    return v


def region_of(answers):
    if answers.get('region') in OBESE_CUTOFF:
        return answers['region']
    return 'south_asia' if answers.get('timezone') in SOUTH_ASIA_TZ else 'who'


def clean(answers):
    """Validate and normalise the questionnaire answers. Raises AnswerError."""
    a = dict(answers or {})
    out = {
        'goal': _choice(a, 'goal', GOALS),
        'why': str(a.get('why') or '').strip()[:200],
        'weight_kg': round(_num(a, 'weight_kg', 30, 300), 1),
        'height_cm': round(_num(a, 'height_cm', 120, 230), 1),
        'age': _num(a, 'age', 16, 90, int),
        'sex': _choice(a, 'sex', ('male', 'female')),
        'experience': _choice(a, 'experience', ('none', 'some', 'regular')),
        'setting': _choice(a, 'setting', ('home', 'gym')),
        'equipment': sorted({e for e in (a.get('equipment') or []) if e in EQUIPMENT}),
        'days_per_week': _num(a, 'days_per_week', 2, 6, int),
        'minutes': _choice(a, 'minutes', MINUTES, 25) if a.get('minutes') is not None else 25,
        'daily_activity': _choice(a, 'daily_activity', tuple(ACTIVITY_BASE)),
        'diet': _choice(a, 'diet', ('veg', 'egg', 'nonveg'), 'nonveg'),
        'track_calories': bool(a.get('track_calories', False)),
        'sleep_hours': round(_num({'s': a.get('sleep_hours', 7)}, 's', 3, 12), 1),
        'region': region_of(a),
        'timezone': str(a.get('timezone') or '')[:64],
        'times': {},
    }
    h = a.get('health') or {}
    out['health'] = {k: bool(h.get(k)) for k in GENTLE_FLAGS + ('joint', 'pregnant', 'surgery')}
    out['health']['joints'] = sorted({j for j in (h.get('joints') or []) if j in JOINTS}) if h.get('joint') else []
    if out['health']['pregnant'] and out['sex'] != 'female':
        out['health']['pregnant'] = False
    t = a.get('times') or {}
    for k in ('wake', 'workout'):
        if t.get(k):
            out['times'][k] = _hhmm(t[k], k)
    meals = {k: _hhmm(v, k) for k, v in (t.get('meals') or {}).items() if v and k in ('breakfast', 'lunch', 'snack', 'dinner')}
    if meals:
        out['times']['meals'] = meals
    if 'weigh_in_day' in t:
        out['times']['weigh_in_day'] = int(t['weigh_in_day']) % 7
    return out


def _hhmm(v, key):
    try:
        h, m = (int(x) for x in str(v)[:5].split(':'))
        if 0 <= h < 24 and 0 <= m < 60:
            return f'{h:02d}:{m:02d}'
    except ValueError:
        pass
    raise AnswerError(f'{key} must be a time like 07:30')


# ── Numbers ────────────────────────────────────────────────

def bmr(kg, cm, age, sex):
    """Mifflin-St Jeor."""
    return 10 * kg + 6.25 * cm - 5 * age + (5 if sex == 'male' else -161)


def activity_factor(daily_activity, days_per_week):
    """Sitting + 3-4 days = 1.45; sitting + 2 days = 1.3."""
    bump = 0.35 if days_per_week >= 5 else 0.25 if days_per_week >= 3 else 0.1
    return ACTIVITY_BASE[daily_activity] + bump


def bmi(kg, cm):
    return kg / (cm / 100) ** 2


def kcal_adjust(goal, bmi_value, region):
    """(adjust, phase): fat loss, gain, lean gain or recomposition."""
    if goal == 'lose_fat' or bmi_value >= OBESE_CUTOFF[region]:
        return -0.20, 'fat loss'
    if bmi_value < 18.5:
        return 0.15, 'gain'
    if goal == 'lean_muscle' and bmi_value < 22:
        return 0.10, 'lean gain'
    return 0.0, 'recomposition'


def round_to(x, base):
    return int(base * round(x / base))


@dataclass
class Targets:
    kcal: int
    protein_g: int
    water_ml: int
    water_workout_ml: int
    steps: int
    sleep_h: tuple
    bmr: int
    tdee: int
    bmi: float
    adjust: float
    phase: str
    explanation: dict = field(default_factory=dict)

    def as_dict(self):
        return {'kcal': self.kcal, 'protein_g': self.protein_g, 'water_ml': self.water_ml,
                'water_workout_ml': self.water_workout_ml, 'steps': self.steps, 'sleep_h': list(self.sleep_h)}


def targets(a):
    """Daily targets with a plain-English line per number. ``a`` = clean(answers)."""
    kg, cm = a['weight_kg'], a['height_cm']
    b = bmr(kg, cm, a['age'], a['sex'])
    factor = activity_factor(a['daily_activity'], a['days_per_week'])
    tdee = b * factor
    bmi_value = bmi(kg, cm)
    adjust, phase = kcal_adjust(a['goal'], bmi_value, a['region'])
    if a['age'] < 18:
        adjust = max(adjust, 0.0)            # no deficit for teenagers
    kcal = round_to(tdee * (1 + adjust), 10)
    floor = KCAL_FLOOR[a['sex']]
    floored = kcal < floor
    kcal = max(kcal, floor)
    capped = bmi_value >= 25
    protein_kg = 25 * (cm / 100) ** 2 if capped else kg
    protein = round(PROTEIN_PER_KG * protein_kg)
    water = round_to(WATER_ML_PER_KG * kg, 100)
    steps = 7000 if a['experience'] == 'none' else 8000
    if a['goal'] == 'lose_fat':
        steps += 1000                        # fat-loss bias: more steps
    cutoff = 'Asian' if a['region'] == 'south_asia' else 'WHO'
    sign = f'{adjust:+.0%}' if adjust else 'no change'
    expl = {
        'kcal': (f'Your body burns about {round(b):,} kcal at rest. With {ACTIVITY_WORDS[a["daily_activity"]]} '
                 f'and {a["days_per_week"]} workouts a week that is about {round(tdee):,} kcal. '
                 f'Your BMI is {bmi_value:.1f} ({cutoff} cut-offs), so the plan is {phase} ({sign}): {kcal:,} kcal.'
                 + (f' Raised to the {floor:,} kcal floor: the plan never goes lower.' if floored else '')),
        'protein_g': (f'{PROTEIN_PER_KG} g per kg of body weight' + (' at a BMI of 25 (capped for your height)' if capped else '')
                      + f': {protein} g a day, about {round(protein / 4)} g a meal.'),
        'water_ml': f'{WATER_ML_PER_KG} ml per kg: {water / 1000:.1f} L a day, plus {WORKOUT_DAY_WATER_ML / 1000:.1f} L on workout days.',
        'steps': (f'{steps:,} steps a day' + (' to start, since you haven\'t trained lately.' if a['experience'] == 'none' else '.')
                  + (' Fat loss adds 1,000.' if a['goal'] == 'lose_fat' else '')),
        'sleep_h': '7-8 hours. Recovery is when the muscle gets built.',
    }
    return Targets(kcal=kcal, protein_g=protein, water_ml=water, water_workout_ml=water + WORKOUT_DAY_WATER_ML,
                   steps=steps, sleep_h=(7, 8), bmr=round(b), tdee=round(tdee), bmi=round(bmi_value, 1),
                   adjust=adjust, phase=phase, explanation=expl)


# ── Template pick ──────────────────────────────────────────

def level_for_week(experience, week):
    """None -> 1; some -> 1 for 2 weeks, then 2; regular -> 2."""
    if experience == 'regular':
        return 2
    if experience == 'some':
        return 1 if week <= 2 else 2
    return 1


def joint_flags(a):
    return list(a['health'].get('joints') or [])


def gentle_reason(a):
    h = a['health']
    if h.get('pregnant'):
        return 'pregnancy'
    if any(h.get(k) for k in GENTLE_FLAGS):
        return 'health'
    return None


def family_for_days(days):
    return 'full_body' if days <= 3 else 'upper_lower' if days <= 5 else 'ppl'


def equipment_kind(a):
    if a['setting'] == 'gym':
        return 'gym'
    return 'home_bands' if set(a['equipment']) & {'band_tube', 'band_loop'} else 'home_bodyweight'


def pick_template(a, templates):
    """
    First match wins:
    1. Pregnancy -> walking + mobility only; heart / chest pain / dizziness / medication -> gentle.
    2. Filter by setting, equipment, days per week (closest at or below) and session length.
    Returns (template, banner or None). ``templates`` are ProgramTemplate-like objects.
    """
    reason = gentle_reason(a)
    banner = None
    pool = [t for t in templates if not getattr(t, 'is_personal', False)]
    if reason == 'pregnancy':
        banner = 'Walking and mobility only during pregnancy and for 6 months after birth. Check with your doctor before anything harder.'
        pick = [t for t in pool if t.slug == 'walk-mobility']
        return (pick[0] if pick else None), banner
    if reason == 'health':
        banner = 'Talk to a doctor before increasing intensity. Your plan starts gentle.'
        pool = [t for t in pool if t.gentle and t.slug != 'walk-mobility']
    else:
        pool = [t for t in pool if not t.gentle]
    if a['health'].get('surgery') and not banner:
        banner = 'You had surgery recently: get your doctor\'s go-ahead before you start.'
    kind = equipment_kind(a)
    have = set(a['equipment']) | {'none'}
    setting_ok = [t for t in pool if t.setting == a['setting'] and
                  (a['setting'] == 'gym' or set(t.equipment_required) <= have)]
    pool = setting_ok or pool
    if not reason:
        family = family_for_days(a['days_per_week'])
        exact = [t for t in pool if t.slug.startswith(family.replace('_', '-')) and t.slug.endswith(kind.replace('_', '-'))]
        pool = exact or pool
    fits = [t for t in pool if t.days_per_week <= a['days_per_week']] or pool
    fits.sort(key=lambda t: (-t.days_per_week, abs(t.session_minutes - a['minutes']), t.slug))
    return (fits[0] if fits else None), banner

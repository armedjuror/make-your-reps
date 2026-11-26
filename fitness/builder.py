"""
Session builder: fills a template's slots from the exercise library.
Deterministic: the same template, answers and library give the same plan.

Slot filling
  candidates = exercises matching the slot pattern (and muscle, if given)
  drop those needing equipment the user lacks or excluding their setting
  drop contraindicated ones; follow the regression chain until one passes, else drop the slot
  keep level <= user level, prefer level == user level
  no exercise twice in a day; rotate alternatives across days for rotate: true
  tie-break: fixed priority per pattern, then id
Session shape: warm-up (2-3 timed) -> main pairs heavy first -> accessory circuit -> cool-down.
Hard rules are checked by validate() on every build (and on any AI-proposed edit later).
"""
from fitness.rules import level_for_week
from fitness.steps import build_workout_steps, est_total

PRIORITY = {
    'squat': ['band_squat', 'goblet_squat', 'bodyweight_squat', 'barbell_back_squat', 'box_squat'],
    'hinge': ['band_rdl', 'dumbbell_rdl', 'romanian_deadlift', 'kettlebell_deadlift', 'hip_hinge', 'glute_bridge'],
    'horizontal_push': ['band_chest_press', 'push_up', 'dumbbell_bench_press', 'knee_push_up', 'incline_push_up'],
    'horizontal_pull': ['band_row', 'dumbbell_row', 'seated_cable_row', 'band_face_pull'],
    'vertical_push': ['band_overhead_press', 'dumbbell_overhead_press', 'pike_push_up'],
    'vertical_pull': ['band_lat_pulldown', 'lat_pulldown', 'assisted_pull_up', 'pull_up'],
    'lunge': ['split_squat', 'reverse_lunge', 'rear_leg_raised_lunge', 'walking_lunge'],
    'core_anti_extension': ['dead_bug', 'plank', 'bird_dog'],
}
# When a slot can't be filled: the same movement family first, then any light core / small-muscle move
FALLBACK = {
    'vertical_pull': ['horizontal_pull'], 'horizontal_pull': ['vertical_pull'],
    'vertical_push': ['horizontal_push'], 'horizontal_push': ['vertical_push'],
    'lunge': ['squat'], 'squat': ['lunge'], 'hinge': ['hinge'],
}
LIGHT_FALLBACK = ['core_anti_extension', 'core_anti_rotation', 'core_lateral', 'core_flexion',
                  'isolation_lower:calves', 'hinge:glutes', 'isolation_upper']
REST = {'heavy': (60, 90), 'moderate': (45, 60), 'light': (30, 30)}
WARMUP_SECONDS = 35
COOLDOWN_SECONDS = 30
COMPOUND = {'squat', 'hinge', 'lunge', 'horizontal_push', 'vertical_push', 'horizontal_pull', 'vertical_pull'}
PUSH, PULL = {'horizontal_push', 'vertical_push'}, {'horizontal_pull', 'vertical_pull'}


class Ctx:
    def __init__(self, equipment, setting='home', joints=(), experience='none', goal='general', minutes=30):
        self.equipment = set(equipment or []) | {'none'}
        if setting == 'gym':
            self.equipment |= {'dumbbell', 'kettlebell', 'barbell', 'bench', 'pullup_bar', 'cable_machine',
                               'machine', 'mat', 'band_tube', 'band_loop', 'door_anchor'}
        self.setting = setting
        self.joints = set(joints or [])
        self.experience = experience
        self.goal = goal
        self.minutes = minutes

    @classmethod
    def from_answers(cls, a):
        return cls(a['equipment'], a['setting'], a['health'].get('joints') or [], a['experience'], a['goal'], a['minutes'])


def parse_slot(slot):
    pattern, _, muscle = slot.partition(':')
    return pattern, muscle or None


def usable(ex, ctx):
    return (not ex.retired and set(ex.equipment) <= ctx.equipment and ctx.setting in ex.settings)


def safe(ex, ctx):
    return not (set(ex.contraindications or []) & ctx.joints)


def resolve_safe(ex, ctx, library):
    """The exercise, or its first regression that avoids the user's flagged joints."""
    seen = set()
    while ex and ex.id not in seen:
        seen.add(ex.id)
        if safe(ex, ctx) and usable(ex, ctx):
            return ex
        ex = library.get(ex.regression_id) if ex.regression_id else None
    return None


def rank(ex, pattern, level, intensity):
    pri = PRIORITY.get(pattern, [])
    return (0 if ex.level == level else 1, 0 if (intensity and ex.intensity == intensity) else 1,
            pri.index(ex.id) if ex.id in pri else len(pri), ex.id)


def candidates(slot, ctx, library, level, intensity=None):
    pattern, muscle = parse_slot(slot)
    out, seen = [], set()
    for ex in sorted(library.values(), key=lambda e: e.id):
        if ex.pattern != pattern or (muscle and muscle not in ex.primary_muscles):
            continue
        if not usable(ex, ctx) and not ex.regression_id:
            continue
        ok = resolve_safe(ex, ctx, library) if not safe(ex, ctx) or not usable(ex, ctx) else ex
        if ok and ok.level <= level and ok.id not in seen:
            seen.add(ok.id)
            out.append(ok)
    out.sort(key=lambda e: rank(e, pattern, level, intensity))
    return out


def fallback(item, ctx, library, level, used, partners):
    """Candidates for an unfillable slot that never pair two heavy moves for the same muscles."""
    pattern, _ = parse_slot(item['slot'])
    taken = {m for p in partners for m in library[p['exercise']].primary_muscles}
    slots = FALLBACK.get(pattern, [])
    if item.get('intensity', 'light') == 'light' or not slots:
        slots = slots + LIGHT_FALLBACK
    for slot in slots:
        cands = [c for c in candidates(slot, ctx, library, level, item.get('intensity'))
                 if c.id not in used and not (set(c.primary_muscles) & taken)]
        if cands:
            return cands
    return []


def fill_day(blocks, ctx, library, level, day_index, trained=None):
    """Concrete blocks for one session day. Returns (blocks, dropped_slots)."""
    used, dropped, out = set(), [], []
    for b in blocks:
        kind = b.get('block')
        if b.get('auto'):
            out.append({'block': kind, 'auto': True})       # filled after the main work is known
            continue
        items = []
        for it in b.get('items', []):
            cands = [c for c in candidates(it['slot'], ctx, library, level, it.get('intensity')) if c.id not in used]
            if not cands:
                cands = fallback(it, ctx, library, level, used, items)
            if not cands:
                dropped.append(it['slot'])
                continue
            pick = cands[day_index % len(cands)] if it.get('rotate') else cands[0]
            used.add(pick.id)
            item = {'exercise': pick.id, 'slot': it['slot']}
            if pick.measure == 'time':
                item['seconds'] = pick.default_seconds or 30
            else:
                item['reps'] = it.get('reps') or pick.default_reps
            items.append(item)
        if not items:
            continue
        nb = {'block': kind, 'rounds': b.get('rounds', 1), 'items': items}
        heavy = max(items, key=lambda i: ['light', 'moderate', 'heavy'].index(library[i['exercise']].intensity))
        intensity = library[heavy['exercise']].intensity
        lo, hi = REST[intensity]
        nb['rest_between'] = 30
        nb['rest_after'] = hi if level == 1 else lo         # level 1 users get the upper value
        if kind == 'circuit':
            nb['rest_after'] = 60
        if ctx.goal == 'lose_fat' and kind == 'pair':
            nb['block'], nb['rest_after'] = 'circuit', 60      # fat-loss bias: more circuit work
        out.append(nb)
    # Warm-up and cool-down
    muscles = {m for b in out for i in b.get('items', []) for m in library[i['exercise']].primary_muscles}
    final = []
    for b in out:
        if not b.get('auto'):
            final.append(b)
            continue
        if b['block'] == 'warmup':
            pool = [e for e in sorted(library.values(), key=lambda e: e.id)
                    if e.pattern in ('warmup', 'mobility') and usable(e, ctx) and safe(e, ctx) and e.id not in used]
            seconds = WARMUP_SECONDS
        else:
            pool = [e for e in sorted(library.values(), key=lambda e: e.id)
                    if e.pattern == 'stretch' and usable(e, ctx) and safe(e, ctx) and e.id not in used
                    and set(e.primary_muscles) & muscles]
            seconds = COOLDOWN_SECONDS
        if not pool:
            continue
        start = day_index % len(pool)
        chosen = (pool[start:] + pool[:start])[:3]
        used.update(e.id for e in chosen)
        final.append({'block': b['block'], 'rounds': 1, 'rest_between': 0, 'rest_after': 0,
                      'items': [{'exercise': e.id, 'seconds': seconds} for e in chosen]})
    return final, dropped


class _Day:
    def __init__(self, blocks):
        self.blocks = blocks


def session_seconds(blocks, library):
    return est_total(build_workout_steps(_Day(blocks), library))


def fit_time(blocks, library, minutes):
    """Trim accessory rounds first, then the warm-up to 2 items, until the session fits minutes +10%."""
    limit = minutes * 60 * 1.1
    blocks = [dict(b, items=list(b['items'])) for b in blocks]
    while session_seconds(blocks, library) > limit:
        acc = [b for b in blocks if b['block'] == 'circuit' and b.get('rounds', 1) > 1]
        if acc:
            acc[-1]['rounds'] -= 1
            continue
        warm = next((b for b in blocks if b['block'] == 'warmup' and len(b['items']) > 2), None)
        if warm:
            warm['items'] = warm['items'][:2]
            continue
        acc = [b for b in blocks if b['block'] == 'circuit']
        if acc:
            blocks.remove(acc[-1])
            continue
        main = [b for b in blocks if b['block'] in ('pair', 'single') and b.get('rounds', 1) > 1]
        if main:
            main[-1]['rounds'] -= 1
            continue
        break
    return blocks


def build(template, ctx, library):
    """
    Resolve a slot template into concrete phases for Program install.
    Returns (phases, report) where report = {dropped: [...], violations: [...]}.
    """
    phases, dropped = [], []
    for ph in template.phases:
        level = level_for_week(ctx.experience, ph['weeks'][0])
        days, day_index = {}, 0
        for wd in sorted(ph['days'], key=int):
            day = ph['days'][wd]
            if day['kind'] != 'session':
                days[wd] = dict(day)
                continue
            blocks, miss = fill_day(day['blocks'], ctx, library, level, day_index)
            dropped += miss
            blocks = fit_time(blocks, library, ctx.minutes)
            days[wd] = {'kind': 'session', 'name': day['name'], 'blocks': blocks}
            if not any(b['block'] in ('pair', 'single', 'circuit') for b in blocks):
                days[wd] = {'kind': 'walk', 'name': 'Walk day'}   # nothing could be filled: walk instead
            day_index += 1
        phases.append({'name': ph['name'], 'weeks': ph['weeks'], 'days': days})
    return phases, {'dropped': sorted(set(dropped)), 'violations': validate(phases, library, ctx.minutes)}


# ── Hard rules ─────────────────────────────────────────────

def validate(phases, library, minutes=None):
    """Hard rules; returns a list of violations (empty = valid)."""
    out = []
    for ph in phases:
        push = pull = 0
        patterns = set()
        for wd, day in ph['days'].items():
            if day.get('kind') != 'session':
                continue
            seq = [i['exercise'] for b in day['blocks'] if b['block'] not in ('warmup', 'cooldown') for i in b['items']]
            exs = [library[e] for e in seq if e in library]
            # 1. never two heavy items for the same primary muscles back to back
            for a, b in zip(exs, exs[1:]):
                if a.intensity == b.intensity == 'heavy' and set(a.primary_muscles) & set(b.primary_muscles):
                    out.append(f'{ph["name"]} day {wd}: {a.id} and {b.id} are heavy for the same muscles back to back')
            # 2. compound before isolation within each main block (a pair is heavy compound + light partner)
            for b in day['blocks']:
                if b['block'] not in ('pair', 'single'):
                    continue
                seen_iso = False
                for i in b['items']:
                    e = library.get(i['exercise'])
                    if not e:
                        continue
                    if e.pattern.startswith('isolation'):
                        seen_iso = True
                    elif seen_iso and e.pattern in COMPOUND:
                        out.append(f'{ph["name"]} day {wd}: compound {e.id} comes after an isolation move')
            # 4. rest by intensity
            for b in day['blocks']:
                if b['block'] in ('pair', 'single'):
                    top = max((library[i['exercise']].intensity for i in b['items'] if i['exercise'] in library),
                              key=['light', 'moderate', 'heavy'].index, default='light')
                    lo, hi = REST[top]
                    if not lo <= b.get('rest_after', lo) <= hi:
                        out.append(f'{ph["name"]} day {wd}: rest {b.get("rest_after")} s outside {lo}-{hi} s for {top} work')
            # 5. session time
            if minutes:
                secs = session_seconds(day['blocks'], library)
                if secs > minutes * 60 * 1.1:
                    out.append(f'{ph["name"]} day {wd}: {round(secs / 60)} min is over {minutes} min')
            for b in day['blocks']:
                for i in b['items']:
                    e = library.get(i['exercise'])
                    if not e:
                        continue
                    patterns.add(e.pattern)
                    if b['block'] in ('warmup', 'cooldown'):
                        continue
                    if e.pattern in PUSH:
                        push += b.get('rounds', 1)
                    elif e.pattern in PULL:
                        pull += b.get('rounds', 1)
        # 3. weekly balance
        if push or pull:
            if abs(push - pull) > 0.2 * max(push, pull):
                out.append(f'{ph["name"]}: push sets ({push}) not within 20% of pull sets ({pull})')
        sessions = [d for d in ph['days'].values() if d.get('kind') == 'session']
        if sessions and any(p in patterns for p in COMPOUND) and not ({'squat', 'hinge'} <= patterns):
            out.append(f'{ph["name"]}: the week needs both a squat and a hinge')
    return out

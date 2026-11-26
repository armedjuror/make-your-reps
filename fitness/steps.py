"""
Step lists: any session, workout or Pomodoro, is expanded server-side into a
flat, ordered list of timed steps that the FocusPlayer just plays.

Step = {kind, title, exercise_id, target, est_seconds, advance, fallback_seconds,
        next_preview, segment, ...}
exercise_set -> manual_with_fallback (never auto-advances on time alone);
exercise_timed, rest, focus, break, transition -> auto.
"""
from fitness.program import WARMUP_BLOCKS

TRANSITION_SECONDS = 5
FALLBACK_FACTOR = 1.5
SET_PAUSE_SECONDS = 4          # getting into position, counted into est time


def _reps(item, ex):
    reps = item.get('reps') or (ex.default_reps if ex else None) or [10, 12]
    return [reps[0], reps[-1]] if isinstance(reps, (list, tuple)) else [reps, reps]


def _set_step(ex, item, set_index, set_total, side, segment, block, rnd):
    name = ex.name if ex else item['exercise'].replace('_', ' ').capitalize()
    seconds = item.get('seconds') or (ex.default_seconds if ex and ex.measure == 'time' and not item.get('reps') else None)
    side_label = f' · {side} side' if side else ''
    base = {
        'exercise_id': item['exercise'], 'set_index': set_index, 'set_total': set_total, 'side': side,
        'segment': segment, 'block': block, 'round': rnd, 'last_set': set_index == set_total,
        'intensity': ex.intensity if ex else 'moderate',
    }
    if seconds:
        return {**base, 'kind': 'exercise_timed', 'title': f'{name} · set {set_index} of {set_total}{side_label}',
                'target': {'seconds': int(seconds)}, 'est_seconds': int(seconds), 'advance': 'auto'}
    reps = _reps(item, ex)
    spr = ex.sec_per_rep if ex else 3.0
    est = int(round(reps[1] * spr)) + SET_PAUSE_SECONDS
    return {**base, 'kind': 'exercise_set', 'title': f'{name} · set {set_index} of {set_total}{side_label}',
            'target': {'reps': reps}, 'est_seconds': est, 'advance': 'manual_with_fallback',
            'fallback_seconds': int(round(est * FALLBACK_FACTOR)), 'sec_per_rep': spr}


def _timed(ex, item, segment, block, label):
    name = ex.name if ex else item['exercise'].replace('_', ' ').capitalize()
    seconds = int(item.get('seconds') or (ex.default_seconds if ex else None) or 30)
    return {'kind': 'exercise_timed', 'title': f'{name} · {label}', 'exercise_id': item['exercise'],
            'target': {'seconds': seconds}, 'est_seconds': seconds, 'advance': 'auto', 'segment': segment,
            'block': block, 'warmup': True, 'set_index': 1, 'set_total': 1, 'side': ''}


def _rest(seconds, segment, block):
    return {'kind': 'rest', 'title': 'Rest', 'exercise_id': None, 'target': {'seconds': int(seconds)},
            'est_seconds': int(seconds), 'advance': 'auto', 'segment': segment, 'block': block}


def build_workout_steps(day, library, overrides=None):
    """
    Steps for a session DayTemplate. ``library`` = {id: Exercise}. Sets of one
    exercise are numbered across rounds; unilateral moves play right then left
    with a "Switch sides" transition (alternating moves are one clip, never split).
    """
    overrides = overrides or {}
    blocks = []
    for b in day.blocks or []:
        items = []
        for it in b.get('items', []):
            ex_id = overrides.get(it.get('exercise'), it.get('exercise'))
            if ex_id:
                items.append({**it, 'exercise': ex_id})
        if items:
            blocks.append({**b, 'items': items})

    totals = {}
    for b in blocks:
        if b.get('block') in WARMUP_BLOCKS:
            continue
        for it in b['items']:
            totals[it['exercise']] = totals.get(it['exercise'], 0) + int(b.get('rounds', 1) or 1)

    steps, counter = [], {}
    for bi, b in enumerate(blocks):
        kind = b.get('block')
        if kind in WARMUP_BLOCKS:
            label = 'warm-up' if kind == 'warmup' else 'cool-down'
            for it in b['items']:
                steps.append(_timed(library.get(it['exercise']), it, bi, kind, label))
            continue
        rounds = int(b.get('rounds', 1) or 1)
        between, after = int(b.get('rest_between', 0) or 0), int(b.get('rest_after', 0) or 0)
        for r in range(1, rounds + 1):
            for ii, it in enumerate(b['items']):
                ex = library.get(it['exercise'])
                counter[it['exercise']] = counter.get(it['exercise'], 0) + 1
                n, total = counter[it['exercise']], totals[it['exercise']]
                if ex and ex.unilateral:
                    steps.append(_set_step(ex, it, n, total, 'right', bi, kind, r))
                    steps.append({'kind': 'transition', 'title': 'Switch sides', 'exercise_id': it['exercise'],
                                  'target': {'seconds': TRANSITION_SECONDS}, 'est_seconds': TRANSITION_SECONDS,
                                  'advance': 'auto', 'segment': bi, 'block': kind})
                    steps.append(_set_step(ex, it, n, total, 'left', bi, kind, r))
                else:
                    steps.append(_set_step(ex, it, n, total, '', bi, kind, r))
                if ii < len(b['items']) - 1 and between:
                    steps.append(_rest(between, bi, kind))
            last_round = r == rounds
            if after and not (last_round and bi == len(blocks) - 1):
                # No rest after the last round when only a cool-down follows
                if not (last_round and all(x.get('block') in WARMUP_BLOCKS for x in blocks[bi + 1:])):
                    steps.append(_rest(after, bi, kind))
    return _finish(steps, library)


def build_focus_steps(focus_min=25, break_min=5, cycles=4, long_break_min=15):
    steps = []
    for c in range(1, cycles + 1):
        steps.append({'kind': 'focus', 'title': f'Focus {c} of {cycles}', 'cycle': c,
                      'target': {'seconds': focus_min * 60}, 'est_seconds': focus_min * 60,
                      'advance': 'auto', 'segment': c - 1})
        if c < cycles:
            long = c % 4 == 0
            mins = long_break_min if long else break_min
            steps.append({'kind': 'break', 'title': 'Long break' if long else 'Break', 'cycle': c,
                          'target': {'seconds': mins * 60}, 'est_seconds': mins * 60,
                          'advance': 'auto', 'segment': c - 1})
    return _finish(steps, {})


def _dose(step):
    t = step.get('target') or {}
    if 'reps' in t:
        lo, hi = t['reps']
        return f'{lo}–{hi} reps' if lo != hi else f'{lo} reps'
    s = t.get('seconds', 0)
    return f'{s // 60} min' if s >= 120 else f'{s} s'


def _finish(steps, library):
    """Index the steps and fill each one's next_preview (next non-rest step)."""
    for i, s in enumerate(steps):
        s['index'] = i
        s['dose'] = _dose(s)
        nxt = next((x for x in steps[i + 1:] if x['kind'] not in ('rest', 'transition')), None)
        if nxt:
            ex = library.get(nxt.get('exercise_id')) if nxt.get('exercise_id') else None
            name = ex.name if ex else nxt['title'].split(' · ')[0]
            s['next_preview'] = f'{name} · {_dose(nxt)}'
            s['next_exercise_id'] = nxt.get('exercise_id')
        else:
            s['next_preview'] = None
    return steps


def est_total(steps):
    return sum(int(s.get('est_seconds', 0)) for s in steps)


def planned_sets(steps):
    """Units of work: (exercise, set_index) pairs; a unilateral set is one unit (both sides)."""
    return {(s['exercise_id'], s['set_index']) for s in steps
            if s['kind'] in ('exercise_set', 'exercise_timed') and not s.get('warmup')}

"""Onboarding: answers -> targets, template, built plan; preview first, then confirm."""
from django.db import transaction
from django.utils import timezone

from board.days import logical_today
from fitness import rules
from fitness.builder import Ctx, build
from fitness.models import Exercise, FitnessProfile
from fitness.setup import ensure_fitness, install_program
from fitness.templates_data import ensure_templates

DISCLAIMER = 'General fitness guidance, not medical advice.'


def plan(answers):
    """Everything the confirm screen shows. Raises rules.AnswerError on bad answers."""
    a = rules.clean(answers)
    t = rules.targets(a)
    template, banner = rules.pick_template(a, list(ensure_templates()))
    if template is None:
        raise rules.AnswerError('No plan fits these answers yet')
    library = Exercise.objects.filter(retired=False).in_bulk()
    phases, report = build(template, Ctx.from_answers(a), library)
    week1 = phases[0]['days'] if phases else {}
    names = {e.id: e.name for e in library.values()}
    days = []
    for wd in sorted(week1, key=int):
        d = week1[wd]
        moves = [names.get(i['exercise'], i['exercise']) for b in d.get('blocks', [])
                 if b['block'] not in ('warmup', 'cooldown') for i in b['items']]
        days.append({'weekday': int(wd), 'kind': d['kind'], 'name': d.get('name', ''), 'exercises': moves})
    return a, t, template, phases, {
        'answers': a, 'targets': t.as_dict(), 'explanation': t.explanation,
        'numbers': {'bmr': t.bmr, 'tdee': t.tdee, 'bmi': t.bmi, 'phase': t.phase, 'adjust': t.adjust},
        'template': {'slug': template.slug, 'name': template.name, 'gentle': template.gentle},
        'banner': banner, 'disclaimer': DISCLAIMER, 'week1': days, 'report': report,
        'rules_version': rules.RULES_VERSION,
    }


@transaction.atomic
def confirm(user_id, answers):
    a, t, template, phases, out = plan(answers)
    profile, _ = FitnessProfile.objects.get_or_create(user_id=user_id)
    versions = list(profile.answers or [])
    versions.append({'v': len(versions) + 1, 'at': timezone.now().isoformat(), 'answers': a,
                     'rules_version': rules.RULES_VERSION})
    profile.answers = versions          # versioned: re-onboarding never loses history
    profile.health_flags = [k for k, v in a['health'].items() if v is True] + a['health']['joints']
    profile.equipment = a['equipment']
    profile.setting = a['setting']
    profile.weight_kg, profile.height_cm, profile.age, profile.sex = a['weight_kg'], a['height_cm'], a['age'], a['sex']
    profile.activity_level, profile.goal, profile.why = a['daily_activity'], a['goal'], a['why']
    profile.targets = t.as_dict()
    profile.explanation = t.explanation
    profile.track_calories = a['track_calories']
    profile.times = {**(profile.times or {}), **a['times']}
    profile.times.setdefault('weigh_in_day', 0)
    profile.rules_version = rules.RULES_VERSION
    profile.save()
    health, activity, _ = ensure_fitness(user_id, profile.targets, a['track_calories'])
    program = install_program(activity, template, logical_today(user_id), name=template.name, phases=phases)
    # Starting weight goes straight into the tracker
    from board import metrics as mx
    from board.models import Metric
    w = Metric.objects.filter(user_id=user_id, domain='fitness', fitness_key='weight').first()
    if w and not w.entries.exists():
        mx.log_entry(w, value=a['weight_kg'])
    out['program'] = {'id': program.id, 'name': program.name, 'start_date': program.start_date.isoformat()}
    return out


def latest_answers(user_id):
    p = FitnessProfile.objects.filter(user_id=user_id).first()
    return p.latest_answers() if p else None

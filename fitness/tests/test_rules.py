"""rules.py (pure), the session builder's hard rules, and the onboarding endpoint."""
import copy
import json
from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from fitness import rules
from fitness.builder import Ctx, build, candidates, validate
from fitness.models import FitnessProfile, Program
from fitness.templates_data import launch_templates

from .base import FitnessBase

AJWAD = dict(goal='lean_muscle', why='Feel strong for the next decade', weight_kg=67.8, height_cm=171, age=26,
             sex='male', experience='some', setting='home', equipment=['band_tube', 'door_anchor', 'mat'],
             days_per_week=3, minutes=25, daily_activity='sitting', diet='nonveg', sleep_hours=7,
             timezone='Asia/Kolkata', times={'wake': '05:30', 'workout': '18:30',
                                             'meals': {'breakfast': '08:00', 'lunch': '13:00', 'snack': '17:00', 'dinner': '21:00'}})


def answers(**kw):
    a = copy.deepcopy(AJWAD)
    a.update(kw)
    return rules.clean(a)


class RulesTest(SimpleTestCase):
    def test_ajwad_targets(self):
        t = rules.targets(answers())
        self.assertEqual(t.bmr, 1622)
        self.assertEqual(t.kcal, 2350)
        self.assertEqual(t.protein_g, 122)
        self.assertEqual(t.water_ml, 2400)
        self.assertEqual(t.water_workout_ml, 2900)
        self.assertEqual(t.bmi, 23.2)
        self.assertEqual(t.phase, 'recomposition')
        self.assertIn('2,350 kcal', t.explanation['kcal'])
        self.assertIn('Asian', t.explanation['kcal'])

    def test_activity_factor(self):
        self.assertAlmostEqual(rules.activity_factor('sitting', 3), 1.45)
        self.assertAlmostEqual(rules.activity_factor('sitting', 2), 1.3)
        self.assertAlmostEqual(rules.activity_factor('most', 5), 1.9)

    def test_mifflin_st_jeor(self):
        self.assertEqual(rules.bmr(60, 160, 30, 'female'), 600 + 1000 - 150 - 161)

    def test_asian_cutoff_turns_bmi_26_into_fat_loss(self):
        a = answers(weight_kg=76.0)                       # BMI 26.0
        self.assertEqual(rules.targets(a).phase, 'fat loss')
        who = answers(weight_kg=76.0, timezone='Europe/London')
        self.assertEqual(rules.targets(who).phase, 'lean gain' if rules.bmi(76, 171) < 22 else 'recomposition')

    def test_goal_adjustments(self):
        self.assertEqual(rules.kcal_adjust('lose_fat', 22, 'who'), (-0.20, 'fat loss'))
        self.assertEqual(rules.kcal_adjust('general', 17.9, 'who'), (0.15, 'gain'))
        self.assertEqual(rules.kcal_adjust('lean_muscle', 21.5, 'who'), (0.10, 'lean gain'))
        self.assertEqual(rules.kcal_adjust('lean_muscle', 23, 'who'), (0.0, 'recomposition'))

    def test_calorie_floor(self):
        a = answers(sex='female', weight_kg=42, height_cm=150, age=60, goal='lose_fat', days_per_week=2)
        t = rules.targets(a)
        self.assertEqual(t.kcal, 1200)
        self.assertIn('floor', t.explanation['kcal'])

    def test_protein_capped_at_bmi_25(self):
        t = rules.targets(answers(weight_kg=110))
        self.assertEqual(t.protein_g, round(1.8 * 25 * 1.71 ** 2))

    def test_steps(self):
        self.assertEqual(rules.targets(answers(experience='none')).steps, 7000)
        self.assertEqual(rules.targets(answers()).steps, 8000)
        self.assertEqual(rules.targets(answers(goal='lose_fat')).steps, 9000)

    def test_no_deficit_for_teenagers(self):
        t = rules.targets(answers(age=17, goal='lose_fat'))
        self.assertGreaterEqual(t.adjust, 0)

    def test_validation(self):
        for bad in ({'weight_kg': 10}, {'goal': 'shred'}, {'days_per_week': 7}, {'times': {'wake': '25:00'}}):
            with self.assertRaises(rules.AnswerError):
                answers(**bad)
        self.assertEqual(answers(health={'joint': True, 'joints': ['knee', 'elbow']})['health']['joints'], ['knee'])

    def test_level_for_week(self):
        self.assertEqual([rules.level_for_week('some', w) for w in (1, 2, 3)], [1, 1, 2])
        self.assertEqual(rules.level_for_week('none', 4), 1)
        self.assertEqual(rules.level_for_week('regular', 1), 2)

    def templates(self):
        return [SimpleNamespace(slug=s, is_personal=False, **d) for s, d in launch_templates()]

    def test_twelve_templates(self):
        self.assertEqual(len(self.templates()), 12)
        self.assertEqual(sum(1 for t in self.templates() if t.gentle), 3)

    def test_template_pick(self):
        T = self.templates()
        self.assertEqual(rules.pick_template(answers(), T)[0].slug, 'full-body-home-bands')
        self.assertEqual(rules.pick_template(answers(days_per_week=4), T)[0].slug, 'upper-lower-home-bands')
        self.assertEqual(rules.pick_template(answers(days_per_week=6, setting='gym'), T)[0].slug, 'ppl-gym')
        self.assertEqual(rules.pick_template(answers(equipment=[]), T)[0].slug, 'full-body-home-bodyweight')

    def test_health_screen_forces_gentle(self):
        T = self.templates()
        tpl, banner = rules.pick_template(answers(health={'meds': True}), T)
        self.assertTrue(tpl.gentle)
        self.assertIn('doctor', banner)
        tpl, banner = rules.pick_template(answers(sex='female', health={'pregnant': True}), T)
        self.assertEqual(tpl.slug, 'walk-mobility')


def ex(id, pattern, prim, intensity='moderate', equipment=('none',), level=1, contra=(), reg=None, measure='reps'):
    return SimpleNamespace(id=id, pattern=pattern, primary_muscles=list(prim), secondary_muscles=[],
                           intensity=intensity, equipment=list(equipment), settings=['home', 'gym'], level=level,
                           contraindications=list(contra), regression_id=reg, retired=False, measure=measure,
                           default_reps=[10, 12], default_seconds=30 if measure == 'time' else None,
                           sec_per_rep=3.0, unilateral=False, name=id.replace('_', ' ').title(), met=4.0)


LIB = {e.id: e for e in [
    ex('arm_circles', 'warmup', ['front_delts'], 'light', measure='time'),
    ex('leg_swings', 'warmup', ['hip_flexors'], 'light', measure='time'),
    ex('cat_cow', 'mobility', ['lower_back'], 'light', ('mat',), measure='time'),
    ex('quad_stretch', 'stretch', ['quads'], 'light', measure='time'),
    ex('hamstring_stretch', 'stretch', ['hamstrings'], 'light', ('mat',), measure='time'),
    ex('box_squat', 'squat', ['quads', 'glutes'], 'moderate'),
    ex('band_squat', 'squat', ['quads', 'glutes'], 'heavy', ('band_tube',), contra=('knee',), reg='box_squat'),
    ex('jump_squat', 'squat', ['quads'], 'heavy', level=2, contra=('knee',)),
    ex('band_rdl', 'hinge', ['hamstrings', 'glutes'], 'heavy', ('band_tube',)),
    ex('glute_bridge', 'hinge', ['glutes'], 'light', ('mat',)),
    ex('band_chest_press', 'horizontal_push', ['chest'], 'heavy', ('band_tube', 'door_anchor')),
    ex('push_up', 'horizontal_push', ['chest'], 'heavy', contra=('wrist',)),
    ex('band_row', 'horizontal_pull', ['upper_back', 'lats'], 'heavy', ('band_tube', 'door_anchor')),
    ex('band_face_pull', 'horizontal_pull', ['rear_delts'], 'light', ('band_tube', 'door_anchor')),
    ex('band_overhead_press', 'vertical_push', ['front_delts'], 'moderate', ('band_tube',)),
    ex('dead_bug', 'core_anti_extension', ['core'], 'light', ('mat',)),
    ex('band_bicep_curl', 'isolation_upper', ['biceps'], 'light', ('band_tube',)),
]}


class BuilderTest(SimpleTestCase):
    def tpl(self, slug='full-body-home-bands'):
        d = dict(launch_templates())[slug]
        return SimpleNamespace(slug=slug, **d)

    def ctx(self, **kw):
        base = dict(equipment=['band_tube', 'door_anchor', 'mat'], setting='home', joints=[], experience='some',
                    goal='lean_muscle', minutes=30)
        base.update(kw)
        return Ctx(**base)

    def test_deterministic(self):
        a = build(self.tpl(), self.ctx(), LIB)
        b = build(self.tpl(), self.ctx(), dict(reversed(list(LIB.items()))))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_shape_and_rules(self):
        phases, report = build(self.tpl(), self.ctx(), LIB)
        self.assertEqual(report['violations'], [])
        mon = phases[0]['days']['0']
        kinds = [b['block'] for b in mon['blocks']]
        self.assertEqual(kinds[0], 'warmup')
        self.assertEqual(kinds[-1], 'cooldown')
        first_pair = mon['blocks'][1]['items']
        self.assertEqual(first_pair[0]['exercise'], 'band_squat')      # heavy first, priority list
        self.assertEqual(first_pair[1]['exercise'], 'band_face_pull')
        stretches = {i['exercise'] for i in mon['blocks'][-1]['items']}
        self.assertTrue(stretches <= {'quad_stretch', 'hamstring_stretch'})   # for the muscles trained

    def test_equipment_filter(self):
        ids = [c.id for c in candidates('squat', self.ctx(equipment=['mat']), LIB, 1)]
        self.assertEqual(ids, ['box_squat'])                             # no bands; the level-2 jump squat is too hard
        ids = [c.id for c in candidates('squat', self.ctx(equipment=['mat']), LIB, 2)]
        self.assertEqual(ids, ['jump_squat', 'box_squat'])

    def test_contraindication_follows_regression_chain(self):
        ids = [c.id for c in candidates('squat', self.ctx(joints=['knee']), LIB, 2)]
        self.assertEqual(ids, ['box_squat'])
        ids = [c.id for c in candidates('horizontal_push', self.ctx(equipment=['mat'], joints=['wrist']), LIB, 1)]
        self.assertEqual(ids, [])                                        # no safe regression: slot dropped

    def test_level_preference(self):
        ids = [c.id for c in candidates('squat', self.ctx(equipment=[]), LIB, 2)]
        self.assertEqual(ids[0], 'jump_squat')                           # level == user level first

    def test_time_fit_trims(self):
        phases, report = build(self.tpl(), self.ctx(minutes=15), LIB)
        self.assertEqual([v for v in report['violations'] if 'min is over' in v], [])

    def test_fat_loss_bias_uses_circuits(self):
        phases, _ = build(self.tpl(), self.ctx(goal='lose_fat'), LIB)
        self.assertNotIn('pair', [b['block'] for b in phases[0]['days']['0']['blocks']])

    def test_validate_catches_violations(self):
        bad = [{'name': 'W1', 'weeks': [1, 1], 'days': {'0': {'kind': 'session', 'name': 'x', 'blocks': [
            {'block': 'pair', 'rounds': 3, 'rest_after': 20, 'items': [{'exercise': 'band_bicep_curl'}, {'exercise': 'band_squat'}]},
            {'block': 'single', 'rounds': 3, 'rest_after': 90, 'items': [{'exercise': 'box_squat'}]},
            {'block': 'single', 'rounds': 3, 'rest_after': 90, 'items': [{'exercise': 'band_chest_press'}]},
        ]}}}]
        v = ' | '.join(validate(bad, LIB))
        self.assertIn('comes after an isolation move', v)
        self.assertIn('rest 20 s', v)
        self.assertIn('not within 20%', v)
        self.assertIn('needs both a squat and a hinge', v)
        two_heavy = [{'name': 'W1', 'weeks': [1, 1], 'days': {'0': {'kind': 'session', 'name': 'x', 'blocks': [
            {'block': 'single', 'rounds': 1, 'rest_after': 90, 'items': [{'exercise': 'band_squat'}]},
            {'block': 'single', 'rounds': 1, 'rest_after': 90, 'items': [{'exercise': 'band_rdl'}]}]}}}]
        self.assertIn('back to back', ' '.join(validate(two_heavy, LIB)))

    def test_every_launch_template_builds_cleanly(self):
        for slug, _ in launch_templates():
            setting = 'gym' if 'gym' in slug else 'home'
            phases, report = build(self.tpl(slug), self.ctx(setting=setting), LIB)
            self.assertEqual(report['violations'], [], slug)


class OnboardingApiTest(FitnessBase):
    today = date(2026, 12, 2)

    def post(self, body):
        return self.client.post('/board/api/fitness/onboarding/', json.dumps(body), content_type='application/json')

    def test_preview_then_confirm(self):
        r = self.post(AJWAD)
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        self.assertEqual(d['targets']['kcal'], 2350)
        self.assertEqual(d['targets']['protein_g'], 122)
        self.assertEqual(d['template']['slug'], 'full-body-home-bands')
        self.assertFalse(Program.objects.exists())                       # preview writes nothing
        r = self.post({**AJWAD, 'confirm': True})
        self.assertEqual(r.status_code, 200, r.content)
        p = FitnessProfile.objects.get(user=self.user)
        self.assertEqual(p.targets['kcal'], 2350)
        self.assertEqual(p.why, 'Feel strong for the next decade')
        self.assertEqual(p.times['workout'], '18:30')
        program = Program.objects.get(user=self.user)
        self.assertEqual(program.start_date, self.today)
        ov = self.client.get('/board/api/fitness/overview/').json()['data']
        self.assertEqual(ov['activity']['day']['kind'], 'session')        # Wednesday
        self.assertEqual({t['key'] for t in ov['trackers']}, {'water', 'protein', 'steps', 'weight', 'waist'})
        weight = next(t for t in ov['trackers'] if t['key'] == 'weight')
        self.assertEqual(weight['today'], 67.8)

    def test_reonboarding_keeps_history(self):
        self.post({**AJWAD, 'confirm': True})
        self.post({**AJWAD, 'days_per_week': 4, 'track_calories': True, 'confirm': True})
        p = FitnessProfile.objects.get(user=self.user)
        self.assertEqual(len(p.answers), 2)
        self.assertEqual(Program.objects.filter(user=self.user).count(), 1)
        self.assertIn('Upper', Program.objects.get(user=self.user).name)
        got = self.client.get('/board/api/fitness/onboarding/').json()['data']['answers']
        self.assertEqual(got['days_per_week'], 4)

    def test_bad_answers(self):
        r = self.post({**AJWAD, 'age': 9})
        self.assertEqual(r.status_code, 400)

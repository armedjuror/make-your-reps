from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from fitness.models import FitnessProfile, ProgramTemplate
from fitness.plans import PERSONAL_TEMPLATES
from fitness.setup import ensure_fitness, install_program

# Ajwad, 26 Nov 2026: 67.8 kg, 171 cm, 26, male, sitting + 3-4 days -> 2,350 kcal, 122 g protein.
# Phase 3's rule engine recomputes these from the onboarding answers.
AJWAD_TARGETS = {'kcal': 2350, 'protein_g': 122, 'water_ml': 2400, 'steps': 7000, 'sleep_h': [7, 8]}


class Command(BaseCommand):
    help = 'Install a hand-written program (default: Ajwad\'s one-month band plan) for one user.'

    def add_arguments(self, parser):
        parser.add_argument('--user', type=int, required=True, help='User id')
        parser.add_argument('--start', default='2026-12-01', help='Program start date (YYYY-MM-DD)')
        parser.add_argument('--template', default='ajwad-bands-month', choices=sorted(PERSONAL_TEMPLATES))
        parser.add_argument('--track-calories', action='store_true')

    def handle(self, user, start, template, track_calories, **opts):
        u = User.objects.filter(id=user).first()
        if not u:
            raise CommandError(f'No user {user}')
        try:
            start_date = date.fromisoformat(start)
        except ValueError:
            raise CommandError('--start must be YYYY-MM-DD')
        spec = dict(PERSONAL_TEMPLATES[template])
        phases = spec.pop('phases')()
        tpl, _ = ProgramTemplate.objects.update_or_create(
            slug=template, defaults={**spec, 'phases': phases, 'is_personal': True})

        profile, _ = FitnessProfile.objects.get_or_create(user=u)
        if not profile.targets:
            profile.targets = AJWAD_TARGETS
        profile.track_calories = track_calories
        profile.times = {'weigh_in_day': 0, **(profile.times or {})}
        profile.save()

        health, activity, trackers = ensure_fitness(u.id, profile.targets, track_calories)
        program = install_program(activity, tpl, start_date)
        self.stdout.write(self.style.SUCCESS(
            f'{u}: Health habit #{health.id}, Activity habit #{activity.id}, '
            f'{len([t for t in trackers.values() if t])} trackers, program "{program.name}" from {start_date}'))

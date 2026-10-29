import datetime
from django.db import migrations

VERSION = '1.7.0'


def seed(apps, schema_editor):
    ReleaseLog = apps.get_model('main', 'ReleaseLog')
    ReleaseLog.objects.get_or_create(
        version=VERSION,
        defaults=dict(
            title='Themes with personality & a smarter timeline',
            description=(
                '- Nine themes, each with its own personality: Ink, Terminal, Tech, Aurora, Sensei, Coach, Garden, Orbit and Quest\n'
                '- Every theme has its own default font, greeting voice, timeline wording and completion effect (change the font any time in Settings)\n'
                '- One-line greeting that reads your day: habits, journal, tasks, focus, sleep, achievements and perfect scores\n'
                '- Timeline shows one overdue task by default with "Show all", plus task-group badges and a group filter\n'
                '- Reschedule overdue tasks to any date you pick, not just tomorrow\n'
                '- Habits: edit the reminder time, see it in the habit modal, and see accountability partner names\n'
                '- Today\'s timeline updates automatically when a habit\'s reminder time or schedule changes\n'
                '- Better mobile layout for the greeting'
            ),
            release_type='major',
            released_at=datetime.date(2026, 10, 29),
            is_public=True,
        ),
    )


def unseed(apps, schema_editor):
    apps.get_model('main', 'ReleaseLog').objects.filter(version=VERSION).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0008_extension_uninstall_feedback'),
    ]

    operations = [
        migrations.RunPython(seed, reverse_code=unseed),
    ]

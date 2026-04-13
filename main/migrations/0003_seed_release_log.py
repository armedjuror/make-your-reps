import datetime
from django.db import migrations


def seed_releases(apps, schema_editor):
    ReleaseLog = apps.get_model('main', 'ReleaseLog')
    ReleaseLog.objects.bulk_create([
        ReleaseLog(
            version='0.0.1',
            title='Initial Launch',
            description=(
                '- Habit tracking with streak support and frequency scheduling\n'
                '- Todo list with soft-delete\n'
                '- Daily journal and sleep hours logging\n'
            ),
            release_type='major',
            released_at=datetime.date(2025, 7, 18),
            is_public=True,
        ),
        ReleaseLog(
            version='1.0.0',
            title='Dashboard Revamp',
            description=(
                '- Full SPA dashboard with pane-based navigation (Home, Todos, Trackers, Journals)\n'
                '- Pomodoro timer with configurable focus/break cycles\n'
                '- Timeline / activity feed\n'
                '- Reading list / bookmarks\n'
                '- Sleep & focus minute tracker\n'
                '- Routine entries (workday & holiday schedules)\n'
                '- Task groups for todo organisation\n'
                '- Configurable search engine (Google, DuckDuckGo, Bing, YouTube, ChatGPT, Claude)\n'
                '- Mobile-responsive hamburger menu\n'
                '- Light/dark theme toggle\n'
                '- Settings modal with font, clock format, and sound preferences'
            ),
            release_type='major',
            released_at=datetime.date(2026, 3, 26),
            is_public=True,
        ),
    ])


def unseed_releases(apps, schema_editor):
    ReleaseLog = apps.get_model('main', 'ReleaseLog')
    ReleaseLog.objects.filter(version__in=['0.0.1', '1.0.0']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0002_add_release_log'),
    ]

    operations = [
        migrations.RunPython(seed_releases, reverse_code=unseed_releases),
    ]
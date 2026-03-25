# Generated migration for dashboard revamp

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import re
from datetime import time


def populate_search_engines(apps, schema_editor):
    """Pre-populate the SearchEngine master list."""
    SearchEngine = apps.get_model('board', 'SearchEngine')
    engines = [
        {
            'name': 'Google',
            'key': 'google',
            'url_template': 'https://www.google.com/search?q={query}',
            'icon': 'fab fa-google',
        },
        {
            'name': 'DuckDuckGo',
            'key': 'duckduckgo',
            'url_template': 'https://duckduckgo.com/?q={query}',
            'icon': 'fas fa-duck',  # FA6 doesn't have duck, we'll use a search icon
        },
        {
            'name': 'Bing',
            'key': 'bing',
            'url_template': 'https://www.bing.com/search?q={query}',
            'icon': 'fab fa-microsoft',
        },
        {
            'name': 'YouTube',
            'key': 'youtube',
            'url_template': 'https://www.youtube.com/results?search_query={query}',
            'icon': 'fab fa-youtube',
        },
        {
            'name': 'ChatGPT',
            'key': 'chatgpt',
            'url_template': 'https://chatgpt.com/?q={query}',
            'icon': 'fas fa-robot',
        },
        {
            'name': 'Claude',
            'key': 'claude',
            'url_template': 'https://claude.ai/new?q={query}',
            'icon': 'fas fa-brain',
        },
    ]
    for engine in engines:
        SearchEngine.objects.get_or_create(key=engine['key'], defaults=engine)


def migrate_routines_to_entries(apps, schema_editor):
    """Parse existing text routines in UserDetail into RoutineEntry rows."""
    UserDetail = apps.get_model('board', 'UserDetail')
    RoutineEntry = apps.get_model('board', 'RoutineEntry')

    time_pattern = re.compile(r'^(\d{1,2})[.:]+(\d{2})\s*(AM|PM|am|pm)?\s*[-–—]\s*(.+)$')

    for ud in UserDetail.objects.all():
        for routine_type, text_field in [('workday', ud.workday_routine), ('holiday', ud.holiday_routine)]:
            if not text_field or not text_field.strip():
                continue
            lines = [line.strip() for line in text_field.split('\n') if line.strip()]
            for line in lines:
                match = time_pattern.match(line)
                if match:
                    hour = int(match.group(1))
                    minute = int(match.group(2))
                    ampm = match.group(3)
                    title = match.group(4).strip()

                    if ampm and ampm.upper() == 'PM' and hour != 12:
                        hour += 12
                    elif ampm and ampm.upper() == 'AM' and hour == 12:
                        hour = 0

                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        entry_time = time(hour, minute)
                        RoutineEntry.objects.get_or_create(
                            user_id=ud.user_id,
                            routine_type=routine_type,
                            time=entry_time,
                            title=title,
                            defaults={'is_active': True}
                        )
                else:
                    # Fallback: store as 00:00 entry if time can't be parsed
                    RoutineEntry.objects.get_or_create(
                        user_id=ud.user_id,
                        routine_type=routine_type,
                        time=time(0, 0),
                        title=line,
                        defaults={'is_active': True}
                    )


def reverse_migrate_routines(apps, schema_editor):
    """Reverse: do nothing, keep text fields intact."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('board', '0002_alter_habitlog_id'),
    ]

    operations = [
        # ── Task: add deadline ──
        migrations.AddField(
            model_name='task',
            name='deadline',
            field=models.DateTimeField(blank=True, null=True),
        ),

        # ── UserDetail: add new preference fields ──
        migrations.AddField(
            model_name='userdetail',
            name='default_search_engine',
            field=models.CharField(
                choices=[
                    ('google', 'Google'), ('duckduckgo', 'Duckduckgo'),
                    ('bing', 'Bing'), ('youtube', 'Youtube'),
                    ('chatgpt', 'Chatgpt'), ('claude', 'Claude'),
                ],
                default='google', max_length=32
            ),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='pomodoro_focus',
            field=models.IntegerField(default=25),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='pomodoro_break',
            field=models.IntegerField(default=5),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='pomodoro_long_break',
            field=models.IntegerField(default=15),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='pomodoro_cycles',
            field=models.IntegerField(default=4),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='font_family',
            field=models.CharField(default='Montserrat', max_length=64),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='sound_pomodoro',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='sound_notifications',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='sleep_time',
            field=models.TimeField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='clock_format',
            field=models.CharField(
                choices=[('12h', '12H'), ('24h', '24H')],
                default='12h', max_length=4
            ),
        ),

        # ── RoutineEntry ──
        migrations.CreateModel(
            name='RoutineEntry',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('routine_type', models.CharField(
                    choices=[('workday', 'Workday'), ('holiday', 'Holiday')],
                    max_length=10
                )),
                ('title', models.CharField(max_length=255)),
                ('time', models.TimeField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='routine_entries',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'ordering': ['time', 'id'],
                'unique_together': {('user', 'routine_type', 'time', 'title')},
            },
        ),

        # ── ReadingListItem ──
        migrations.CreateModel(
            name='ReadingListItem',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('url', models.URLField()),
                ('icon', models.URLField(blank=True, null=True)),
                ('is_featured', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reading_list',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),

        # ── TimelineEvent ──
        migrations.CreateModel(
            name='TimelineEvent',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('timestamp', models.DateTimeField()),
                ('event_type', models.CharField(
                    choices=[
                        ('habit', 'Habit'), ('todo', 'Todo'), ('routine', 'Routine'),
                        ('sleep_tracker', 'Sleep Tracker'), ('journal', 'Journal'),
                        ('text', 'Text'), ('meeting', 'Meeting'),
                    ],
                    max_length=16
                )),
                ('event', models.TextField()),
                ('reference', models.JSONField(blank=True, null=True)),
                ('action', models.JSONField(blank=True, null=True)),
                ('action_response', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='timeline_events',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
        migrations.AddIndex(
            model_name='timelineevent',
            index=models.Index(fields=['user', 'timestamp'], name='board_timel_user_id_idx'),
        ),
        migrations.AddIndex(
            model_name='timelineevent',
            index=models.Index(fields=['user', 'event_type', 'timestamp'], name='board_timel_user_ty_idx'),
        ),

        # ── SearchEngine ──
        migrations.CreateModel(
            name='SearchEngine',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=64)),
                ('key', models.CharField(max_length=32, unique=True)),
                ('url_template', models.CharField(max_length=500)),
                ('icon', models.CharField(max_length=64)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),

        # ── Data migrations ──
        migrations.RunPython(populate_search_engines, migrations.RunPython.noop),
        migrations.RunPython(migrate_routines_to_entries, reverse_migrate_routines),
    ]
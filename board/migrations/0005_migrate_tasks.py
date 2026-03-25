# Migration: Add TaskGroup model and Task.group FK

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_default_groups(apps, schema_editor):
    """Create a 'General' group for every existing user who has tasks."""
    Task = apps.get_model('board', 'Task')
    TaskGroup = apps.get_model('board', 'TaskGroup')

    user_ids = Task.objects.filter(is_deleted=False).values_list('user_id', flat=True).distinct()
    for user_id in user_ids:
        group, _ = TaskGroup.objects.get_or_create(
            user_id=user_id,
            name='General',
            defaults={'is_active': True}
        )
        # Assign all existing tasks to General
        Task.objects.filter(user_id=user_id, group__isnull=True).update(group=group)


def reverse_default_groups(apps, schema_editor):
    """Reverse: set all task groups back to null."""
    Task = apps.get_model('board', 'Task')
    Task.objects.all().update(group=None)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('board', '0004_rename_board_timel_user_id_idx_board_timel_user_id_30b189_idx_and_more'),  # Depends on the revamp migration
    ]

    operations = [
        # ── Create TaskGroup ──
        migrations.CreateModel(
            name='TaskGroup',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=128)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_groups',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['name'],
                'unique_together': {('user', 'name')},
            },
        ),

        # ── Add group FK to Task ──
        migrations.AddField(
            model_name='task',
            name='group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='tasks',
                to='board.taskgroup',
            ),
        ),

        # ── Data migration: create default groups ──
        migrations.RunPython(create_default_groups, reverse_default_groups),
    ]
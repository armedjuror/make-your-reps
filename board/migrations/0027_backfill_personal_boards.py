"""
Board migration, step 1 and 2: one personal board per existing user, then
point every Habit, Task and Metric at its creator's personal board.
``user_id`` stays as the creator.
"""
from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Board = apps.get_model('squads', 'Board')
    existing = set(Board.objects.filter(type='personal').values_list('owner_id', flat=True))
    Board.objects.bulk_create([
        Board(type='personal', owner_id=uid, timezone=settings.TIME_ZONE, settings={})
        for uid in User.objects.exclude(id__in=existing).values_list('id', flat=True)
    ], batch_size=1000)
    board_of = dict(Board.objects.filter(type='personal').values_list('owner_id', 'id'))
    for model_name in ('Habit', 'Task', 'Metric'):
        Model = apps.get_model('board', model_name)
        for owner_id, board_id in board_of.items():
            Model.objects.filter(user_id=owner_id, board__isnull=True).update(board_id=board_id)


def backwards(apps, schema_editor):
    for model_name in ('Habit', 'Task', 'Metric'):
        apps.get_model('board', model_name).objects.update(board=None)


class Migration(migrations.Migration):
    dependencies = [
        ('board', '0026_squads_board_fields'),
        ('squads', '0001_initial'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]

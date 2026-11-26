"""Board migration, step 3: every shareable item now has a board."""
import django.db.models.deletion
from django.db import migrations, models


def _fk():
    return models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='squads.board')


class Migration(migrations.Migration):
    dependencies = [
        ('board', '0027_backfill_personal_boards'),
    ]

    operations = [
        migrations.AlterField(model_name='habit', name='board', field=_fk()),
        migrations.AlterField(model_name='task', name='board', field=_fk()),
        migrations.AlterField(model_name='metric', name='board', field=_fk()),
    ]

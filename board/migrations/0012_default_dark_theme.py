from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('board', '0011_invite_tokens'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userdetail',
            name='default_theme',
            field=models.CharField(
                choices=[('dark', 'Dark'), ('light', 'Light')],
                default='dark',
                max_length=16,
            ),
        ),
    ]

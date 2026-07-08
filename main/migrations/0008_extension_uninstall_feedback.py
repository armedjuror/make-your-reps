from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0007_emailpreference_last_reengagement_sent'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExtensionUninstallFeedback',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('reason', models.CharField(
                    blank=True,
                    choices=[
                        ('not_useful',  "Wasn't useful enough"),
                        ('too_slow',    'Made browser too slow'),
                        ('privacy',     'Privacy concerns'),
                        ('accidental',  'Installed by accident'),
                        ('switching',   'Switching to another tool'),
                        ('other',       'Other'),
                    ],
                    max_length=20,
                )),
                ('comment', models.TextField(blank=True)),
                ('extension_version', models.CharField(blank=True, max_length=16)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-submitted_at'],
            },
        ),
    ]

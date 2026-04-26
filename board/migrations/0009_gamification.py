from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('board', '0008_remove_accountabilitypartner_is_active_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add gamification fields to UserDetail
        migrations.AddField(
            model_name='userdetail',
            name='total_points',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='level',
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='current_streak',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='longest_streak',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='userdetail',
            name='last_active_date',
            field=models.DateField(blank=True, default=None, null=True),
        ),
        # Achievement model
        migrations.CreateModel(
            name='Achievement',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('key', models.CharField(max_length=64, unique=True)),
                ('name', models.CharField(max_length=128)),
                ('description', models.CharField(max_length=255)),
                ('icon', models.CharField(max_length=64)),
                ('category', models.CharField(default='general', max_length=32)),
            ],
            options={
                'ordering': ['category', 'name'],
            },
        ),
        # UserAchievement model
        migrations.CreateModel(
            name='UserAchievement',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('unlocked_at', models.DateTimeField(auto_now_add=True)),
                ('achievement', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='board.achievement')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='achievements', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-unlocked_at'],
                'unique_together': {('user', 'achievement')},
            },
        ),
    ]

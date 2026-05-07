from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('board', '0016_push_notifications'),
    ]

    operations = [
        migrations.DeleteModel(
            name='PushSubscription',
        ),
        migrations.RemoveField(
            model_name='timelineevent',
            name='push_notified',
        ),
    ]

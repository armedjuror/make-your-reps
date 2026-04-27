from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0006_announcementlog_audience_specific'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailpreference',
            name='last_reengagement_sent',
            field=models.DateField(blank=True, default=None, null=True),
        ),
    ]
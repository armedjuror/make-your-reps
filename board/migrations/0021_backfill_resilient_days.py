from datetime import datetime, time, timedelta

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    """
    * Every user gets a Sleep metric and a default journal linked to it.
    * DailyData.journal text moves into the default journal, one entry per date.
    * The current streak becomes 'legacy' DaySummary rows, so nobody's streak
      resets the day the new engine starts counting from summaries.
    The old columns are kept; the journal pane and the sleep card keep working.
    """
    User = apps.get_model('auth', 'User')
    UserDetail = apps.get_model('board', 'UserDetail')
    DailyData = apps.get_model('board', 'DailyData')
    Metric = apps.get_model('board', 'Metric')
    MetricEntry = apps.get_model('board', 'MetricEntry')
    Journal = apps.get_model('board', 'Journal')
    JournalEntry = apps.get_model('board', 'JournalEntry')
    DaySummary = apps.get_model('board', 'DaySummary')

    today = timezone.localdate()
    for user in User.objects.all().iterator():
        sleep = Metric.objects.create(
            user=user, name='Sleep', unit='h', kind='single', direction='at_least',
            quick_steps=[], fields=[], is_system=True,
        )
        journal = Journal.objects.create(user=user, name='Journal', metric=sleep, is_default=True)
        entries, sleeps = [], []
        for d in DailyData.objects.filter(user=user).iterator():
            if d.journal and d.journal.strip():
                at = timezone.make_aware(datetime.combine(d.date, time(21, 0)))
                entries.append(JournalEntry(journal=journal, date=d.date, at=at, text=d.journal.strip()))
            if d.sleep_hours is not None:
                at = timezone.make_aware(datetime.combine(d.date, time(12, 0)))
                sleeps.append(MetricEntry(metric=sleep, date=d.date, at=at, value=d.sleep_hours))
        JournalEntry.objects.bulk_create(entries)
        MetricEntry.objects.bulk_create(sleeps)

        detail = UserDetail.objects.filter(user=user).first()
        if detail and detail.current_streak > 0 and detail.last_active_date:
            # Only a streak that is still alive (active today or yesterday) is carried over.
            if detail.last_active_date >= today - timedelta(days=1):
                end = min(detail.last_active_date, today - timedelta(days=1))
                for i in range(detail.current_streak):
                    day = detail.last_active_date - timedelta(days=i)
                    if day <= end:
                        DaySummary.objects.get_or_create(
                            user=user, date=day,
                            defaults={'mode': 'normal', 'required': 0, 'required_done': 0, 'outcome': 'legacy'},
                        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('board', '0020_resilient_days')]
    operations = [migrations.RunPython(backfill, noop)]

from django.db import migrations


def forwards(apps, schema_editor):
    """Entries logged with answers but no note get their journal entry, as new ones now do."""
    MetricEntry = apps.get_model('board', 'MetricEntry')
    Journal = apps.get_model('board', 'Journal')
    JournalEntry = apps.get_model('board', 'JournalEntry')
    linked = set(JournalEntry.objects.exclude(metric_entry=None).values_list('metric_entry_id', flat=True))
    for e in MetricEntry.objects.select_related('metric').exclude(data={}):
        if e.id in linked or not {k for k in (e.data or {}) if k != 'previous'}:
            continue
        m = e.metric
        journal = Journal.objects.filter(metric=m).first() or Journal.objects.create(
            user_id=m.user_id, name=m.name, metric=m, is_private=m.is_private)
        JournalEntry.objects.create(journal=journal, date=e.date, at=e.at, text='', metric_entry=e)


class Migration(migrations.Migration):
    dependencies = [('board', '0022_metric_remind_at')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]

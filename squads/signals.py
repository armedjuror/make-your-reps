"""Signal handlers: personal boards, the contribution ledger, account deletion."""
import logging

from django.contrib.auth.models import User
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from board.models import HabitLog, MetricEntry

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_personal_board(sender, instance, created, **kwargs):
    if created:
        from squads.models import Board
        Board.personal_for(instance.id)


def _safe(fn, *args, **kwargs):
    # The ledger must never break a personal log
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.exception('Squad ledger update failed')


@receiver(post_save, sender=HabitLog)
def habit_log_saved(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return
    from squads import ledger
    _safe(ledger.on_habit_log, instance)


@receiver(post_delete, sender=HabitLog)
def habit_log_deleted(sender, instance, **kwargs):
    from squads import ledger
    _safe(ledger.on_habit_log, instance, deleted=True)


@receiver(post_save, sender=MetricEntry)
def metric_entry_saved(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return
    from squads import ledger
    _safe(ledger.on_metric_entry, instance)


@receiver(post_delete, sender=MetricEntry)
def metric_entry_deleted(sender, instance, **kwargs):
    from squads import ledger
    _safe(ledger.on_metric_entry, instance, deleted=True)


@receiver(pre_delete, sender=User)
def anonymise_contributions(sender, instance, **kwargs):
    """Account deletion: contributions stay as 'Former member' so squad totals stay correct."""
    from squads.safety import anonymise_user
    anonymise_user(instance)

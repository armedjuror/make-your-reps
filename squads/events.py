"""Instrumentation: every squad event lands in the Event table from day one."""
import logging

logger = logging.getLogger(__name__)


def track(name, user=None, **props):
    from squads.models import Event
    try:
        user_id = getattr(user, 'id', user)
        Event.objects.create(user_id=user_id, name=name, props=props)
    except Exception:   # instrumentation never breaks the request
        logger.exception('Event %s not recorded', name)

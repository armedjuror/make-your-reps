"""
Feature flags, one per build track. Defaults come from settings.FEATURE_FLAGS;
a Config row ``flag_<name>`` (value 'on' / 'off') overrides at runtime.
"""
from functools import wraps

from django.conf import settings
from django.http import JsonResponse

FLAGS = (
    'squads',          # squads core: create, invite, join, roles
    'squad_items',     # habits, todos, trackers on squads; linking
    'otp_login',       # email OTP sign-up and login
    'notifications',   # web push, email fallback, caps
    'streaks',         # squad streak, heatmap, nudges, away
    'leaderboard',     # points, goals, MVP
    'focus',           # scheduled focus sessions
    'challenges',      # challenges and Discover
    'share',           # recap image, completion card, public pages
    'plan_limits',     # PLAN_LIMITS enforcement
    'safety',          # block, report, export
)


def enabled(name):
    try:
        from main.models import Config
        row = Config.objects.filter(key=f'flag_{name}').first()
        if row is not None:
            return row.value.strip().lower() in ('1', 'on', 'true', 'yes')
    except Exception:
        pass
    return bool(getattr(settings, 'FEATURE_FLAGS', {}).get(name, True))


def all_flags():
    return {name: enabled(name) for name in FLAGS}


def flag_required(name):
    """Decorator for function views and APIView methods."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not enabled(name):
                return JsonResponse({'status': 'failed', 'error': 'This feature is not available yet'}, status=404)
            return fn(*args, **kwargs)
        return wrapper
    return deco

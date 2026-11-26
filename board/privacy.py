"""
Privacy mode. A PIN hides private habits, metrics and journals from anyone at
the screen. It is not encryption: anyone with the account or the database can
read the data. Enforcement is on the server, so the UI only follows it.

Every list, timeline, score, Progress, achievement and export query excludes
private rows unless ``session['private_until']`` is in the future. When
locked, nothing hints at private items: they are absent, not placeholders.
"""
import random
import time

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.mail import send_mail

MAX_WRONG_PINS = 5
LOCKOUT_SECONDS = 15 * 60
OTP_SECONDS = 15 * 60


def is_unlocked(request):
    return float(request.session.get('private_until') or 0) > time.time()


def include_private(request):
    """True when private rows may be shown on this request."""
    return is_unlocked(request)


def valid_pin(pin):
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 6


def set_pin(detail, pin):
    detail.private_pin_hash = make_password(pin)
    detail.save(update_fields=['private_pin_hash'])


def _fail_key(user_id):
    return f'pin-fail:{user_id}'


def _lock_key(user_id):
    return f'pin-lock:{user_id}'


def locked_out_for(user_id):
    """Seconds left on a PIN lockout, or 0."""
    until = cache.get(_lock_key(user_id))
    return max(0, int(until - time.time())) if until else 0


def try_unlock(request, detail, pin):
    """Returns (ok, error, retry_after_seconds)."""
    user_id = detail.user_id
    if not detail.private_pin_hash:
        return False, 'no_pin', 0
    wait = locked_out_for(user_id)
    if wait:
        return False, 'locked_out', wait
    if not valid_pin(pin) or not check_password(pin, detail.private_pin_hash):
        fails = cache.get(_fail_key(user_id), 0) + 1
        if fails >= MAX_WRONG_PINS:
            cache.set(_lock_key(user_id), time.time() + LOCKOUT_SECONDS, LOCKOUT_SECONDS)
            cache.delete(_fail_key(user_id))
            return False, 'locked_out', LOCKOUT_SECONDS
        cache.set(_fail_key(user_id), fails, LOCKOUT_SECONDS)
        return False, 'wrong_pin', 0
    cache.delete(_fail_key(user_id))
    request.session['private_until'] = time.time() + detail.private_unlock_minutes * 60
    return True, None, 0


def lock(request):
    request.session.pop('private_until', None)


# ── Forgotten PIN: email one-time code ─────────────────────

def _otp_key(user_id):
    return f'pin-otp:{user_id}'


def send_reset_code(user):
    code = f'{random.SystemRandom().randrange(10**6):06d}'
    cache.set(_otp_key(user.id), make_password(code), OTP_SECONDS)
    if user.email:
        send_mail(
            'Your Make Your Reps privacy PIN reset code',
            f'Your code is {code}. It expires in 15 minutes. If you did not ask for it, ignore this email.',
            None, [user.email], fail_silently=True,
        )
    return bool(user.email)


def check_reset_code(user_id, code):
    hashed = cache.get(_otp_key(user_id))
    if not hashed or not check_password(str(code), hashed):
        return False
    cache.delete(_otp_key(user_id))
    return True

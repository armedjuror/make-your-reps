"""
Email OTP sign-up and login (web, extension and app), alongside Google.

* 6-digit code by email (Resend SMTP), stored as an HMAC, valid 10 minutes,
  at most 5 attempts per code, rate-limited per email and per IP.
* Google and OTP logins for the same email resolve to the same account.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.utils import timezone

from main.models import EmailOTP

BACKEND = 'django.contrib.auth.backends.ModelBackend'


class OTPError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _hash(email, code):
    key = (settings.SECRET_KEY or 'dev').encode()
    return hmac.new(key, f'{email}:{code}'.encode(), hashlib.sha256).hexdigest()


def normalise(email):
    email = (email or '').strip().lower()
    try:
        validate_email(email)
    except Exception:
        raise OTPError('Enter a valid email address')
    return email


def request_code(email, ip=None, now=None):
    now = now or timezone.now()
    email = normalise(email)
    hour_ago = now - timedelta(hours=1)
    if EmailOTP.objects.filter(email=email, created_at__gte=hour_ago).count() >= settings.OTP_PER_EMAIL_PER_HOUR:
        raise OTPError('Too many codes for this email. Try again in an hour.', 429)
    if ip and EmailOTP.objects.filter(ip=ip, created_at__gte=hour_ago).count() >= settings.OTP_PER_IP_PER_HOUR:
        raise OTPError('Too many requests. Try again later.', 429)
    last = EmailOTP.objects.filter(email=email).first()
    if last and (now - last.created_at).total_seconds() < 30:
        raise OTPError('A code was just sent. Wait 30 seconds before asking again.', 429)
    code = f'{secrets.randbelow(1_000_000):06d}'
    EmailOTP.objects.filter(email=email, used_at__isnull=True).update(used_at=now)   # one live code at a time
    EmailOTP.objects.create(email=email, code_hash=_hash(email, code), ip=ip,
                            expires_at=now + timedelta(minutes=settings.OTP_TTL_MINUTES))
    _send(email, code)
    return email


def _send(email, code):
    subject = f'{code} is your makeyourreps code'
    text = f'Your makeyourreps code is {code}. It expires in {settings.OTP_TTL_MINUTES} minutes.'
    html = (f'<div style="font-family:Montserrat,Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px">'
            f'<p>Your makeyourreps login code:</p>'
            f'<p style="font-size:32px;letter-spacing:8px;font-weight:700">{code}</p>'
            f'<p style="color:#888;font-size:13px">It expires in {settings.OTP_TTL_MINUTES} minutes. '
            f'If you didn\'t ask for it, ignore this email.</p></div>')
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [email])
    msg.attach_alternative(html, 'text/html')
    msg.send(fail_silently=False)


def verify_code(email, code, now=None):
    """Returns (user, created). Raises OTPError on a wrong, used or expired code."""
    now = now or timezone.now()
    email = normalise(email)
    code = (code or '').strip()
    otp = EmailOTP.objects.filter(email=email, used_at__isnull=True).first()
    if otp is None or otp.expires_at <= now:
        raise OTPError('That code has expired. Ask for a new one.')
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise OTPError('Too many wrong tries. Ask for a new code.', 429)
    if not hmac.compare_digest(otp.code_hash, _hash(email, code)):
        EmailOTP.objects.filter(pk=otp.pk).update(attempts=otp.attempts + 1)
        left = settings.OTP_MAX_ATTEMPTS - otp.attempts - 1
        raise OTPError(f'Wrong code. {left} tries left.' if left > 0 else 'Too many wrong tries. Ask for a new code.')
    EmailOTP.objects.filter(pk=otp.pk).update(used_at=now)
    return get_or_create_user(email)


def get_or_create_user(email):
    """One account per email, whichever way the person signs in."""
    from allauth.account.models import EmailAddress
    addr = EmailAddress.objects.filter(email__iexact=email).select_related('user').first()
    user = addr.user if addr else User.objects.filter(email__iexact=email).order_by('id').first()
    created = False
    if user is None:
        base = email.split('@')[0][:120] or 'user'
        username, n = base, 1
        while User.objects.filter(username=username).exists():
            n += 1
            username = f'{base}{n}'
        user = User.objects.create_user(username=username, email=email)
        user.set_unusable_password()
        user.save()
        created = True
    # A verified address lets a later Google login with the same email land on this account
    EmailAddress.objects.update_or_create(user=user, email=email,
                                          defaults={'verified': True, 'primary': not addr or addr.primary})
    return user, created


def sign_in(request, user, created):
    if created:
        from allauth.account.signals import user_signed_up
        user_signed_up.send(sender=User, request=request, user=user)   # same onboarding as a Google sign-up
    login(request, user, backend=BACKEND)

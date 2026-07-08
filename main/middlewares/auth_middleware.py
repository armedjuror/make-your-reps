import json
from datetime import datetime, timedelta

from django.utils.deprecation import MiddlewareMixin

from main.models import LoginActivity
from main.utils import get_auth_token, RefreshToken, AccessToken, get_client_ip


class BearerCSRFExemptMiddleware:
    """
    Skip CSRF enforcement for requests authenticated via Bearer token.
    Bearer token auth is not CSRF-vulnerable — an attacker on another origin
    cannot read the user's token, so they cannot include it in a forged request.
    Web/session-based requests (no Authorization header) still go through
    normal CSRF validation.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get('HTTP_AUTHORIZATION', '').startswith('Bearer '):
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)


class AuthMiddleware(MiddlewareMixin):
    """
    Middleware to handle auth token cookies and validation
    """
    def process_request(self, request):
        if '/accounts/google/login/' in request.path:
            request.session['client_type'] = request.GET.get('client_type')

        if request.user.is_authenticated:
            request.session['user_id'] = request.user.id
        else:
            payload, token_string = get_auth_token(request)
            if payload is None:
                return
            if payload.get('type') == 'refresh':
                user, token_obj = RefreshToken.validate_token(token_string)
                if user:
                    try:
                        raw_token, token_hash = RefreshToken.generate_raw_token()
                        token_obj.token_hash = token_hash
                        token_obj.expires_at = datetime.now() + timedelta(days=30)
                        token_obj.save()
                        access_token = AccessToken.generate(user)
                        LoginActivity.objects.create(
                            user_id=user.id,
                            auth_token=token_obj,
                            timestamp=datetime.now(),
                            ip_address=get_client_ip(request),
                            user_agent=request.META['HTTP_USER_AGENT'],
                            action='token_refresh',
                            status='success',
                        )
                        request.session['access_token'] = access_token
                        request.session['refresh_token'] = raw_token
                        request.session['user_id'] = user.id
                    except Exception as e:
                        LoginActivity.objects.create(
                            user_id=user.id,
                            auth_token=token_obj,
                            timestamp=datetime.now(),
                            ip_address=get_client_ip(request),
                            user_agent=request.META['HTTP_USER_AGENT'],
                            action='token_refresh',
                            status='failed',
                        )
                        raise e
                else:
                    return
            elif payload.get('type') == 'access':
                now = datetime.now()
                if now <= payload.get('exp'):
                    return
                request.session['user_id'] = payload.get('sub')


    def process_response(self, request, response):
        """
        Process response to set auth token cookie if needed
        """
        # Check if we need to set auth token cookie
        if request.user.is_authenticated:
            refresh_token = request.session.get('refresh_token')
            if refresh_token:
                response.set_cookie(
                    'myrt',
                    refresh_token,
                    max_age=30 * 24 * 60 * 60,  # 30 days
                    httponly=True,
                    secure=request.is_secure(),
                    samesite='Strict'
                )
            elif request.session.get('client_type') == 'extension' and not request.COOKIES.get('myrt'):
                try:
                    jwt_token, _ = RefreshToken.generate_token(request.user, request)
                    response.set_cookie(
                        'myrt',
                        jwt_token,
                        max_age=30 * 24 * 60 * 60,  # 30 days
                        httponly=True,
                        secure=request.is_secure(),
                        samesite='Strict'
                    )
                    request.session.pop('client_type', None)
                except Exception:
                    pass
            if request.session.get('access_token'):
                del request.session['access_token']
            if request.session.get('refresh_token'):
                del request.session['refresh_token']
        return response
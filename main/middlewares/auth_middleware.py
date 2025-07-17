import json
from datetime import datetime, timedelta

from django.utils.deprecation import MiddlewareMixin

from main.models import LoginActivity
from main.utils import get_auth_token, RefreshToken, AccessToken, get_client_ip


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
            if request.session.get('access_token'):
                del request.session['access_token']
            if request.session.get('refresh_token'):
                del request.session['refresh_token']
        return response
from datetime import timedelta, datetime

import jwt
from allauth.account.signals import user_logged_in, user_signed_up
from django.contrib.auth import user_logged_out

from django.dispatch import receiver
from django.http import JsonResponse

from main.models import UserAuthToken, LoginActivity
from main.utils import get_auth_token, get_client_ip, AccessToken, RefreshToken


@receiver(user_signed_up)
@receiver(user_logged_in)
def handle_user_login(sender, request, user, **kwargs):
    client_type = request.session.get('client_type')
    if client_type == 'api':
        token_string, token_obj = RefreshToken.generate_token(
            user,
            request,
        )
        access_token = AccessToken.generate(user)
        request.session['refresh_token'] = token_string
        request.session['access_token'] = access_token
        request.session['user_id'] = user.id
    else:
        token_string, token_obj, response = None, None, None

    # Record login activity
    LoginActivity.objects.create(
        user=user,
        auth_token=token_obj,
        action='login',
        status='success',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )


@receiver(user_logged_out)
def handle_user_logout(sender, request, user, **kwargs):
    payload, token_string = get_auth_token(request)
    if payload:
        user_obj, auth_token = RefreshToken.validate_token(token_string)
        auth_token.is_active = False
        auth_token.save()
    else:
        auth_token = None
    LoginActivity.objects.create(
        user=user,
        auth_token=auth_token,
        action='logout',
        status='success',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )


from datetime import timedelta, datetime

import jwt
from allauth.account.signals import user_logged_in, user_signed_up
from django.contrib.auth import user_logged_out

from django.dispatch import receiver
from django.http import JsonResponse

from board.models import Habit, Task, UserDetail
from main.models import UserAuthToken, LoginActivity
from main.utils import get_auth_token, get_client_ip, AccessToken, RefreshToken


@receiver(user_signed_up)
def user_signed_up(sender, request, user, **kwargs):
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

    # Fill dummy data
    habits_to_create = [
        Habit(
            user=user,
            habit="Read a page",
            detail="when I wake up",
            identity="a wise person"
        ),
        Habit(
            user=user,
            habit="Put the gym shoe on",
            detail="at 7.00 AM everyday",
            identity="a fit person"
        )
    ]
    Habit.objects.bulk_create(habits_to_create)
    tasks_to_create = [
        Task(
            user=user,
            task_name="Check Email",
        ),
        Task(
            user=user,
            task_name="Clean the room"
        ),
        Task(
            user=user,
            task_name="Support Make Your Reps"
        )
    ]
    Task.objects.bulk_create(tasks_to_create)
    UserDetail.objects.get_or_create(user=user, defaults={
        'holiday_routine': "4.00 AM  - Wake Up\n6.00 AM - Break Fast\n7.00 AM - Gym\n9.00 AM - Family Time\n4.00 PM - Game Time\n7.00 PM - Dinner\n9.00 PM - Sleep",
        'workday_routine': "4.00 AM  - Wake Up\n6.00 AM - Break Fast\n7.00 AM - Gym\n9.00 AM - Office\n4.00 PM - Leisure Time\n7.00 PM - Dinner\n9.00 PM - Sleep"
    })




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


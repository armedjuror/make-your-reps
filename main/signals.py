from datetime import timedelta, datetime, time

import jwt
from allauth.account.signals import user_logged_in, user_signed_up
from django.contrib.auth import user_logged_out

from django.dispatch import receiver
from django.http import JsonResponse

from board.models import Habit, Task, UserDetail, RoutineEntry
from board.tasks import generate_daily_timeline
from main.models import UserAuthToken, LoginActivity
from main.utils import get_auth_token, get_client_ip, AccessToken, RefreshToken


@receiver(user_signed_up)
def user_signed_up_handler(sender, request, user, **kwargs):
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

    # Fill dummy data — Habits
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

    # Tasks
    tasks_to_create = [
        Task(user=user, task_name="Check Email"),
        Task(user=user, task_name="Clean the room"),
        Task(user=user, task_name="Support Make Your Reps"),
    ]
    Task.objects.bulk_create(tasks_to_create)

    # UserDetail
    UserDetail.objects.get_or_create(user=user, defaults={
        'sleep_time': time(22, 0),  # 10:00 PM default
    })

    # Routine Entries (proper model instead of text)
    workday_entries = [
        ('04:00', 'Wake Up'),
        ('06:00', 'Breakfast'),
        ('07:00', 'Gym'),
        ('09:00', 'Office'),
        ('16:00', 'Leisure Time'),
        ('19:00', 'Dinner'),
        ('21:00', 'Sleep'),
    ]
    holiday_entries = [
        ('04:00', 'Wake Up'),
        ('06:00', 'Breakfast'),
        ('07:00', 'Gym'),
        ('09:00', 'Family Time'),
        ('16:00', 'Game Time'),
        ('19:00', 'Dinner'),
        ('21:00', 'Sleep'),
    ]

    routine_objects = []
    for time_str, title in workday_entries:
        h, m = time_str.split(':')
        routine_objects.append(RoutineEntry(
            user=user,
            routine_type='workday',
            title=title,
            time=time(int(h), int(m)),
        ))
    for time_str, title in holiday_entries:
        h, m = time_str.split(':')
        routine_objects.append(RoutineEntry(
            user=user,
            routine_type='holiday',
            title=title,
            time=time(int(h), int(m)),
        ))
    RoutineEntry.objects.bulk_create(routine_objects, ignore_conflicts=True)

    # Generate today's timeline for the new user
    generate_daily_timeline.delay(user_id=user.id)


@receiver(user_logged_in)
def handle_user_login(sender, request, user, **kwargs):
    client_type = request.session.get('client_type')
    if client_type == 'api':
        token_string, token_obj = RefreshToken.generate_token(user, request)
        access_token = AccessToken.generate(user)
        request.session['refresh_token'] = token_string
        request.session['access_token'] = access_token
        request.session['user_id'] = user.id

        LoginActivity.objects.create(
            user=user,
            auth_token=token_obj,
            action='login',
            status='success',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
    else:
        request.session['user_id'] = user.id
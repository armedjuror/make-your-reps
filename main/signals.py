from datetime import datetime, time

from allauth.account.signals import user_logged_in, user_signed_up
from django.dispatch import receiver

from board.models import Habit, Task, UserDetail, RoutineEntry, DailyData, FriendRequest, FriendRequestStatus, \
    AccountabilityPartner, AccountabilityPartnerStatus
from board.tasks import generate_daily_timeline
from main.models import LoginActivity
from main.utils import get_client_ip, AccessToken, RefreshToken


def _accept_pending_invites(user):
    """
    After a new user signs up, link and accept any invites that were sent to their email
    before they had an account.
    """
    from board.models import TimelineEvent, TimelineEventType
    from django.utils import timezone

    # Friend requests
    pending_freq = FriendRequest.objects.filter(
        invited_email__iexact=user.email,
        to_user=None,
        status=FriendRequestStatus.PENDING,
    )
    for freq in pending_freq:
        freq.to_user = user
        freq.save()
        from_name = freq.from_user.get_full_name() or freq.from_user.username
        TimelineEvent.objects.create(
            user=user,
            timestamp=timezone.now(),
            event_type=TimelineEventType.FRIEND_REQUEST,
            event=f"{from_name} sent you a friend request",
            reference={'model': 'FriendRequest', 'id': freq.id},
            action={'accept': [True, False]},
        )

    # Accountability partner invites
    pending_ap = AccountabilityPartner.objects.filter(
        invited_email__iexact=user.email,
        partner=None,
        status=AccountabilityPartnerStatus.REQUEST_SENT,
    )
    for ap in pending_ap:
        ap.partner = user
        ap.save()
        owner_name = ap.habit.user.get_full_name() or ap.habit.user.username
        TimelineEvent.objects.create(
            user=user,
            timestamp=timezone.now(),
            event_type=TimelineEventType.ACCOUNTABILITY_INVITE,
            event=f"{owner_name} invited you as accountability partner for: {ap.habit.habit}",
            reference={'model': 'AccountabilityPartner', 'id': ap.id},
            action={'accept': [True, False]},
        )


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
    all_days = [0, 1, 2, 3, 4, 5, 6]
    habits_to_create = [
        Habit(
            user=user,
            habit="Read a page",
            detail="When I wake up, before checking my phone",
            identity="a well-read, curious person",
            frequency=all_days,
            notify_at=time(7, 0),
        ),
        Habit(
            user=user,
            habit="Put the gym shoes on",
            detail="At 7:00 AM, right after brushing my teeth",
            identity="a fit and energetic person",
            frequency=[0, 1, 2, 3, 4],  # Weekdays
            notify_at=time(7, 0),
        ),
        Habit(
            user=user,
            habit="Write 3 things I'm grateful for",
            detail="Every evening before dinner",
            identity="a positive and mindful person",
            frequency=all_days,
            notify_at=time(18, 0),
        ),
    ]
    Habit.objects.bulk_create(habits_to_create)

    # Tasks
    tasks_to_create = [
        Task(user=user, task_name="Check emails and reply to urgent ones"),
        Task(user=user, task_name="Plan tomorrow's top 3 priorities"),
        Task(user=user, task_name="Read for 20 minutes"),
        Task(user=user, task_name="Go for a 10-minute walk"),
    ]
    Task.objects.bulk_create(tasks_to_create)

    # UserDetail
    UserDetail.objects.get_or_create(user=user, defaults={
        'sleep_time': time(22, 0),
    })

    # Today's journal entry
    today = datetime.now().date()
    DailyData.objects.get_or_create(
        user=user,
        date=today,
        defaults={
            'journal': (
                "Welcome to Make Your Reps! \n\n"
                "This is your daily journal. Write about your day, thoughts, plans, or anything on your mind.\n\n"
                "Today is day one. What are you looking forward to building?"
            )
        }
    )

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

    # Link and accept any pending invites sent to this email before signup
    _accept_pending_invites(user)


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
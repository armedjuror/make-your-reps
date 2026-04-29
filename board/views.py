import os
from datetime import datetime, time

from django.contrib.auth.models import User
from django.db.models import Count, F, Prefetch, Q
from django.shortcuts import render, redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from board.models import (
    Task, TaskGroup, DailyData, UserDetail, Habit, HabitStatus, HabitLog,
    RoutineEntry, ReadingListItem, TimelineEvent, TimelineEventType, SearchEngine,
    AccountabilityPartner, AccountabilityPartnerStatus,
    Friend, FriendRequest, FriendRequestStatus,
    Achievement, UserAchievement,
)
from board.serializers import (
    TaskSerializer, TaskGroupSerializer, DailyDataSerializer, UserDetailSerializer, HabitSerializer,
    HabitLogSerializer, RoutineEntrySerializer, ReadingListItemSerializer,
    TimelineEventSerializer, SearchEngineSerializer,
    AccountabilityPartnerSerializer, FriendSerializer, FriendRequestSerializer,
    AchievementSerializer,
)
from main.config_manager import get_config
from main.utils import NoDestroyViewSet, AuthenticatedModelViewSet
from board.tasks import generate_timeline_for_new_item
from board.gamification import award_points, deduct_points, update_daily_streak


# ──────────────────────────────────────
# Social feature helpers
# ──────────────────────────────────────

def _accept_friend_request(freq):
    """Create Friend records in both directions, mark request accepted, notify requester."""
    Friend.objects.get_or_create(user=freq.from_user, friend=freq.to_user)
    Friend.objects.get_or_create(user=freq.to_user, friend=freq.from_user)
    freq.status = FriendRequestStatus.ACCEPTED
    freq.save()
    # Clear action buttons on timeline event
    TimelineEvent.objects.filter(
        user=freq.to_user,
        event_type=TimelineEventType.FRIEND_REQUEST,
        reference__model='FriendRequest',
        reference__id=freq.id,
    ).update(action=None)
    # Notify requester
    acceptor_name = freq.to_user.get_full_name() or freq.to_user.username
    TimelineEvent.objects.create(
        user=freq.from_user,
        timestamp=timezone.now(),
        event_type=TimelineEventType.FRIEND_REQUEST,
        event=f"{acceptor_name} accepted your friend request",
        reference={'model': 'FriendRequest', 'id': freq.id, 'type': 'accepted'},
        action=None,
    )


def _create_partner_habit_entry(ap, target_date):
    """Create the daily monitoring timeline entry for an accountability partner."""
    if not ap.partner:
        return
    owner_name = ap.habit.user.get_full_name() or ap.habit.user.username
    timestamp = timezone.make_aware(datetime.combine(target_date, time(8, 0)))
    exists = TimelineEvent.objects.filter(
        user=ap.partner,
        event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
        reference__model='AccountabilityPartner',
        reference__id=ap.id,
        reference__type='monitor',
        timestamp__date=target_date,
    ).exists()
    if not exists:
        TimelineEvent.objects.create(
            user=ap.partner,
            timestamp=timestamp,
            event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
            event=f"Check on {owner_name}'s habit: {ap.habit.habit}",
            reference={'model': 'AccountabilityPartner', 'id': ap.id, 'type': 'monitor'},
            action={'check': [True, False], 'remind': [True, False]},
        )


def _accept_accountability_invite(ap, user_id):
    """Accept an accountability partner invite: activate, create today's monitoring entry, notify owner."""
    ap.status = AccountabilityPartnerStatus.ACTIVE
    ap.save()
    # Clear action buttons on invite timeline event
    TimelineEvent.objects.filter(
        user_id=user_id,
        event_type=TimelineEventType.ACCOUNTABILITY_INVITE,
        reference__model='AccountabilityPartner',
        reference__id=ap.id,
    ).update(action=None)
    # Create today's monitoring entry
    _create_partner_habit_entry(ap, timezone.localdate())
    # Notify habit owner
    partner_name = ap.partner.get_full_name() or ap.partner.username
    TimelineEvent.objects.create(
        user=ap.habit.user,
        timestamp=timezone.now(),
        event_type=TimelineEventType.ACCOUNTABILITY_INVITE,
        event=f"{partner_name} accepted your accountability partner request for: {ap.habit.habit}",
        reference={'model': 'AccountabilityPartner', 'id': ap.id, 'type': 'accepted'},
        action=None,
    )


def _invite_email_html(title, body_text, accept_url, button_label):
    """Return a minimal HTML email with an accept button."""
    return f"""
<html><body style="font-family:sans-serif;color:#333;max-width:600px;margin:0 auto;padding:24px">
<h2 style="margin-bottom:8px">{title}</h2>
<p style="line-height:1.6">{body_text}</p>
<p style="margin-top:32px">
  <a href="{accept_url}"
     style="background:#98753f;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-weight:bold;display:inline-block">
    {button_label}
  </a>
</p>
<p style="margin-top:32px;font-size:13px;color:#888">
  If the button doesn't work, copy and paste this link:<br>
  <a href="{accept_url}" style="color:#98753f">{accept_url}</a>
</p>
<p style="margin-top:24px;font-size:13px;color:#888">— The Make Your Reps Team</p>
</body></html>
"""


def _send_accountability_email(to_email, owner_name, habit_name, token, site_url):
    """Send an email invite to a non-registered user."""
    from django.core.mail import EmailMultiAlternatives
    from django.conf import settings

    accept_url = f"{site_url}accept-invite/{token}/"
    subject = f"{owner_name} invited you as an accountability partner on Make Your Reps"
    plain = (
        f"Hi,\n\n"
        f"{owner_name} has invited you to be their accountability partner "
        f"for the habit: \"{habit_name}\"\n\n"
        f"Accept the invite here: {accept_url}\n\n"
        f"— The Make Your Reps Team"
    )
    html = _invite_email_html(
        title=f"{owner_name} invited you as an accountability partner",
        body_text=f"{owner_name} wants you to be their accountability partner for the habit: <strong>{habit_name}</strong>.<br>Sign up (or log in) to accept.",
        accept_url=accept_url,
        button_label="Accept Invite",
    )
    msg = EmailMultiAlternatives(
        subject=subject,
        body=plain,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'Make Your Reps <noreply@makeyourreps.com>'),
        to=[to_email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)


def _send_friend_request_email(to_email, from_name, token, site_url):
    """Send a friend-request email to a non-registered user."""
    from django.core.mail import EmailMultiAlternatives
    from django.conf import settings

    accept_url = f"{site_url}accept-invite/{token}/"
    subject = f"{from_name} sent you a friend request on Make Your Reps"
    plain = (
        f"Hi,\n\n"
        f"{from_name} has sent you a friend request on Make Your Reps.\n\n"
        f"Accept the request here: {accept_url}\n\n"
        f"— The Make Your Reps Team"
    )
    html = _invite_email_html(
        title=f"{from_name} sent you a friend request",
        body_text=f"{from_name} wants to connect with you on Make Your Reps.<br>Sign up (or log in) to accept.",
        accept_url=accept_url,
        button_label="Accept Friend Request",
    )
    msg = EmailMultiAlternatives(
        subject=subject,
        body=plain,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'Make Your Reps <noreply@makeyourreps.com>'),
        to=[to_email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)


# ──────────────────────────────────────
# Page Views
# ──────────────────────────────────────

def dashboard(request):
    """Single unified dashboard view serving all panes."""
    if request.user.is_authenticated:
        return render(request, 'board/dashboard.html')
    else:
        return redirect('/')


def journals(request):
    """Redirect legacy journals URL to dashboard with journals pane."""
    if request.user.is_authenticated:
        return redirect('/board/#journals')
    else:
        return redirect('/')


# ──────────────────────────────────────
# Existing ViewSets (modified)
# ──────────────────────────────────────

class UserDetailView(APIView):
    def get(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)
        user_detail, _ = UserDetail.objects.get_or_create(user_id=user_id)
        return Response({
            'status': 'success',
            'data': {
                **UserDetailSerializer(user_detail).data,
                'first_name': user_detail.user.first_name,
                'last_name': user_detail.user.last_name,
            }
        })

    def put(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)
        user_detail, _ = UserDetail.objects.get_or_create(user_id=user_id)

        # Handle User model name fields separately
        name_fields = {}
        if 'first_name' in request.data:
            name_fields['first_name'] = request.data['first_name']
        if 'last_name' in request.data:
            name_fields['last_name'] = request.data['last_name']
        if name_fields:
            User.objects.filter(pk=user_id).update(**name_fields)

        serializer = UserDetailSerializer(user_detail, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        return Response({
            'status': 'failed',
            'error': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class DashboardConfigView(APIView):
    def get(self, request):
        if not request.session.get('user_id'):
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)
        configs = get_config().get_all()
        return Response({
            'status': 'success',
            'data': {
                'greetings': {
                    'night': configs.get('board_greetings_night', []),
                    'morning': configs.get('board_greetings_morning', []),
                    'afternoon': configs.get('board_greetings_afternoon', []),
                    'evening': configs.get('board_greetings_evening', []),
                },
                'messages': {
                    'night': configs.get('board_messages_night', []),
                    'morning': configs.get('board_messages_morning', []),
                    'afternoon': configs.get('board_messages_afternoon', []),
                    'evening': configs.get('board_messages_evening', []),
                },
                'section_titles': {
                    'tasks': configs.get('board_tasks_title', 'Tasks'),
                    'habits': configs.get('board_habits_title', 'Habits'),
                    'routines': configs.get('board_routines_title', 'Routines'),
                    'sleep_tracker': configs.get('board_sleep_tracker_title', 'Sleep Tracker'),
                },
                'copyright_text': configs.get('copyright_text', ''),
            }
        })


class TaskGroupViewSet(AuthenticatedModelViewSet):
    serializer_class = TaskGroupSerializer

    def get_queryset(self):
        return TaskGroup.objects.filter(is_active=True)

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        queryset = self.get_queryset().filter(user_id=user_id)
        data = self.get_serializer(queryset, many=True).data
        return Response({'status': 'success', 'data': data})

    def create(self, request, **kwargs):
        user_id = request.session.get('user_id')
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'status': 'failed', 'error': 'Group name is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        # Check uniqueness
        if self.get_queryset().filter(user_id=user_id, name__iexact=name).exists():
            return Response({'status': 'failed', 'error': 'A group with this name already exists'},
                            status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user_id=user_id)
            return Response({'status': 'success', 'data': serializer.data},
                            status=status.HTTP_201_CREATED)
        return Response({'status': 'failed', 'error': serializer.errors},
                        status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, **kwargs):
        """Rename a group."""
        pk = int(kwargs['pk'])
        user_id = request.session.get('user_id')
        group = self.get_queryset().get(pk=pk, user_id=user_id)
        new_name = request.data.get('name', '').strip()
        if not new_name:
            return Response({'status': 'failed', 'error': 'Group name is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        if self.get_queryset().filter(user_id=user_id, name__iexact=new_name).exclude(pk=pk).exists():
            return Response({'status': 'failed', 'error': 'A group with this name already exists'},
                            status=status.HTTP_400_BAD_REQUEST)
        group.name = new_name
        group.save()
        return Response({'status': 'success', 'data': self.get_serializer(group).data})

    def destroy(self, request, **kwargs):
        """Delete a group — moves its tasks to General (or first active group)."""
        pk = int(kwargs['pk'])
        user_id = request.session.get('user_id')
        group = self.get_queryset().get(pk=pk, user_id=user_id)

        # Find or create a General group to reassign tasks
        fallback, _ = TaskGroup.objects.get_or_create(
            user_id=user_id, name='General',
            defaults={'is_active': True}
        )
        if fallback.pk == pk:
            return Response({'status': 'failed', 'error': 'Cannot delete the General group'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Move tasks to fallback
        Task.objects.filter(group=group, is_deleted=False).update(group=fallback)
        group.is_active = False
        group.save()
        return Response({'status': 'success', 'message': f'Group deleted. Tasks moved to {fallback.name}.'})


class TaskViewSet(AuthenticatedModelViewSet):
    serializer_class = TaskSerializer

    def get_queryset(self):
        return Task.objects.filter(is_deleted=False).select_related('group')

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        queryset = self.get_queryset().filter(user_id=user_id)

        # Filter by group
        group_id = request.GET.get('group')
        if group_id:
            queryset = queryset.filter(group_id=group_id)

        # Filter by status
        done_filter = request.GET.get('done')
        if done_filter == 'true':
            queryset = queryset.filter(is_done=True)
        elif done_filter == 'false':
            queryset = queryset.filter(is_done=False)

        queryset = queryset.order_by(F('deadline').asc(nulls_last=True), 'created_at')
        data = self.get_serializer(queryset, many=True).data
        return Response({
            'status': 'success',
            'data': data
        })

    def create(self, request, **kwargs):
        user_id = request.session.get('user_id')

        # Auto-assign to General if no group specified
        group_id = request.data.get('group')
        if not group_id:
            general, _ = TaskGroup.objects.get_or_create(
                user_id=user_id, name='General',
                defaults={'is_active': True}
            )
            # Inject group into request data
            request.data['group'] = general.pk

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user_id=user_id)
            generate_timeline_for_new_item.delay('todo', serializer.data['id'])
            return Response({
                "status": "success",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({
                "status": "failed",
                "error": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, **kwargs):
        task_id = kwargs.get('pk')
        task = self.get_queryset().get(pk=task_id)
        deadline_changing = 'deadline' in request.data and request.data['deadline'] != (
            task.deadline.isoformat() if task.deadline else None
        )
        was_done = task.is_done
        serializer = self.get_serializer(task, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            gamification_result = {}
            is_done_value = request.data.get('is_done')
            uid = request.session.get('user_id')
            if is_done_value is True and not was_done:
                update_daily_streak(uid)
                gamification_result = award_points(uid, 'todo')
            elif is_done_value is False and was_done:
                gamification_result = deduct_points(uid, 'todo')
            if deadline_changing:
                TimelineEvent.objects.filter(
                    event_type=TimelineEventType.TODO,
                    reference__model='Task',
                    reference__id=task_id,
                ).delete()
                generate_timeline_for_new_item.delay('todo', task_id)
            return Response({
                'status': 'success',
                'data': serializer.data,
                'message': 'Task updated successfully',
                'gamification': gamification_result,
            })
        else:
            return Response({
                "status": "failed",
                "error": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, **kwargs):
        task_id = kwargs.get('pk')
        task = self.get_queryset().get(pk=task_id)
        task.is_deleted = True
        task.save()
        TimelineEvent.objects.filter(
            event_type=TimelineEventType.TODO,
            reference__model='Task',
            reference__id=task_id,
        ).delete()
        return Response({
            'status': 'success',
            'message': 'Task deleted successfully',
        })


class DailyDataViewSet(NoDestroyViewSet):
    serializer_class = DailyDataSerializer

    def get_queryset(self):
        return DailyData.objects.all()

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        start_date = request.GET.get('start_date')
        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d')
            except ValueError:
                return Response({
                    'status': 'failed',
                    'error': 'Invalid start date',
                }, status=status.HTTP_400_BAD_REQUEST)

        end_date = request.GET.get('end_date')
        if end_date:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                return Response({
                    'status': 'failed',
                    'error': 'Invalid end date',
                }, status=status.HTTP_400_BAD_REQUEST)

        if start_date and end_date:
            queryset = self.get_queryset().filter(user_id=user_id, date__gte=start_date, date__lte=end_date)
        elif start_date:
            queryset = self.get_queryset().filter(user_id=user_id, date__gte=start_date)
        else:
            queryset = self.get_queryset().filter(user_id=user_id)

        data = self.get_serializer(queryset, many=True).data
        return Response({
            'status': 'success',
            'data': data
        })

    def retrieve(self, request, **kwargs):
        user_id = request.session.get('user_id')
        date_str = kwargs.get('pk')
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'status': 'failed', 'error': 'Invalid date'}, status=400)

        obj, created = DailyData.objects.get_or_create(
            user_id=user_id, date=target_date
        )
        return Response({
            'status': 'success',
            'data': self.get_serializer(obj).data
        })

    def update(self, request, **kwargs):
        user_id = request.session.get('user_id')
        date_str = kwargs.get('pk')
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'status': 'failed', 'error': 'Invalid date'}, status=400)

        obj, created = DailyData.objects.get_or_create(
            user_id=user_id, date=target_date
        )
        had_journal = bool(obj.journal and obj.journal.strip())
        had_sleep = obj.sleep_hours is not None
        serializer = self.get_serializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            uid = request.session.get('user_id')
            gamification_result = {}
            now_journal = bool(serializer.data.get('journal', ''))
            now_sleep = serializer.data.get('sleep_hours') is not None
            if not had_journal and now_journal:
                update_daily_streak(uid)
                gamification_result = award_points(uid, 'journal')
            elif not had_sleep and now_sleep:
                update_daily_streak(uid)
                gamification_result = award_points(uid, 'sleep')
            return Response({
                'status': 'success',
                'data': serializer.data,
                'gamification': gamification_result,
            })
        else:
            return Response({
                "status": "failed",
                "error": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='add_focus')
    def add_focus_minutes(self, request, **kwargs):
        """Atomically add minutes to today's focus_minutes."""
        from django.db.models import F
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)
        minutes = request.data.get('minutes', 0)
        try:
            minutes = int(minutes)
        except (ValueError, TypeError):
            return Response({'status': 'failed', 'error': 'Invalid minutes'}, status=400)

        today = timezone.localdate()
        obj, _ = DailyData.objects.get_or_create(user_id=user_id, date=today)
        DailyData.objects.filter(pk=obj.pk).update(focus_minutes=F('focus_minutes') + minutes)
        obj.refresh_from_db()

        # Award points per completed cycle (25 min = 1 cycle)
        gamification_result = {}
        cycles_added = minutes // 25
        if cycles_added > 0:
            update_daily_streak(user_id)
            gamification_result = award_points(user_id, 'pomodoro', multiplier=float(cycles_added))

        return Response({'status': 'success', 'data': {'focus_minutes': obj.focus_minutes}, 'gamification': gamification_result})


class HabitViewSet(AuthenticatedModelViewSet):
    serializer_class = HabitSerializer

    def get_queryset(self):
        return Habit.objects.exclude(status=HabitStatus.DELETED.value)

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        habit_status = request.GET.get('status', 'active')
        now = timezone.localdate()
        start_date = now - timezone.timedelta(days=60)
        queryset = self.get_queryset().filter(
            user_id=user_id, status=habit_status
        ).annotate(
            total_reps_count=Count('habitlog', filter=Q(habitlog__is_done=True))
        ).prefetch_related(
            Prefetch(
                'habitlog_set',
                queryset=HabitLog.objects.filter(date__gte=start_date, date__lte=now).order_by('date'),
                to_attr='recent_logs_prefetched',
            )
        ).order_by('notify_at', 'created_at')
        data = self.get_serializer(queryset, many=True).data
        return Response({
            'status': 'success',
            'data': data
        })

    def create(self, request, **kwargs):
        user_id = request.session.get('user_id')
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save(user_id=user_id)
            generate_timeline_for_new_item.delay('habit', serializer.data['id'])
            return Response({
                "status": "success",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            "status": "failed",
            "error": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, **kwargs):
        try:
            pk = int(kwargs['pk'])
            habit = self.get_queryset().get(pk=pk)
            serializer = self.serializer_class(habit, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({
                    "status": "success",
                    "data": serializer.data,
                    "message": "Habit updated successfully"
                })
            return Response({
                "status": "failed",
                "error": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        except Habit.DoesNotExist:
            return Response({
                "status": "failed",
                "error": "Habit not found"
            }, status=status.HTTP_404_NOT_FOUND)

    def destroy(self, request, **kwargs):
        habit_id = int(kwargs['pk'])
        habit = self.get_queryset().get(pk=habit_id)
        habit.status = HabitStatus.DELETED.value
        habit.save()
        TimelineEvent.objects.filter(
            event_type=TimelineEventType.HABIT,
            reference__model='Habit',
            reference__id=habit_id,
        ).delete()
        return Response({
            "status": "success",
            "message": "Habit deleted successfully"
        })

    @action(detail=True, methods=['get'])
    def logs(self, request, **kwargs):
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        habit_id = int(kwargs['pk'])
        dataset = HabitLog.objects.filter(habit__id=habit_id)
        if start_date:
            dataset = dataset.filter(date__gte=start_date)
        if end_date:
            dataset = dataset.filter(date__lte=end_date)
        return Response({
            "status": "success",
            'data': HabitLogSerializer(dataset, many=True).data
        })

    @action(detail=True, methods=['put'])
    def toggle(self, request, **kwargs):
        habit_id = int(kwargs['pk'])
        toggle_date = request.data.get('date')
        try:
            habit = self.get_queryset().get(pk=habit_id)
        except Habit.DoesNotExist:
            return Response({
                "status": "failed",
                "error": "Habit not found"
            }, status=status.HTTP_404_NOT_FOUND)

        try:
            parsed_date = datetime.strptime(toggle_date, '%Y-%m-%d').date()
            if parsed_date > timezone.localdate():
                return Response({'status': 'failed', 'error': 'This date is in future'},
                                status=status.HTTP_400_BAD_REQUEST)
            if parsed_date < habit.created_at.replace(tzinfo=None).date():
                return Response({
                    "status": "failed",
                    "error": "This date is before the habit creation"
                })
        except ValueError:
            return Response({'status': 'failed', 'error': 'Invalid Date'},
                            status=status.HTTP_400_BAD_REQUEST)

        habit_log, _ = HabitLog.objects.get_or_create(habit_id=habit_id, date=toggle_date)
        was_done = habit_log.is_done
        habit_log.is_done = not habit_log.is_done
        habit_log.save()

        # Gamification
        user_id = request.session.get('user_id')
        gamification_result = {}
        if parsed_date == timezone.localdate():
            if not was_done and habit_log.is_done:
                update_daily_streak(user_id)
                gamification_result = award_points(user_id, 'habit')
            elif was_done and not habit_log.is_done:
                gamification_result = deduct_points(user_id, 'habit')

        # Notify active accountability partners
        active_partners = AccountabilityPartner.objects.filter(
            habit=habit, status=AccountabilityPartnerStatus.ACTIVE,
        ).select_related('partner', 'habit__user')
        owner_name = habit.user.get_full_name() or habit.user.username
        today = timezone.localdate()
        for ap in active_partners:
            if not ap.partner:
                continue
            if habit_log.is_done:
                exists = TimelineEvent.objects.filter(
                    user=ap.partner,
                    event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
                    reference__model='AccountabilityPartner',
                    reference__id=ap.id,
                    reference__type='done',
                    timestamp__date=today,
                ).exists()
                if not exists:
                    TimelineEvent.objects.create(
                        user=ap.partner,
                        timestamp=timezone.now(),
                        event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
                        event=f"{owner_name} completed: {habit.habit}",
                        reference={'model': 'AccountabilityPartner', 'id': ap.id, 'type': 'done'},
                        action=None,
                    )
            else:
                TimelineEvent.objects.filter(
                    user=ap.partner,
                    event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
                    reference__model='AccountabilityPartner',
                    reference__id=ap.id,
                    reference__type='done',
                    timestamp__date=today,
                ).delete()

        return Response({
            'status': 'success',
            'data': HabitLogSerializer(habit_log).data,
            'message': self.get_serializer(habit).data['remark'],
            'gamification': gamification_result,
        })


# ──────────────────────────────────────
# New ViewSets
# ──────────────────────────────────────

class RoutineEntryViewSet(AuthenticatedModelViewSet):
    serializer_class = RoutineEntrySerializer

    def get_queryset(self):
        return RoutineEntry.objects.all()

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        routine_type = request.GET.get('type')
        queryset = self.get_queryset().filter(user_id=user_id)
        if routine_type:
            queryset = queryset.filter(routine_type=routine_type)
        data = self.get_serializer(queryset, many=True).data
        return Response({'status': 'success', 'data': data})

    def create(self, request, **kwargs):
        user_id = request.session.get('user_id')
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user_id=user_id)
            generate_timeline_for_new_item.delay('routine', serializer.data['id'])
            return Response({
                'status': 'success',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'status': 'failed',
            'error': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, **kwargs):
        pk = int(kwargs['pk'])
        entry = self.get_queryset().get(pk=pk)
        serializer = self.get_serializer(entry, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        return Response({
            'status': 'failed',
            'error': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, **kwargs):
        pk = int(kwargs['pk'])
        self.get_queryset().get(pk=pk).delete()
        return Response({'status': 'success', 'message': 'Routine entry deleted'})

    @action(detail=False, methods=['post'])
    def bulk_create(self, request, **kwargs):
        """Create multiple routine entries at once (for routine editing)."""
        user_id = request.session.get('user_id')
        routine_type = request.data.get('routine_type')
        entries = request.data.get('entries', [])

        if not routine_type or not entries:
            return Response({
                'status': 'failed',
                'error': 'routine_type and entries are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Delete existing entries for this type
        RoutineEntry.objects.filter(
            user_id=user_id, routine_type=routine_type
        ).delete()

        # Delete today's routine timeline events so the re-created entries
        # don't duplicate them (new entry IDs would bypass the exists check)
        TimelineEvent.objects.filter(
            user_id=user_id,
            event_type=TimelineEventType.ROUTINE,
            timestamp__date=timezone.localdate(),
        ).delete()

        created = []
        for entry_data in entries:
            entry_data['routine_type'] = routine_type
            serializer = self.get_serializer(data=entry_data)
            if serializer.is_valid():
                obj = serializer.save(user_id=user_id)
                created.append(serializer.data)
                generate_timeline_for_new_item.delay('routine', serializer.data['id'])

        return Response({
            'status': 'success',
            'data': created,
            'message': f'{len(created)} routine entries created'
        }, status=status.HTTP_201_CREATED)


class ReadingListItemViewSet(AuthenticatedModelViewSet):
    serializer_class = ReadingListItemSerializer
    MAX_FEATURED = 6

    def get_queryset(self):
        return ReadingListItem.objects.filter(is_active=True)

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        featured_only = request.GET.get('featured')
        queryset = self.get_queryset().filter(user_id=user_id)
        if featured_only:
            queryset = queryset.filter(is_featured=True)
        data = self.get_serializer(queryset, many=True).data
        return Response({'status': 'success', 'data': data})

    def create(self, request, **kwargs):
        user_id = request.session.get('user_id')
        is_featured = request.data.get('is_featured', False)

        if is_featured:
            current_featured = self.get_queryset().filter(
                user_id=user_id, is_featured=True
            ).count()
            if current_featured >= self.MAX_FEATURED:
                return Response({
                    'status': 'failed',
                    'error': f'Maximum {self.MAX_FEATURED} featured items allowed'
                }, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user_id=user_id)
            return Response({
                'status': 'success',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'status': 'failed',
            'error': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, **kwargs):
        pk = int(kwargs['pk'])
        user_id = request.session.get('user_id')
        item = self.get_queryset().get(pk=pk)
        is_featured = request.data.get('is_featured')

        if is_featured and not item.is_featured:
            current_featured = self.get_queryset().filter(
                user_id=user_id, is_featured=True
            ).count()
            if current_featured >= self.MAX_FEATURED:
                return Response({
                    'status': 'failed',
                    'error': f'Maximum {self.MAX_FEATURED} featured items allowed'
                }, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(item, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        return Response({
            'status': 'failed',
            'error': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, **kwargs):
        pk = int(kwargs['pk'])
        item = self.get_queryset().get(pk=pk)
        item.is_active = False
        item.save()
        return Response({'status': 'success', 'message': 'Item removed'})


class TimelineEventViewSet(AuthenticatedModelViewSet):
    serializer_class = TimelineEventSerializer

    def get_queryset(self):
        return TimelineEvent.objects.all()

    def list(self, request, **kwargs):
        """
        Paginated timeline. Supports:
        - ?date=YYYY-MM-DD (filter by date, defaults to today)
        - ?before=ISO_TIMESTAMP (for lazy loading older events)
        - ?limit=N (defaults to 5)
        """
        user_id = request.session.get('user_id')
        target_date = request.GET.get('date')
        before = request.GET.get('before')
        limit = int(request.GET.get('limit', 100))

        queryset = self.get_queryset().filter(user_id=user_id)

        if before:
            try:
                before_dt = datetime.fromisoformat(before)
                queryset = queryset.filter(timestamp__lt=before_dt)
            except ValueError:
                pass
        elif target_date:
            try:
                d = datetime.strptime(target_date, '%Y-%m-%d').date()
                queryset = queryset.filter(timestamp__date=d)
            except ValueError:
                pass
        # If neither before nor date specified, return recent events across all days
        queryset = queryset.order_by('-timestamp')[:limit]

        data = self.get_serializer(queryset, many=True).data
        return Response({
            'status': 'success',
            'data': data,
            'has_more': len(data) == limit
        })

    def create(self, request, **kwargs):
        """Allow manual creation of timeline events (e.g., text notes, meetings)."""
        user_id = request.session.get('user_id')
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user_id=user_id)
            return Response({
                'status': 'success',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response({
            'status': 'failed',
            'error': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['put'])
    def respond(self, request, **kwargs):
        """
        Record the user's action response on a timeline event.
        Propagates to the source model (e.g., toggle HabitLog, mark Task done).
        """
        pk = int(kwargs['pk'])
        user_id = request.session.get('user_id')
        event = self.get_queryset().get(pk=pk, user_id=user_id)
        action_response = request.data.get('action_response')

        if not action_response:
            return Response({
                'status': 'failed',
                'error': 'action_response is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        event.action_response = action_response
        event.save()

        # Propagate to source model
        propagation_result = self._propagate_action(event, action_response, user_id)

        return Response({
            'status': 'success',
            'data': self.get_serializer(event).data,
            'propagation': propagation_result
        })

    def _propagate_action(self, event, action_response, user_id=None):
        """Propagate timeline action to the actual source model."""
        ref = event.reference
        if not ref:
            return {'propagated': False, 'reason': 'No reference'}

        model_name = ref.get('model')
        model_id = ref.get('id')

        try:
            if event.event_type == TimelineEventType.HABIT and model_name == 'Habit':
                mark_done = action_response.get('mark_done', False)
                today = timezone.localdate()
                habit_log, _ = HabitLog.objects.get_or_create(
                    habit_id=model_id, date=today
                )
                habit_log.is_done = mark_done
                habit_log.save()
                return {'propagated': True, 'model': 'HabitLog', 'is_done': mark_done}

            elif event.event_type == TimelineEventType.TODO and model_name == 'Task':
                mark_done = action_response.get('mark_done', False)
                task = Task.objects.get(pk=model_id)
                task.is_done = mark_done
                task.save()
                return {'propagated': True, 'model': 'Task', 'is_done': mark_done}

            elif event.event_type == TimelineEventType.SLEEP_TRACKER:
                return {'propagated': False, 'reason': 'Sleep logged via daily_data API'}

            elif event.event_type == TimelineEventType.JOURNAL:
                return {'propagated': False, 'reason': 'Journal edited via daily_data API'}

            elif event.event_type == TimelineEventType.MEETING:
                return {'propagated': False, 'reason': 'Client-side action'}

            elif event.event_type == TimelineEventType.FRIEND_REQUEST and model_name == 'FriendRequest':
                freq = FriendRequest.objects.get(pk=model_id, to_user_id=user_id)
                if freq.status != FriendRequestStatus.PENDING:
                    return {'propagated': False, 'reason': 'Already responded'}
                if action_response.get('accept'):
                    _accept_friend_request(freq)
                    return {'propagated': True, 'action': 'accepted'}
                else:
                    freq.status = FriendRequestStatus.DECLINED
                    freq.save()
                    TimelineEvent.objects.filter(pk=event.pk).update(action=None)
                    return {'propagated': True, 'action': 'declined'}

            elif event.event_type == TimelineEventType.ACCOUNTABILITY_INVITE and model_name == 'AccountabilityPartner':
                ap = AccountabilityPartner.objects.get(pk=model_id, partner_id=user_id)
                if ap.status != AccountabilityPartnerStatus.REQUEST_SENT:
                    return {'propagated': False, 'reason': 'Already responded'}
                if action_response.get('accept'):
                    _accept_accountability_invite(ap, user_id)
                    return {'propagated': True, 'action': 'accepted'}
                else:
                    ap.status = AccountabilityPartnerStatus.INACTIVE
                    ap.save()
                    TimelineEvent.objects.filter(pk=event.pk).update(action=None)
                    return {'propagated': True, 'action': 'declined'}

        except Exception as e:
            return {'propagated': False, 'reason': str(e)}

        return {'propagated': False, 'reason': 'Unknown event type'}

    def destroy(self, request, **kwargs):
        """Don't actually delete timeline events."""
        return Response({
            'status': 'failed',
            'error': 'Timeline events cannot be deleted'
        }, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class SearchEngineViewSet(NoDestroyViewSet):
    """Read-only master list of search engines."""
    serializer_class = SearchEngineSerializer

    def get_queryset(self):
        return SearchEngine.objects.filter(is_active=True)

    def list(self, request, **kwargs):
        data = self.get_serializer(self.get_queryset(), many=True).data
        return Response({'status': 'success', 'data': data})


class FriendViewSet(AuthenticatedModelViewSet):
    serializer_class = FriendSerializer

    def get_queryset(self):
        return Friend.objects.all()

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        friends = self.get_queryset().filter(user_id=user_id).select_related('friend')
        return Response({'status': 'success', 'data': FriendSerializer(friends, many=True).data})

    def destroy(self, request, **kwargs):
        """Revoke friendship — removes both directions and cleans up the friend request."""
        user_id = request.session.get('user_id')
        pk = int(kwargs['pk'])
        friendship = self.get_queryset().get(pk=pk, user_id=user_id)
        friend_id = friendship.friend_id
        Friend.objects.filter(user_id=user_id, friend_id=friend_id).delete()
        Friend.objects.filter(user_id=friend_id, friend_id=user_id).delete()
        FriendRequest.objects.filter(
            from_user_id__in=[user_id, friend_id],
            to_user_id__in=[user_id, friend_id],
        ).delete()
        return Response({'status': 'success', 'message': 'Friendship removed'})

    @action(detail=False, methods=['post'], url_path='send_request')
    def send_request(self, request, **kwargs):
        user_id = request.session.get('user_id')
        email = request.data.get('email', '').strip()

        if not email:
            return Response({'status': 'failed', 'error': 'Email is required'}, status=400)

        try:
            to_user = User.objects.get(email=email)
        except User.DoesNotExist:
            to_user = None

        from_user = User.objects.get(pk=user_id)
        from_name = from_user.get_full_name() or from_user.username

        if to_user is None:
            # Non-registered user — store by email and send invite
            if FriendRequest.objects.filter(from_user=from_user, invited_email=email).exists():
                return Response({'status': 'failed', 'error': 'Friend request already sent'}, status=400)
            freq = FriendRequest.objects.create(
                from_user=from_user,
                to_user=None,
                invited_email=email,
                status=FriendRequestStatus.PENDING,
            )
            site_url = request.build_absolute_uri('/')
            _send_friend_request_email(email, from_name, freq.token, site_url)
            return Response({'status': 'success', 'message': 'Friend request sent'})

        if to_user.id == user_id:
            return Response({'status': 'failed', 'error': 'Cannot send friend request to yourself'}, status=400)

        if Friend.objects.filter(user_id=user_id, friend=to_user).exists():
            return Response({'status': 'failed', 'error': 'Already friends'}, status=400)

        # Check if they sent us a request already — auto-accept mutual
        existing_reverse = FriendRequest.objects.filter(
            from_user=to_user, to_user_id=user_id, status=FriendRequestStatus.PENDING
        ).first()
        if existing_reverse:
            _accept_friend_request(existing_reverse)
            return Response({'status': 'success', 'message': 'Mutual request found — you are now friends!'})

        freq, created = FriendRequest.objects.get_or_create(
            from_user=from_user,
            to_user=to_user,
            defaults={'status': FriendRequestStatus.PENDING},
        )
        if not created:
            if freq.status == FriendRequestStatus.PENDING:
                return Response({'status': 'failed', 'error': 'Friend request already sent'}, status=400)
            freq.status = FriendRequestStatus.PENDING
            freq.save()

        TimelineEvent.objects.create(
            user=to_user,
            timestamp=timezone.now(),
            event_type=TimelineEventType.FRIEND_REQUEST,
            event=f"{from_name} sent you a friend request",
            reference={'model': 'FriendRequest', 'id': freq.id},
            action={'accept': [True, False]},
        )
        site_url = request.build_absolute_uri('/')
        _send_friend_request_email(to_user.email, from_name, freq.token, site_url)
        return Response({'status': 'success', 'message': 'Friend request sent'})

    @action(detail=False, methods=['get'])
    def requests(self, request, **kwargs):
        user_id = request.session.get('user_id')
        received = FriendRequest.objects.filter(to_user_id=user_id, status=FriendRequestStatus.PENDING)
        sent = FriendRequest.objects.filter(from_user_id=user_id).exclude(status=FriendRequestStatus.DECLINED)
        return Response({
            'status': 'success',
            'data': {
                'received': FriendRequestSerializer(received, many=True).data,
                'sent': FriendRequestSerializer(sent, many=True).data,
            }
        })


class FriendRequestViewSet(AuthenticatedModelViewSet):
    serializer_class = FriendRequestSerializer

    def get_queryset(self):
        return FriendRequest.objects.all()

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        queryset = self.get_queryset().filter(to_user_id=user_id, status=FriendRequestStatus.PENDING)
        return Response({'status': 'success', 'data': FriendRequestSerializer(queryset, many=True).data})

    @action(detail=True, methods=['post'])
    def accept(self, request, **kwargs):
        user_id = request.session.get('user_id')
        freq = self.get_queryset().get(pk=int(kwargs['pk']), to_user_id=user_id)
        if freq.status != FriendRequestStatus.PENDING:
            return Response({'status': 'failed', 'error': 'Already responded'}, status=400)
        _accept_friend_request(freq)
        return Response({'status': 'success', 'message': 'Friend request accepted'})

    @action(detail=True, methods=['post'])
    def decline(self, request, **kwargs):
        user_id = request.session.get('user_id')
        freq = self.get_queryset().get(pk=int(kwargs['pk']), to_user_id=user_id)
        if freq.status != FriendRequestStatus.PENDING:
            return Response({'status': 'failed', 'error': 'Already responded'}, status=400)
        freq.status = FriendRequestStatus.DECLINED
        freq.save()
        TimelineEvent.objects.filter(
            user_id=user_id,
            event_type=TimelineEventType.FRIEND_REQUEST,
            reference__model='FriendRequest',
            reference__id=freq.id,
        ).update(action=None)
        return Response({'status': 'success', 'message': 'Friend request declined'})


class AccountabilityPartnerViewSet(AuthenticatedModelViewSet):
    serializer_class = AccountabilityPartnerSerializer

    def get_queryset(self):
        return AccountabilityPartner.objects.select_related('habit__user', 'partner')

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        habit_id = request.GET.get('habit_id')
        if habit_id:
            queryset = self.get_queryset().filter(habit__user_id=user_id, habit_id=habit_id)
        else:
            queryset = self.get_queryset().filter(partner_id=user_id, status=AccountabilityPartnerStatus.ACTIVE)
        return Response({'status': 'success', 'data': AccountabilityPartnerSerializer(queryset, many=True).data})

    @action(detail=False, methods=['get'], url_path='my_invites')
    def my_invites(self, request, **kwargs):
        user_id = request.session.get('user_id')
        invites = self.get_queryset().filter(partner_id=user_id, status=AccountabilityPartnerStatus.REQUEST_SENT)
        return Response({'status': 'success', 'data': AccountabilityPartnerSerializer(invites, many=True).data})

    def create(self, request, **kwargs):
        user_id = request.session.get('user_id')
        habit_id = request.data.get('habit_id')
        email = request.data.get('email', '').strip()

        if not habit_id or not email:
            return Response({'status': 'failed', 'error': 'habit_id and email are required'}, status=400)

        try:
            habit = Habit.objects.get(pk=habit_id, user_id=user_id, status=HabitStatus.ACTIVE.value)
        except Habit.DoesNotExist:
            return Response({'status': 'failed', 'error': 'Habit not found'}, status=404)

        try:
            partner_user = User.objects.get(email=email)
        except User.DoesNotExist:
            partner_user = None

        if partner_user and partner_user.id == user_id:
            return Response({'status': 'failed', 'error': 'Cannot add yourself as partner'}, status=400)

        if partner_user and AccountabilityPartner.objects.filter(habit=habit, partner=partner_user).exists():
            return Response({'status': 'failed', 'error': 'Already an accountability partner for this habit'}, status=400)

        is_friend = partner_user and Friend.objects.filter(user_id=user_id, friend=partner_user).exists()
        ap_status = AccountabilityPartnerStatus.ACTIVE if is_friend else AccountabilityPartnerStatus.REQUEST_SENT

        ap = AccountabilityPartner.objects.create(
            habit=habit,
            partner=partner_user,
            invited_email=email,
            status=ap_status,
        )

        owner = User.objects.get(pk=user_id)
        owner_name = owner.get_full_name() or owner.username

        if partner_user:
            if is_friend:
                TimelineEvent.objects.create(
                    user=partner_user,
                    timestamp=timezone.now(),
                    event_type=TimelineEventType.ACCOUNTABILITY_INVITE,
                    event=f"{owner_name} added you as accountability partner for: {habit.habit}",
                    reference={'model': 'AccountabilityPartner', 'id': ap.id, 'type': 'accepted'},
                    action=None,
                )
                _create_partner_habit_entry(ap, timezone.localdate())
            else:
                TimelineEvent.objects.create(
                    user=partner_user,
                    timestamp=timezone.now(),
                    event_type=TimelineEventType.ACCOUNTABILITY_INVITE,
                    event=f"{owner_name} invited you as accountability partner for: {habit.habit}",
                    reference={'model': 'AccountabilityPartner', 'id': ap.id},
                    action={'accept': [True, False]},
                )
                site_url = request.build_absolute_uri('/')
                _send_accountability_email(partner_user.email, owner_name, habit.habit, ap.token, site_url)
        else:
            site_url = request.build_absolute_uri('/')
            _send_accountability_email(email, owner_name, habit.habit, ap.token, site_url)

        return Response({'status': 'success', 'data': AccountabilityPartnerSerializer(ap).data}, status=201)

    def destroy(self, request, **kwargs):
        """Habit owner removes a partner."""
        user_id = request.session.get('user_id')
        pk = int(kwargs['pk'])
        ap = self.get_queryset().get(pk=pk, habit__user_id=user_id)
        if ap.partner:
            TimelineEvent.objects.filter(
                user=ap.partner,
                event_type__in=[TimelineEventType.ACCOUNTABILITY_INVITE, TimelineEventType.ACCOUNTABILITY_HABIT],
                reference__model='AccountabilityPartner',
                reference__id=ap.id,
            ).delete()
        ap.delete()
        return Response({'status': 'success', 'message': 'Accountability partner removed'})

    @action(detail=True, methods=['post'])
    def accept(self, request, **kwargs):
        user_id = request.session.get('user_id')
        ap = self.get_queryset().get(pk=int(kwargs['pk']), partner_id=user_id)
        if ap.status != AccountabilityPartnerStatus.REQUEST_SENT:
            return Response({'status': 'failed', 'error': 'Invite already responded to'}, status=400)
        _accept_accountability_invite(ap, user_id)
        update_daily_streak(user_id)
        award_points(user_id, 'achievement')
        return Response({'status': 'success', 'message': 'Accepted'})

    @action(detail=True, methods=['post'])
    def decline(self, request, **kwargs):
        user_id = request.session.get('user_id')
        ap = self.get_queryset().get(pk=int(kwargs['pk']), partner_id=user_id)
        if ap.status != AccountabilityPartnerStatus.REQUEST_SENT:
            return Response({'status': 'failed', 'error': 'Invite already responded to'}, status=400)
        ap.status = AccountabilityPartnerStatus.INACTIVE
        ap.save()
        TimelineEvent.objects.filter(
            user_id=user_id,
            event_type=TimelineEventType.ACCOUNTABILITY_INVITE,
            reference__model='AccountabilityPartner',
            reference__id=ap.id,
        ).update(action=None)
        return Response({'status': 'success', 'message': 'Declined'})

    @action(detail=True, methods=['post'])
    def check(self, request, **kwargs):
        """Return today's habit status for this partnership (partner-only, no side effects)."""
        user_id = request.session.get('user_id')
        ap = self.get_queryset().get(pk=int(kwargs['pk']), partner_id=user_id, status=AccountabilityPartnerStatus.ACTIVE)
        today = timezone.localdate()
        log = HabitLog.objects.filter(habit=ap.habit, date=today).first()
        return Response({
            'status': 'success',
            'data': {
                'habit': ap.habit.habit,
                'date': today.isoformat(),
                'is_done': log.is_done if log else False,
            }
        })

    @action(detail=True, methods=['post'])
    def remind(self, request, **kwargs):
        """Partner sends a reminder to the habit owner."""
        user_id = request.session.get('user_id')
        ap = self.get_queryset().get(pk=int(kwargs['pk']), partner_id=user_id, status=AccountabilityPartnerStatus.ACTIVE)
        partner = User.objects.get(pk=user_id)
        partner_name = partner.get_full_name() or partner.username
        TimelineEvent.objects.create(
            user=ap.habit.user,
            timestamp=timezone.now(),
            event_type=TimelineEventType.ACCOUNTABILITY_HABIT,
            event=f"{partner_name} reminded you to: {ap.habit.habit}",
            reference={'model': 'AccountabilityPartner', 'id': ap.id, 'type': 'reminder'},
            action=None,
        )
        return Response({'status': 'success', 'message': 'Reminder sent'})


class GamificationView(APIView):
    """Return user gamification stats + all achievements (with unlocked status)."""

    def get(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)

        from board.gamification import get_level_info
        ud, _ = UserDetail.objects.get_or_create(user_id=user_id)
        level_num, level_name, threshold, next_threshold = get_level_info(ud.total_points)
        xp_in_level = ud.total_points - threshold
        xp_needed = next_threshold - threshold
        xp_pct = round((xp_in_level / xp_needed) * 100, 1) if xp_needed > 0 else 100.0

        achievements = Achievement.objects.all()
        serializer = AchievementSerializer(achievements, many=True, context={'user_id': user_id})

        return Response({
            'status': 'success',
            'data': {
                'total_points': ud.total_points,
                'level': level_num,
                'level_name': level_name,
                'xp_pct': xp_pct,
                'xp_in_level': xp_in_level,
                'xp_needed': xp_needed,
                'current_streak': ud.current_streak,
                'longest_streak': ud.longest_streak,
                'achievements': serializer.data,
                'unlocked_count': UserAchievement.objects.filter(user_id=user_id).count(),
                'total_count': achievements.count(),
            }
        })


class OnboardingCompleteView(APIView):
    def post(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)
        UserDetail.objects.filter(user_id=user_id).update(is_onboarded=True)
        return Response({'status': 'success'})


def _compute_productivity_score(user_id, target_date, now=None):
    """Compute productivity score for a given date. Returns a dict."""
    from datetime import date as date_type
    weekday = target_date.weekday()
    is_today = target_date == timezone.localdate()

    active_habits = Habit.objects.filter(user_id=user_id, status=HabitStatus.ACTIVE.value)
    habits_due = 0
    habits_done = 0
    for habit in active_habits:
        if habit.frequency and weekday not in habit.frequency:
            continue
        # For today: respect notify_at; for past days: count all scheduled habits
        if is_today and now and habit.notify_at and habit.notify_at > timezone.localtime(now).time():
            pass
        else:
            habits_due += 1
        log = HabitLog.objects.filter(habit=habit, date=target_date, is_done=True).first()
        if log:
            habits_done += 1

    denominator = max(habits_due, habits_done)
    habit_score = (habits_done / denominator * 5) if denominator > 0 else 5.0

    todos_due = Task.objects.filter(user_id=user_id, is_deleted=False, deadline__date=target_date).count()
    todos_done_deadline = Task.objects.filter(user_id=user_id, is_deleted=False, deadline__date=target_date, is_done=True).count()
    todos_done_no_deadline = Task.objects.filter(
        user_id=user_id, is_deleted=False, deadline__isnull=True, is_done=True, updated_at__date=target_date
    ).count()
    total_todos_done = todos_done_deadline + todos_done_no_deadline
    todo_score = (total_todos_done / max(todos_due, total_todos_done) * 2) if max(todos_due, total_todos_done) > 0 else 2.0

    daily_data = DailyData.objects.filter(user_id=user_id, date=target_date).first()
    journal_score = 2.0 if (daily_data and daily_data.journal and daily_data.journal.strip()) else 0.0
    sleep_score = 1.0 if (daily_data and daily_data.sleep_hours is not None) else 0.0

    total = round(habit_score + todo_score + journal_score + sleep_score, 1)
    return {
        'total': total,
        'habit': round(habit_score, 1),
        'todo': round(todo_score, 1),
        'journal': round(journal_score, 1),
        'sleep': round(sleep_score, 1),
        'breakdown': {
            'habits_done': habits_done,
            'habits_due': habits_due,
            'todos_done': total_todos_done,
            'todos_due': todos_due,
            'journaled': bool(journal_score),
            'sleep_logged': bool(sleep_score),
        }
    }


class ProductivityScoreView(APIView):
    """Compute productivity score for today (or a given date via ?date=YYYY-MM-DD)."""

    def get(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)

        now = timezone.now()
        date_param = request.GET.get('date')
        if date_param:
            try:
                target_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            except ValueError:
                return Response({'status': 'failed', 'error': 'Invalid date'}, status=400)
        else:
            target_date = timezone.localdate()

        data = _compute_productivity_score(user_id, target_date, now=now)
        return Response({'status': 'success', 'data': data})


class ProductivityScoreHistoryView(APIView):
    """Return productivity scores for the last N days (default 7)."""

    def get(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)

        from datetime import timedelta
        days = min(int(request.GET.get('days', 7)), 30)
        now = timezone.now()
        today = timezone.localdate()

        history = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            score = _compute_productivity_score(user_id, d, now=(now if i == 0 else None))
            history.append({'date': d.isoformat(), 'score': score['total']})

        return Response({'status': 'success', 'data': history})


def process_invite_token(token_str, user):
    """
    Accept a pending invite (FriendRequest or AccountabilityPartner) identified by token_str
    for the given user.
    Returns 'accepted', 'wrong_user', or 'not_found'.
    """
    import uuid as _uuid
    try:
        token_uuid = _uuid.UUID(token_str)
    except (ValueError, AttributeError):
        return 'not_found'

    freq = FriendRequest.objects.filter(token=token_uuid, status=FriendRequestStatus.PENDING).first()
    if freq:
        if freq.to_user_id and freq.to_user_id != user.id:
            return 'wrong_user'
        if freq.to_user_id is None:
            if freq.invited_email and freq.invited_email.lower() != user.email.lower():
                return 'wrong_user'
            freq.to_user = user
            freq.save()
        _accept_friend_request(freq)
        return 'accepted'

    ap = AccountabilityPartner.objects.filter(token=token_uuid, status=AccountabilityPartnerStatus.REQUEST_SENT).first()
    if ap:
        if ap.partner_id and ap.partner_id != user.id:
            return 'wrong_user'
        if ap.partner_id is None:
            if ap.invited_email and ap.invited_email.lower() != user.email.lower():
                return 'wrong_user'
            ap.partner = user
            ap.save()
        _accept_accountability_invite(ap, user.id)
        return 'accepted'

    return 'not_found'


def accept_invite_by_token(request, token):
    """
    Token-based invite acceptance link used in emails.
    - If the user is logged in: accept immediately and redirect to the app.
    - If not: store the token in session and redirect to the main page so the user
      can log in / sign up via the normal UI. The login signal finishes the acceptance.
    """
    from django.shortcuts import redirect as _redirect

    user_id = request.session.get('user_id') or (request.user.id if request.user.is_authenticated else None)
    if not user_id:
        request.session['pending_invite_token'] = str(token)
        return _redirect('/')

    user = User.objects.get(pk=user_id)
    result = process_invite_token(str(token), user)
    if result == 'accepted':
        return _redirect('/board/?invite_accepted=1#friends')
    if result == 'wrong_user':
        return _redirect('/board/?invite_error=wrong_user#friends')
    return _redirect('/board/#friends')
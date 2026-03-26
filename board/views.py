import os
from datetime import datetime

from django.shortcuts import render, redirect
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from board.models import (
    Task, TaskGroup, DailyData, UserDetail, Habit, HabitStatus, HabitLog,
    RoutineEntry, ReadingListItem, TimelineEvent, SearchEngine
)
from board.serializers import (
    TaskSerializer, TaskGroupSerializer, DailyDataSerializer, UserDetailSerializer, HabitSerializer,
    HabitLogSerializer, RoutineEntrySerializer, ReadingListItemSerializer,
    TimelineEventSerializer, SearchEngineSerializer
)
from main.config_manager import get_config
from main.utils import NoDestroyViewSet, AuthenticatedModelViewSet


# ──────────────────────────────────────
# Page Views
# ──────────────────────────────────────

def dashboard(request):
    """Single unified dashboard view serving all panes."""
    if request.user.is_authenticated:
        configs = get_config().get_all()
        user_detail, _ = UserDetail.objects.get_or_create(user=request.user)
        context = {
            'user_detail': UserDetailSerializer(user_detail).data,
            'host': os.environ.get("HOST", "http://127.0.0.1:8000/"),
        }
        context.update(configs)
        return render(request, 'board/dashboard.html', context=context)
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
            'data': UserDetailSerializer(user_detail).data
        })

    def put(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)
        user_detail, _ = UserDetail.objects.get_or_create(user_id=user_id)
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
        serializer = self.get_serializer(task, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'data': serializer.data,
                'message': 'Task updated successfully',
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
        serializer = self.get_serializer(obj, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'data': serializer.data
            })
        else:
            return Response({
                "status": "failed",
                "error": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)


class HabitViewSet(AuthenticatedModelViewSet):
    serializer_class = HabitSerializer

    def get_queryset(self):
        return Habit.objects.exclude(status=HabitStatus.DELETED.value)

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        habit_status = request.GET.get('status', 'active')
        queryset = self.get_queryset().filter(user_id=user_id, status=habit_status).order_by(
            'notify_at', 'created_at'
        )
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
            if parsed_date > datetime.now().date():
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
        habit_log.is_done = not habit_log.is_done
        habit_log.save()

        return Response({
            'status': 'success',
            'data': HabitLogSerializer(habit_log).data,
            'message': self.get_serializer(habit).data['remark']
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

        created = []
        for entry_data in entries:
            entry_data['routine_type'] = routine_type
            serializer = self.get_serializer(data=entry_data)
            if serializer.is_valid():
                obj = serializer.save(user_id=user_id)
                created.append(serializer.data)

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
        limit = int(request.GET.get('limit', 5))

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
        propagation_result = self._propagate_action(event, action_response)

        return Response({
            'status': 'success',
            'data': self.get_serializer(event).data,
            'propagation': propagation_result
        })

    def _propagate_action(self, event, action_response):
        """Propagate timeline action to the actual source model."""
        ref = event.reference
        if not ref:
            return {'propagated': False, 'reason': 'No reference'}

        model_name = ref.get('model')
        model_id = ref.get('id')

        try:
            if event.event_type == 'habit' and model_name == 'Habit':
                # Toggle habit log for today
                mark_done = action_response.get('mark_done', False)
                today = timezone.now().date()
                habit_log, _ = HabitLog.objects.get_or_create(
                    habit_id=model_id, date=today
                )
                habit_log.is_done = mark_done
                habit_log.save()
                return {'propagated': True, 'model': 'HabitLog', 'is_done': mark_done}

            elif event.event_type == 'todo' and model_name == 'Task':
                mark_done = action_response.get('mark_done', False)
                task = Task.objects.get(pk=model_id)
                task.is_done = mark_done
                task.save()
                return {'propagated': True, 'model': 'Task', 'is_done': mark_done}

            elif event.event_type == 'sleep_tracker':
                # Sleep tracker action — user logs hours via daily data
                return {'propagated': False, 'reason': 'Sleep logged via daily_data API'}

            elif event.event_type == 'journal':
                return {'propagated': False, 'reason': 'Journal edited via daily_data API'}

            elif event.event_type == 'meeting':
                # Meeting join is handled client-side (opens URL)
                return {'propagated': False, 'reason': 'Client-side action'}

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


class ProductivityScoreView(APIView):
    """
    Compute productivity score for today.
    Habit: 5 pts, Todo: 2 pts, Journal: 2 pts, Sleep: 1 pt = 10 total
    """

    def get(self, request):
        user_id = request.session.get('user_id')
        if not user_id:
            return Response({'status': 'failed', 'error': 'Not authenticated'}, status=401)

        today = timezone.now().date()
        now = timezone.now()
        weekday = today.weekday()

        # ── Habit Score (out of 5) ──
        active_habits = Habit.objects.filter(
            user_id=user_id, status=HabitStatus.ACTIVE.value
        )
        habits_due_now = 0
        habits_done = 0
        for habit in active_habits:
            is_scheduled = not habit.frequency or weekday in habit.frequency
            if not is_scheduled:
                continue
            # Only count habits whose notify_at <= current time (or no notify_at)
            if habit.notify_at is None or habit.notify_at <= now.time():
                habits_due_now += 1
            log = HabitLog.objects.filter(habit=habit, date=today, is_done=True).first()
            if log:
                habits_done += 1

        denominator = max(habits_due_now, habits_done)
        habit_score = (habits_done / denominator * 5) if denominator > 0 else 5.0

        # ── Todo Score (out of 2) ──
        todos_due_today = Task.objects.filter(
            user_id=user_id, is_deleted=False,
            deadline__date=today
        ).count()
        todos_done_today = Task.objects.filter(
            user_id=user_id, is_deleted=False,
            deadline__date=today, is_done=True
        ).count()
        # Also count todos done today that may not have deadline
        todos_done_no_deadline = Task.objects.filter(
            user_id=user_id, is_deleted=False,
            deadline__isnull=True, is_done=True,
            updated_at__date=today
        ).count()
        total_todos_done = todos_done_today + todos_done_no_deadline
        total_todos_denominator = max(todos_due_today, total_todos_done)
        todo_score = (total_todos_done / total_todos_denominator * 2) if total_todos_denominator > 0 else 2.0

        # ── Journal Score (out of 2) ──
        daily_data = DailyData.objects.filter(user_id=user_id, date=today).first()
        journal_score = 2.0 if (daily_data and daily_data.journal and daily_data.journal.strip()) else 0.0

        # ── Sleep Score (out of 1) ──
        sleep_score = 1.0 if (daily_data and daily_data.sleep_hours is not None) else 0.0

        total = round(habit_score + todo_score + journal_score + sleep_score, 1)

        return Response({
            'status': 'success',
            'data': {
                'total': total,
                'habit': round(habit_score, 1),
                'todo': round(todo_score, 1),
                'journal': round(journal_score, 1),
                'sleep': round(sleep_score, 1),
                'breakdown': {
                    'habits_done': habits_done,
                    'habits_due': habits_due_now,
                    'todos_done': total_todos_done,
                    'todos_due': todos_due_today,
                    'journaled': bool(journal_score),
                    'sleep_logged': bool(sleep_score),
                }
            }
        })
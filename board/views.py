import os
from datetime import datetime

from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from board.models import Task, DailyData, UserDetail, Habit, HabitStatus, HabitLog
from board.serializers import TaskSerializer, DailyDataSerializer, UserDetailSerializer, HabitSerializer, \
    HabitLogSerializer
from main.config_manager import get_config
from main.utils import NoDestroyViewSet, AuthenticatedModelViewSet


def board(request):
    if request.user.is_authenticated:
        configs = get_config().get_all()
        user_detail, _ = UserDetail.objects.get_or_create(user=request.user)
        context = {
            'user_detail': UserDetailSerializer(user_detail).data,
            'host': os.environ.get("HOST", "http://127.0.0.1:8000"),
        }

        context.update(configs)
        return render(request, 'board/board.html', context=context)
    else:
        return redirect('/')


class UserDetailView(APIView):
    def get(self, request, *args, **kwargs):
        user_id = request.session.get('user_id')
        data, _ = UserDetail.objects.get_or_create(user_id=user_id)
        serializer = UserDetailSerializer(data)
        return Response({
            "status": 'success',
            "data": serializer.data,
        })

    def put(self, request, *args, **kwargs):
        user_id = request.session.get('user_id')
        user_detail, _ = UserDetail.objects.get_or_create(user_id=user_id)
        serializer = UserDetailSerializer(user_detail, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': "success",
                'data': serializer.data,
                'message': 'Successfully updated',
            })
        return Response({
            'status': "failed",
            'error': serializer.errors,
        }, status=status.HTTP_400_BAD_REQUEST)


class TaskViewSet(AuthenticatedModelViewSet):
    serializer_class = TaskSerializer

    def get_queryset(self):
        return Task.objects.filter(is_deleted=False)

    def list(self, request, **kwargs):
        user_id = request.session.get('user_id')
        queryset = self.get_queryset().filter(user_id=user_id)
        data = self.get_serializer(queryset, many=True).data
        return Response({
            'status': 'success',
            'data': data,
        })

    def create(self, request, **kwargs):
        print(request.user, request.session.get('user_id'))
        task_name = request.data.get('task_name')
        serializer = self.get_serializer(data={'task_name': task_name}, partial=True)
        if serializer.is_valid():
            serializer.save(
                user_id=request.session.get('user_id'),
            )
            return Response({
                'status': 'success',
                'data': serializer.data,
            })
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
        elif end_date:
            queryset = self.get_queryset().filter(user_id=user_id, date__lte=end_date)
        else:
            queryset = self.get_queryset().filter(user_id=user_id)

        data = self.get_serializer(queryset, many=True).data
        return Response({
            'status': 'success',
            'data': data
        })

    def retrieve(self, request, **kwargs):
        user_id = request.session.get('user_id')
        date = kwargs.get('pk')
        try:
            date = datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return Response({'status': 'failed', 'error': 'Invalid Date'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = self.get_queryset().get(user_id=user_id, date=date)
        except DailyData.DoesNotExist:
            if date > datetime.now():
                return Response({'status': 'failed', 'error': 'This date is in future'}, status=status.HTTP_400_BAD_REQUEST)
            data = DailyData.objects.create(date=date, user_id=user_id)

        return Response({
            'status': 'success',
            'data': self.get_serializer(data).data
        })

    def update(self, request, **kwargs):
        user_id = request.session.get('user_id')
        date_str = kwargs.get('pk')
        try:
            date_parsed = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return Response({'status': 'failed', 'error': 'Invalid Date'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = self.get_queryset().get(user_id=user_id, date=date_str)
        except DailyData.DoesNotExist:
            if date_parsed > datetime.now():
                return Response({'status': 'failed', 'error': 'This date is in future'},
                                status=status.HTTP_400_BAD_REQUEST)
            data = DailyData.objects.create(date=date_str, user_id=user_id)

        serializer = self.get_serializer(data, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'data': serializer.data,
                'message': 'Data updated successfully',
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
        queryset = self.get_queryset().filter(user_id=user_id, status=habit_status)
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
        date = request.data.get('date')
        try:
            habit = self.get_queryset().get(pk=habit_id)
        except Habit.DoesNotExist:
            return Response({
                "status": "failed",
                "error": "Habit not found"
            }, status=status.HTTP_404_NOT_FOUND)

        try:
            parse_date = datetime.strptime(date, '%Y-%m-%d')
            if parse_date > datetime.now():
                return Response({'status': 'failed', 'error': 'This date is in future'}, status=status.HTTP_400_BAD_REQUEST)
            if parse_date < habit.created_at.replace(tzinfo=None):
                return Response({
                    "status": "failed",
                    "error": "This date is before the habit creation"
                })
        except ValueError:
            return Response({'status': 'failed', 'error': 'Invalid Date'}, status=status.HTTP_400_BAD_REQUEST)
        habitLog, _ = HabitLog.objects.get_or_create(habit_id=habit_id, date=date)
        habitLog.is_done = False if habitLog.is_done else True
        habitLog.save()


        return Response({
            'status': 'success',
            'data': HabitLogSerializer(habitLog).data,
            'message': self.get_serializer(habit).data['remark']
        })






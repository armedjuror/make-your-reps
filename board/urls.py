from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from board.views import board, TaskViewSet, DailyDataViewSet, UserDetailView, HabitViewSet

api_router = DefaultRouter()
api_router.register(r'tasks', TaskViewSet, basename='tasks')
api_router.register(r'daily_data', DailyDataViewSet, basename='daily_data')
api_router.register(r'habits', HabitViewSet, basename='habits')
urlpatterns = [
    path('', board, name='dashboard'),
    path('api/user_details/', UserDetailView.as_view(), name='user-details'),
    path('api/', include(api_router.urls)),
]

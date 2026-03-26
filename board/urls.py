from django.urls import path, include
from rest_framework.routers import DefaultRouter

from board.views import (
    dashboard, journals,
    TaskViewSet, TaskGroupViewSet, DailyDataViewSet, UserDetailView, HabitViewSet,
    RoutineEntryViewSet, ReadingListItemViewSet, TimelineEventViewSet,
    SearchEngineViewSet, ProductivityScoreView, DashboardConfigView
)

api_router = DefaultRouter()
api_router.register(r'tasks', TaskViewSet, basename='tasks')
api_router.register(r'task_groups', TaskGroupViewSet, basename='task_groups')
api_router.register(r'daily_data', DailyDataViewSet, basename='daily_data')
api_router.register(r'habits', HabitViewSet, basename='habits')
api_router.register(r'routine_entries', RoutineEntryViewSet, basename='routine_entries')
api_router.register(r'reading_list', ReadingListItemViewSet, basename='reading_list')
api_router.register(r'timeline', TimelineEventViewSet, basename='timeline')
api_router.register(r'search_engines', SearchEngineViewSet, basename='search_engines')

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('journals/', journals, name='journals'),
    path('api/user_details/', UserDetailView.as_view(), name='user-details'),
    path('api/dashboard_config/', DashboardConfigView.as_view(), name='dashboard-config'),
    path('api/productivity_score/', ProductivityScoreView.as_view(), name='productivity-score'),
    path('api/', include(api_router.urls)),
]
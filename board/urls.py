from django.urls import path, include
from rest_framework.routers import DefaultRouter

from board.views import (
    dashboard, journals,
    TaskViewSet, TaskGroupViewSet, DailyDataViewSet, UserDetailView, HabitViewSet,
    RoutineEntryViewSet, ReadingListItemViewSet, TimelineEventViewSet,
    SearchEngineViewSet, ProductivityScoreView, ProductivityScoreHistoryView,
    DashboardConfigView, FriendViewSet, FriendRequestViewSet, AccountabilityPartnerViewSet,
    GamificationView, OnboardingCompleteView, FeedbackView,
)
from board.calendar_views import (
    CalendarAuthView, CalendarCallbackView, CalendarListView,
    CalendarRefreshView, CalendarUpdateView, CalendarDisconnectView,
    calendar_webhook,
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
api_router.register(r'friends', FriendViewSet, basename='friends')
api_router.register(r'friend_requests', FriendRequestViewSet, basename='friend_requests')
api_router.register(r'accountability_partners', AccountabilityPartnerViewSet, basename='accountability_partners')

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('journals/', journals, name='journals'),
    path('api/user_details/', UserDetailView.as_view(), name='user-details'),
    path('api/dashboard_config/', DashboardConfigView.as_view(), name='dashboard-config'),
    path('api/productivity_score/', ProductivityScoreView.as_view(), name='productivity-score'),
    path('api/productivity_score_history/', ProductivityScoreHistoryView.as_view(), name='productivity-score-history'),
    path('api/gamification/', GamificationView.as_view(), name='gamification'),
    path('api/onboarding_complete/', OnboardingCompleteView.as_view(), name='onboarding-complete'),
    path('api/feedback/', FeedbackView.as_view(), name='feedback'),
    # Google Calendar integration
    path('api/calendar/auth/', CalendarAuthView.as_view(), name='calendar-auth'),
    path('api/calendar/callback/', CalendarCallbackView.as_view(), name='calendar-callback'),
    path('api/calendar/accounts/', CalendarListView.as_view(), name='calendar-accounts'),
    path('api/calendar/accounts/<int:token_id>/refresh/', CalendarRefreshView.as_view(), name='calendar-refresh'),
    path('api/calendar/accounts/<int:token_id>/disconnect/', CalendarDisconnectView.as_view(), name='calendar-disconnect'),
    path('api/calendar/calendars/<int:cal_id>/', CalendarUpdateView.as_view(), name='calendar-update'),
    path('api/calendar/webhook/<int:cal_id>/', calendar_webhook, name='calendar-webhook'),
    path('api/', include(api_router.urls)),
]
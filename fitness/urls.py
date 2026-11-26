from django.urls import path

from fitness import workout_views as wv
from fitness.views import CalendarView, DayView, ExerciseListView, ExerciseView, OnboardingView, OverviewView, TickView

urlpatterns = [
    path('overview/', OverviewView.as_view(), name='fitness-overview'),
    path('calendar/', CalendarView.as_view(), name='fitness-calendar'),
    path('days/<str:date>/', DayView.as_view(), name='fitness-day'),
    path('exercises/', ExerciseListView.as_view(), name='fitness-exercises'),
    path('exercises/<str:pk>/', ExerciseView.as_view(), name='fitness-exercise'),
    path('workouts/start/', wv.WorkoutStartView.as_view(), name='workout-start'),
    path('workouts/active/', wv.WorkoutActiveView.as_view(), name='workout-active'),
    path('workouts/skip/', wv.WorkoutSkipView.as_view(), name='workout-skip'),
    path('workouts/plan/', wv.WorkoutPlanView.as_view(), name='workout-plan'),
    path('workouts/log/', wv.WorkoutManualLogView.as_view(), name='workout-log'),
    path('workouts/<int:pk>/state/', wv.WorkoutStateView.as_view(), name='workout-state'),
    path('workouts/<int:pk>/sets/', wv.WorkoutSetView.as_view(), name='workout-sets'),
    path('workouts/<int:pk>/finish/', wv.WorkoutFinishView.as_view(), name='workout-finish'),
    path('onboarding/', OnboardingView.as_view(), name='fitness-onboarding'),
    path('ticks/', TickView.as_view(), name='fitness-ticks'),
    path('pain/', wv.PainView.as_view(), name='fitness-pain'),
]

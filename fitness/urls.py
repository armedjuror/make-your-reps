from django.urls import path

from fitness.views import CalendarView, DayView, ExerciseListView, ExerciseView, OverviewView

urlpatterns = [
    path('overview/', OverviewView.as_view(), name='fitness-overview'),
    path('calendar/', CalendarView.as_view(), name='fitness-calendar'),
    path('days/<str:date>/', DayView.as_view(), name='fitness-day'),
    path('exercises/', ExerciseListView.as_view(), name='fitness-exercises'),
    path('exercises/<str:pk>/', ExerciseView.as_view(), name='fitness-exercise'),
]

from django.urls import path

from focus.views import FocusActionView, FocusActiveView, FocusStartView

urlpatterns = [
    path('sessions/', FocusStartView.as_view(), name='focus-start'),
    path('sessions/active/', FocusActiveView.as_view(), name='focus-active'),
    path('sessions/<int:pk>/', FocusActionView.as_view(), name='focus-state'),
    path('sessions/<int:pk>/<str:action>/', FocusActionView.as_view(), name='focus-action'),
]

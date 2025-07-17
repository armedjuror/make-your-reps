from django.contrib import admin
from django.urls import path, include

from main.views import index, logout_view, refresh

urlpatterns = [
    path('', index, name='index'),
    path('refresh/', refresh, name='refresh_token'),
    path('logout/', logout_view, name='logout'),
]
from django.urls import path

from board.views import accept_invite_by_token
from main.views import index, logout_view, refresh, privacy_policy, manifest, release_log, delete_account

urlpatterns = [
    path('', index, name='index'),
    path('privacy-policy', privacy_policy, name='privacy-policy'),
    path('refresh/', refresh, name='refresh_token'),
    path('logout/', logout_view, name='logout'),
    path('manifest.json', manifest, name='manifest'),
    path('release-log', release_log, name='release-log'),
    path('delete-account/', delete_account, name='delete-account'),
    path('accept-invite/<uuid:token>/', accept_invite_by_token, name='accept-invite'),
]
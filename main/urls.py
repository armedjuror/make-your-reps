from django.urls import path

from board.views import accept_invite_by_token
from main.views import index, logout_view, refresh, privacy_policy, manifest, release_log, delete_account, unsubscribe, \
    internal_dashboard, assetlinks, ext_auth_success, ext_auth_logout

urlpatterns = [
    path('', index, name='index'),
    path('privacy-policy', privacy_policy, name='privacy-policy'),
    path('refresh/', refresh, name='refresh_token'),
    path('logout/', logout_view, name='logout'),
    path('manifest.json', manifest, name='manifest'),
    path('release-log', release_log, name='release-log'),
    path('delete-account/', delete_account, name='delete-account'),
    path('accept-invite/<uuid:token>/', accept_invite_by_token, name='accept-invite'),
    path('unsubscribe/<uuid:token>/', unsubscribe, name='unsubscribe'),
    path('internal/', internal_dashboard, name='internal-dashboard'),
    path('.well-known/assetlinks.json', assetlinks),
    path('ext-auth/success/', ext_auth_success, name='ext-auth-success'),
    path('ext-auth/logout/', ext_auth_logout, name='ext-auth-logout'),
]
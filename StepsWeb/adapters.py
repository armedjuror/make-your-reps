import secrets
from django.core.cache import cache
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

class MobileAwareSocialAdapter(DefaultSocialAccountAdapter):
    def get_login_redirect_url(self, request):
        client_type = request.session.get('client_type')
        if client_type == 'extension':
            return '/ext-auth/success/'
        if 'MakeYourRepsApp' in request.META.get('HTTP_USER_AGENT', ''):
            token = secrets.token_urlsafe(32)
            cache.set(f'mobile_auth_{token}', request.session.session_key, 300)
            return f'makeyourreps://auth?token={token}'
        return '/'
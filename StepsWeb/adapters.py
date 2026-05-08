import secrets
from django.core.cache import cache
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

class MobileAwareSocialAdapter(DefaultSocialAccountAdapter):
    def get_login_redirect_url(self, request):
        # Only change behaviour for Android app requests
        ua = request.META.get('HTTP_USER_AGENT', '')
        print(f"[ADAPTER] User agent: {ua}")
        if 'MakeYourRepsApp' in request.META.get('HTTP_USER_AGENT', ''):
            print("[ADAPTER] Mobile app detected")
            token = secrets.token_urlsafe(32)
            # Store session key against token for 5 minutes
            cache.set(f'mobile_auth_{token}', request.session.session_key, 300)
            return f'makeyourreps://auth?token={token}'
        return '/'
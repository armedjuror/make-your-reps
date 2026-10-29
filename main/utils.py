import hashlib
import secrets
import traceback
from datetime import timedelta, datetime
from functools import wraps

import jwt
from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from rest_framework import mixins, status
from rest_framework.viewsets import GenericViewSet
from user_agents import parse

from main.models import UserAuthToken, ErrorLog, LoginActivity


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

def get_auth_token(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        if not token:
            token = request.COOKIES.get('myrt')
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
        return payload, token
    else:
        return None, None

class RefreshToken:
    @staticmethod
    def generate_raw_token():
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return raw_token, token_hash

    @staticmethod
    def generate_token(user, request, device_id=None):

        raw_token, token_hash = RefreshToken.generate_raw_token()

        user_agent_string = request.META.get('HTTP_USER_AGENT', '')
        user_agent = parse(user_agent_string)

        if not device_id:
            device_id = hashlib.sha256(
                f"{user.id}:{user_agent_string}:{datetime.now().timestamp()}".encode()
            ).hexdigest()

        # Calculate expiration (30 days from now by default)
        expires_at = datetime.now() + timedelta(
            days=getattr(settings, 'AUTH_TOKEN_EXPIRY_DAYS', 30)
        )

        # Create or update token for this device
        token_obj, _ = UserAuthToken.objects.update_or_create(
            user=user,
            device_id=device_id,
            defaults={
                'token_hash': token_hash,
                'expires_at': expires_at,
                'is_active': True,
                'device_name': f"{user_agent.device.family} ({user_agent.os.family})",
                'device_type': user_agent.device.family,
                'os': user_agent.os.family,
                'browser': user_agent.browser.family,
                'ip_address': get_client_ip(request),
            }
        )

        return jwt.encode({
            'user_id': user.id,
            'refresh_token': raw_token,
            'device_id': device_id,
            'type': 'refresh',
        }, settings.JWT_SECRET, algorithm='HS256'), token_obj

    @staticmethod
    def validate_token(token_string):
        try:

            jwt_payload = jwt.decode(token_string, settings.JWT_SECRET, algorithms='HS256')

            if jwt_payload.get('type') != 'refresh':
                return None, None

            user_id = jwt_payload['user_id']
            refresh_token = jwt_payload['refresh_token']
            device_id = jwt_payload['device_id']

            token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

            token = UserAuthToken.objects.select_related('user').get(
                user_id=user_id,
                device_id=device_id,
                token_hash=token_hash,
                is_active=True,
                expires_at__gt=datetime.now()
            )

            # Update last used timestamp
            token.save()  # This triggers auto_now for last_used_at
            return token.user, token

        except (ValueError, UserAuthToken.DoesNotExist):
            return None, None


class AccessToken:
    @staticmethod
    def generate(user, expires_in=15):
        now = datetime.now()
        expires = now + timedelta(seconds=expires_in)
        payload = {
            'exp': expires,
            'iat': now,
            'sub': user.id,
            'type': 'access',
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm='HS256')

    @staticmethod
    def validate(token):
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
            now = datetime.now()
            if payload.get('exp', datetime.now()) > now:
                return payload.get('sub')
            return None
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    @staticmethod
    def refresh(refresh_token):
        user, token_obj = RefreshToken.validate_token(refresh_token)
        if user is None:
            return None
        return AccessToken.generate(user)


def authenticated_only(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.session.get('user_id'):
            return view_func(request, *args, **kwargs)

        return JsonResponse({
            'status':'failed',
            'error': 'Not authenticated'
        }, status=401)

    return wrapper

def handle_exceptions(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Exception as e:
            ErrorLog.objects.create(
                request=dict(request),
                error=str(e),
                traceback=traceback.format_exc(),
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT'),
            )
            traceback.print_exc()
            return JsonResponse({
                'status': 'failed',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return wrapper


@method_decorator([authenticated_only, handle_exceptions], name='dispatch')
class AuthenticatedModelViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    GenericViewSet
):
    pass

@method_decorator([authenticated_only, handle_exceptions], name='dispatch')
class NoDestroyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet
):
    pass

@method_decorator([authenticated_only, handle_exceptions], name='dispatch')
class RetrieveUpdateViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet
):
    pass




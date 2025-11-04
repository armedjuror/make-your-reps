from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt

from main.config_manager import get_config
from main.utils import handle_exceptions


# Create your views here.
def index(request):
    config = get_config()
    context = config.get_all()
    sliding_text_strikethrough = []
    sliding_text = []
    for key, value in context.items():
        if key.startswith('sliding_text_strikethrough'):
            sliding_text_strikethrough.append(value)
        elif key.startswith('sliding_text'):
            sliding_text.append(value)
    context['sliding_text_strikethrough'] = sliding_text_strikethrough
    context['sliding_text'] = sliding_text
    return render(request, 'board/index.html', context=context)

def privacy_policy(request):
    config = get_config()
    context = config.get_all()
    return render(request, 'board/privacy.html', context=context)

@csrf_exempt
@handle_exceptions
def refresh(request):
    if request.session.get('access_token'):
        return JsonResponse({'access_token': request.session.get('access_token')})
    else:
        return JsonResponse({
            'status':'failed',
            'error': 'Not authenticated'
        }, status=401)


def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
    return redirect('/')


def manifest(request):
    """Serve PWA manifest"""
    manifest_data = {
        "name": "Expense Tracker - Split & Settle",
        "short_name": "ExpenseTracker",
        "description": "Split expenses, settle debts, stay organized with friends and family",
        "start_url": "/expenses/",
        "display": "standalone",
        "background_color": "#dcc9ac",
        "theme_color": "#98753f",
        "orientation": "portrait-primary",
        "scope": "/",
        "icons": [
            {
                "src": "/static/images/logo.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/static/images/logo.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ],
        "categories": ["finance", "productivity", "utilities"],
        "lang": "en",
        "dir": "ltr"
    }

    return JsonResponse(manifest_data, content_type='application/manifest+json')

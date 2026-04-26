from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt

from main.config_manager import get_config
from main.models import EmailPreference, ReleaseLog
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


def release_log(request):
    config = get_config()
    context = config.get_all()
    context['releases'] = ReleaseLog.objects.filter(is_public=True)
    return render(request, 'board/release_log.html', context=context)

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


def delete_account(request):
    if not request.user.is_authenticated:
        return redirect('/')
    if request.method == 'POST':
        user = request.user
        logout(request)
        user.delete()
        return redirect('/')
    return redirect('/')


def internal_dashboard(request):
    if not request.user.is_authenticated or not request.user.is_superuser:
        return HttpResponseForbidden()

    total_users = User.objects.filter(is_active=True).exclude(email='').count()
    opted_out_marketing = EmailPreference.objects.filter(marketing_emails=False).count()
    opted_out_announcements = EmailPreference.objects.filter(announcement_emails=False).count()
    prefs_created = EmailPreference.objects.count()
    latest_release = ReleaseLog.objects.order_by('-released_at', '-id').first()

    return render(request, 'internal/dashboard.html', {
        'total_users': total_users,
        'opted_out_marketing': opted_out_marketing,
        'opted_out_announcements': opted_out_announcements,
        'prefs_created': prefs_created,
        'latest_release': latest_release,
    })


def unsubscribe(request, token):
    try:
        pref = EmailPreference.objects.select_related('user').get(token=token)
    except EmailPreference.DoesNotExist:
        raise Http404

    saved = False
    if request.method == 'POST':
        pref.marketing_emails = 'marketing_emails' in request.POST
        pref.announcement_emails = 'announcement_emails' in request.POST
        pref.save(update_fields=['marketing_emails', 'announcement_emails', 'updated_at'])
        saved = True

    return render(request, 'emails/unsubscribe.html', {
        'pref': pref,
        'saved': saved,
        'site_url': 'https://makeyourreps.com',
    })


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

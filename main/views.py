from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt

from main.config_manager import get_config
from main.models import AnnouncementLog, EmailPreference, ExtensionUninstallFeedback, ReleaseLog, UninstallReason
from main.utils import get_client_ip, handle_exceptions


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


def ext_auth_success(request):
    return render(request, 'board/ext_auth_success.html')


@csrf_exempt
def ext_auth_logout(request):
    # Invalidate the refresh token in DB if provided
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        token_string = auth_header.split(' ', 1)[1]
        from main.utils import RefreshToken
        user, token_obj = RefreshToken.validate_token(token_string)
        if token_obj:
            token_obj.is_active = False
            token_obj.save(update_fields=['is_active'])

    # Flush the Django session so sessionid cookie becomes invalid
    logout(request)

    response = JsonResponse({'status': 'ok'})
    response.delete_cookie('myrt')
    response.delete_cookie('sessionid')
    return response


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

    from django.db.models import Count

    total_users = User.objects.filter(is_active=True).exclude(email='').count()
    opted_out_marketing = EmailPreference.objects.filter(marketing_emails=False).count()
    opted_out_announcements = EmailPreference.objects.filter(announcement_emails=False).count()
    prefs_created = EmailPreference.objects.count()
    latest_release = ReleaseLog.objects.order_by('-released_at', '-id').first()
    recent_announcements = AnnouncementLog.objects.select_related('release', 'sent_by')[:8]

    uninstall_total = ExtensionUninstallFeedback.objects.count()
    uninstall_by_reason = (
        ExtensionUninstallFeedback.objects
        .values('reason')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    reason_display = dict(UninstallReason.choices)
    uninstall_reasons = [
        {'reason': r['reason'], 'label': reason_display.get(r['reason'], r['reason'] or 'No reason selected'), 'count': r['count']}
        for r in uninstall_by_reason
    ]
    recent_uninstalls = ExtensionUninstallFeedback.objects.exclude(comment='')[:10]

    return render(request, 'internal/dashboard.html', {
        'total_users': total_users,
        'opted_out_marketing': opted_out_marketing,
        'opted_out_announcements': opted_out_announcements,
        'prefs_created': prefs_created,
        'latest_release': latest_release,
        'recent_announcements': recent_announcements,
        'uninstall_total': uninstall_total,
        'uninstall_reasons': uninstall_reasons,
        'recent_uninstalls': recent_uninstalls,
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


@csrf_exempt
def extension_uninstall_feedback(request):
    submitted = False
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        comment = request.POST.get('comment', '')[:1000]
        version = request.POST.get('version', '')[:16]
        valid_reasons = {k for k, _ in UninstallReason.choices}
        ExtensionUninstallFeedback.objects.create(
            reason=reason if reason in valid_reasons else '',
            comment=comment,
            extension_version=version,
            ip_address=get_client_ip(request),
        )
        submitted = True

    return render(request, 'board/extension_uninstall.html', {
        'reasons': UninstallReason.choices,
        'submitted': submitted,
        'version': request.GET.get('v', ''),
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


def assetlinks(request):
    data = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": "com.makeyourreps.app",
            "sha256_cert_fingerprints": [
                "C2:B3:9C:22:47:DF:C9:32:C6:EF:EA:93:29:C1:4C:46:CB:67:FD:0F:D9:4B:FC:25:F3:24:51:9A:B0:AC:62:53"
            ]
        }
    }]
    return JsonResponse(data, safe=False)
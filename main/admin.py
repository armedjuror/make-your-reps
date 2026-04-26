from django import forms
from django.contrib import admin, messages
from django.contrib.admin import register
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import path
from django.utils import timezone
from django.conf import settings

from main.models import Config, EmailPreference, ErrorLog, LoginActivity, ReleaseLog


# Register your models here.
@register(Config)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ('key', 'value')
    search_fields = ('key', 'value')

@register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'request', 'ip_address', 'user_agent', 'error', 'status')
    search_fields = ('error', 'ip_address')
    list_filter = ('status',)
    list_editable = ('status',)

    def has_add_permission(self, request):
        return False

@register(LoginActivity)
class LoginActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'timestamp', 'action', 'status', 'ip_address', 'user_agent')
    search_fields = ('user', 'ip_address')
    list_filter = ('action',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ReleaseAnnouncementForm(forms.Form):
    custom_message = forms.CharField(
        label='Message body',
        widget=forms.Textarea(attrs={'rows': 8, 'cols': 70}),
        help_text='Shown in the email body. Plain text; line breaks are preserved.',
    )
    cta_label = forms.CharField(
        label='CTA button label',
        max_length=80,
        initial='See What\'s New',
    )
    cta_url = forms.URLField(
        label='CTA URL',
        initial='https://makeyourreps.com',
    )
    test_email = forms.EmailField(
        label='Test send (optional)',
        required=False,
        help_text='If set, sends only to this address and skips the full send. Use to preview before sending to everyone.',
    )


class TestReengagementForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('username'),
        required=False,
        label='Use real user',
        help_text=(
            'Select a user to pull their real last-login date and name. '
            'Leave empty to fill in values manually below.'
        ),
        widget=forms.Select(attrs={'style': 'width:320px;'}),
    )
    test_email = forms.EmailField(
        label='Send to',
        help_text='Address the test email is delivered to (independent of the selected user).',
    )
    first_name = forms.CharField(
        label='Preview name (manual)',
        max_length=50,
        required=False,
        initial='there',
        help_text='Ignored when a user is selected above.',
    )
    days_away = forms.IntegerField(
        label='Days away (manual)',
        required=False,
        initial=10,
        min_value=1,
        help_text='Ignored when a user is selected above.',
    )

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get('user')
        if not user:
            if not cleaned.get('first_name'):
                self.add_error('first_name', 'Required when no user is selected.')
            if not cleaned.get('days_away'):
                self.add_error('days_away', 'Required when no user is selected.')
        return cleaned


@register(EmailPreference)
class EmailPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'marketing_emails', 'announcement_emails', 'updated_at')
    list_filter = ('marketing_emails', 'announcement_emails')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('token', 'updated_at')

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['test_reengagement_url'] = 'test-reengagement/'
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'test-reengagement/',
                self.admin_site.admin_view(self.test_reengagement_view),
                name='emailpreference_test_reengagement',
            ),
        ]
        return custom + urls

    def test_reengagement_view(self, request):
        site_url = 'https://makeyourreps.com'
        sent = False

        if request.method == 'POST':
            form = TestReengagementForm(request.POST)
            if form.is_valid():
                from main.models import LoginActivity
                from django.db.models import Max

                selected_user = form.cleaned_data['user']
                test_email = form.cleaned_data['test_email']
                year = timezone.now().year
                login_url = f'{site_url}/login'
                today = timezone.now().date()

                if selected_user:
                    first_name = selected_user.first_name or selected_user.username
                    last_login = (
                        LoginActivity.objects
                        .filter(user=selected_user, action='login', status='success')
                        .aggregate(last=Max('timestamp'))['last']
                    )
                    if last_login:
                        days_away = (today - last_login.date()).days
                    else:
                        days_away = (today - selected_user.date_joined.date()).days
                    pref, _ = EmailPreference.objects.get_or_create(user=selected_user)
                    unsubscribe_url = f'{site_url}/unsubscribe/{pref.token}/'
                else:
                    first_name = form.cleaned_data['first_name']
                    days_away = form.cleaned_data['days_away']
                    unsubscribe_url = f'{site_url}/unsubscribe/00000000-0000-0000-0000-000000000000/'

                html_body = render_to_string('emails/reengagement.html', {
                    'first_name': first_name,
                    'days_away': days_away,
                    'login_url': login_url,
                    'site_url': site_url,
                    'unsubscribe_url': unsubscribe_url,
                    'year': year,
                })
                send_mail(
                    subject='[TEST] Your habits are waiting — come back and make your reps',
                    message=(
                        f"Hey {first_name},\n\n[TEST — {days_away} days away]\n\n"
                        f"Jump back in: {login_url}\n\n"
                        "— The Make Your Reps team"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[test_email],
                    html_message=html_body,
                    fail_silently=False,
                )
                label = f'{selected_user.username} ({days_away} days away)' if selected_user else f'manual ({days_away} days)'
                self.message_user(request, f'Test reengagement email sent to {test_email} using {label}.', level=messages.SUCCESS)
                sent = True
        else:
            form = TestReengagementForm()

        context = {
            **self.admin_site.each_context(request),
            'title': 'Send Test Reengagement Email',
            'form': form,
            'sent': sent,
            'opts': self.model._meta,
        }
        return render(request, 'admin/test_reengagement.html', context)


@register(ReleaseLog)
class ReleaseLogAdmin(admin.ModelAdmin):
    list_display = ('version', 'title', 'release_type', 'released_at', 'is_public')
    list_filter = ('release_type', 'is_public')
    list_editable = ('is_public',)
    search_fields = ('version', 'title', 'description')
    ordering = ('-released_at',)
    actions = ['send_release_announcement']

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:release_id>/send-announcement/',
                self.admin_site.admin_view(self.send_announcement_view),
                name='releaselog_send_announcement',
            ),
        ]
        return custom + urls

    @admin.action(description='Send release announcement email to all users')
    def send_release_announcement(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Please select exactly one release.', level=messages.WARNING)
            return
        release = queryset.first()
        return redirect(f'{release.id}/send-announcement/')

    def send_announcement_view(self, request, release_id):
        release = ReleaseLog.objects.get(pk=release_id)
        site_url = 'https://makeyourreps.com'

        if request.method == 'POST':
            form = ReleaseAnnouncementForm(request.POST)
            if form.is_valid():
                custom_message = form.cleaned_data['custom_message']
                cta_label = form.cleaned_data['cta_label']
                cta_url = form.cleaned_data['cta_url']
                test_email = form.cleaned_data.get('test_email')
                year = timezone.now().year

                def _send(display_name, email, unsubscribe_url, subject_prefix=''):
                    html_body = render_to_string('emails/release_announcement.html', {
                        'subject': f"v{release.version}: {release.title}",
                        'version': release.version,
                        'release_type': release.get_release_type_display(),
                        'title': release.title,
                        'released_at': release.released_at.strftime('%B %-d, %Y'),
                        'first_name': display_name,
                        'custom_message': custom_message,
                        'cta_label': cta_label,
                        'cta_url': cta_url,
                        'site_url': site_url,
                        'unsubscribe_url': unsubscribe_url,
                        'year': year,
                    })
                    send_mail(
                        subject=f"{subject_prefix}v{release.version} is here — {release.title}",
                        message=(
                            f"Hey {display_name},\n\n"
                            f"{custom_message}\n\n"
                            f"{cta_label}: {cta_url}\n\n"
                            "— The Make Your Reps team\n\n"
                            f"Manage email preferences: {unsubscribe_url}"
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        html_message=html_body,
                        fail_silently=True,
                    )

                if test_email:
                    _send(
                        display_name='there',
                        email=test_email,
                        unsubscribe_url=f'{site_url}/unsubscribe/00000000-0000-0000-0000-000000000000/',
                        subject_prefix='[TEST] ',
                    )
                    self.message_user(request, f'Test email sent to {test_email}.', level=messages.SUCCESS)
                else:
                    users = (
                        User.objects
                        .filter(is_active=True)
                        .exclude(email='')
                        .prefetch_related('email_preference')
                    )
                    sent = 0
                    for user in users:
                        pref, _ = EmailPreference.objects.get_or_create(user=user)
                        if not pref.announcement_emails:
                            continue
                        display_name = user.first_name or user.username
                        _send(
                            display_name=display_name,
                            email=user.email,
                            unsubscribe_url=f'{site_url}/unsubscribe/{pref.token}/',
                        )
                        sent += 1

                    self.message_user(
                        request,
                        f"Release announcement for v{release.version} sent to {sent} users.",
                        level=messages.SUCCESS,
                    )
                return redirect('../../')
        else:
            form = ReleaseAnnouncementForm(initial={'cta_url': site_url})

        context = {
            **self.admin_site.each_context(request),
            'title': f'Send announcement: v{release.version} — {release.title}',
            'release': release,
            'form': form,
            'opts': self.model._meta,
        }
        return render(request, 'admin/releaselog_send_announcement.html', context)

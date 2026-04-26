from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone


@shared_task(bind=True, max_retries=2)
def send_release_announcement_task(self, announcement_log_id, release_id, subject, custom_message, cta_label, cta_url):
    """
    Background task: send a release announcement email to all eligible users.
    Updates AnnouncementLog.sent_count when finished.
    """
    from main.models import AnnouncementLog, EmailPreference, ReleaseLog

    try:
        release = ReleaseLog.objects.get(pk=release_id)
    except ReleaseLog.DoesNotExist:
        return f"ReleaseLog {release_id} not found."

    site_url = 'https://makeyourreps.com'
    year = timezone.now().year

    users = User.objects.filter(is_active=True).exclude(email='')
    sent = 0

    for user in users:
        pref, _ = EmailPreference.objects.get_or_create(user=user)
        if not pref.announcement_emails:
            continue

        display_name = user.first_name or user.username
        unsubscribe_url = f'{site_url}/unsubscribe/{pref.token}/'

        html_body = render_to_string('emails/release_announcement.html', {
            'subject': subject,
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
            subject=subject,
            message=(
                f"Hey {display_name},\n\n"
                f"{custom_message}\n\n"
                f"{cta_label}: {cta_url}\n\n"
                "— The Make Your Reps team\n\n"
                f"Manage email preferences: {unsubscribe_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_body,
            fail_silently=True,
        )
        sent += 1

    AnnouncementLog.objects.filter(pk=announcement_log_id).update(sent_count=sent)
    return f"Announcement sent to {sent} users."

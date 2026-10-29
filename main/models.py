# Create your models here.
import uuid

from django.contrib.auth.models import User
from django.db import models
from django.db.models import TextChoices


class Config(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key

class UserAuthToken(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auth_tokens')
    token_hash = models.CharField(max_length=64)  # SHA-256 hash
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    device_id = models.CharField(max_length=64, unique=True)  # Unique identifier for each device
    device_name = models.CharField(max_length=100)  # Human-readable device name
    device_type = models.CharField(max_length=50)  # Mobile, tablet, desktop, etc.
    os = models.CharField(max_length=50)  # Operating system
    browser = models.CharField(max_length=50)  # Browser name
    app_version = models.CharField(max_length=50, null=True)  # Mobile app version if applicable
    ip_address = models.GenericIPAddressField()

    class Meta:
        # Ensure user can have multiple active tokens
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'device_id'],
                condition=models.Q(is_active=True),
                name='unique_active_device_token'
            )
        ]


class LoginActivity(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_activities')
    auth_token = models.ForeignKey(UserAuthToken, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20, choices=[
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('token_refresh', 'Token Refresh'),
    ])
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    status = models.CharField(max_length=20, choices=[
        ('success', 'Success'),
        ('failed', 'Failed'),
    ])

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Login Activities'


class ErrorStatus(TextChoices):
    open = 'open'
    solved = 'solved'
    ignored = 'ignored'


class ErrorLog(models.Model):
    id = models.AutoField(primary_key=True)
    request = models.TextField()
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    error = models.TextField()
    traceback = models.TextField()
    status = models.CharField(max_length=20, choices=ErrorStatus.choices, default=ErrorStatus.open)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class EmailPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_preference')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    marketing_emails = models.BooleanField(default=True, help_text='Re-engagement / habit reminder emails')
    announcement_emails = models.BooleanField(default=True, help_text='Product updates and release announcements')
    last_reengagement_sent = models.DateField(null=True, blank=True, default=None)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user} — email prefs'


class ReleaseType(TextChoices):
    major = 'major', 'Major'
    minor = 'minor', 'Minor'
    patch = 'patch', 'Patch'
    hotfix = 'hotfix', 'Hotfix'


class ReleaseLog(models.Model):
    id = models.AutoField(primary_key=True)
    version = models.CharField(max_length=32)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    release_type = models.CharField(max_length=16, choices=ReleaseType.choices, default=ReleaseType.minor)
    released_at = models.DateField()
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-released_at', '-id']

    def __str__(self):
        return f'v{self.version} — {self.title}'


class UninstallReason(TextChoices):
    not_useful = 'not_useful', "Wasn't useful enough"
    too_slow    = 'too_slow',  'Made browser too slow'
    privacy     = 'privacy',   'Privacy concerns'
    accidental  = 'accidental','Installed by accident'
    switching   = 'switching', 'Switching to another tool'
    other       = 'other',     'Other'


class ExtensionUninstallFeedback(models.Model):
    reason = models.CharField(max_length=20, choices=UninstallReason.choices, blank=True)
    comment = models.TextField(blank=True)
    extension_version = models.CharField(max_length=16, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.get_reason_display() or "No reason"} — {self.submitted_at:%Y-%m-%d}'


class AnnouncementLog(models.Model):
    AUDIENCE_TEST = 'test'
    AUDIENCE_ALL = 'all'
    AUDIENCE_SPECIFIC = 'specific'
    AUDIENCE_CHOICES = [
        (AUDIENCE_TEST, 'Test'),
        (AUDIENCE_ALL, 'All Users'),
        (AUDIENCE_SPECIFIC, 'Specific Emails'),
    ]

    release = models.ForeignKey(ReleaseLog, on_delete=models.SET_NULL, null=True, blank=True, related_name='announcement_logs')
    subject = models.CharField(max_length=255)
    audience = models.CharField(max_length=8, choices=AUDIENCE_CHOICES)
    test_recipient = models.TextField(blank=True, help_text='Email address(es) used for test or specific sends')
    sent_count = models.PositiveIntegerField(default=0)
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='announcement_logs')
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.subject} — {self.sent_at:%Y-%m-%d %H:%M}'

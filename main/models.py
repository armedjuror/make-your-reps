# Create your models here.
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


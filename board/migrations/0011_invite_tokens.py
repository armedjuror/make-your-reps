import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('board', '0010_add_is_onboarded'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # FriendRequest: make to_user nullable
        migrations.AlterField(
            model_name='friendrequest',
            name='to_user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='received_friend_requests',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # FriendRequest: add invited_email
        migrations.AddField(
            model_name='friendrequest',
            name='invited_email',
            field=models.EmailField(blank=True, null=True),
        ),
        # FriendRequest: add token
        migrations.AddField(
            model_name='friendrequest',
            name='token',
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
        # AccountabilityPartner: add token
        migrations.AddField(
            model_name='accountabilitypartner',
            name='token',
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
    ]

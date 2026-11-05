"""Template context shared by every page."""
import os
import time

from django.conf import settings

# Changes on every deploy (or restart), so browsers, Cloudflare and the service
# worker all fetch the new JS and CSS instead of a cached copy. Set ASSET_VERSION
# in the environment (for example to the git commit) to pin it.
_STARTED = str(int(time.time()))


def asset_version(request):
    return {'ASSET_VERSION': getattr(settings, 'ASSET_VERSION', None) or os.environ.get('ASSET_VERSION') or _STARTED}

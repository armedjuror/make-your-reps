# ══════════════════════════════════════════════════════════════════
# DJANGO BACKEND CHANGES FOR CHROME EXTENSION
# ══════════════════════════════════════════════════════════════════
#
# The extension runs on chrome-extension:// origin and needs to:
#   1. Fetch static assets (JS/CSS) from makeyourreps.com
#   2. Make API calls with session cookies via background service worker
#   3. The service worker sends Cookie header manually (can't use credentials: include)
#
# Two changes needed:
#   A) Add CORS middleware to allow cross-origin requests
#   B) Update settings to whitelist the extension
#
# ──────────────────────────────────────
# OPTION 1: Install django-cors-headers (recommended)
# ──────────────────────────────────────
#
#   pip install django-cors-headers
#
#   In settings.py:
#
#   INSTALLED_APPS = [
#       ...
#       'corsheaders',
#       ...
#   ]
#
#   MIDDLEWARE = [
#       'corsheaders.middleware.CorsMiddleware',   # <-- ADD THIS (before CommonMiddleware)
#       'django.middleware.security.SecurityMiddleware',
#       'django.contrib.sessions.middleware.SessionMiddleware',
#       'django.middleware.common.CommonMiddleware',
#       ...
#   ]
#
#   # Allow any chrome-extension origin (they're unique per install)
#   CORS_ALLOWED_ORIGIN_REGEXES = [
#       r"^chrome-extension://.*$",
#   ]
#
#   # Allow credentials (cookies) in cross-origin requests
#   CORS_ALLOW_CREDENTIALS = True
#
#   # Allow these headers from the extension
#   CORS_ALLOW_HEADERS = [
#       'accept',
#       'authorization',
#       'content-type',
#       'cookie',
#       'x-csrftoken',
#       'x-requested-with',
#   ]
#
#
# ──────────────────────────────────────
# OPTION 2: Lightweight custom middleware (no dependency)
# ──────────────────────────────────────
#
# Create: main/middlewares/cors_middleware.py


class ExtensionCorsMiddleware:
    """
    Lightweight CORS middleware that allows Chrome extension origins
    to make cross-origin requests with credentials.

    Add to MIDDLEWARE (before CommonMiddleware):
        'main.middlewares.cors_middleware.ExtensionCorsMiddleware',
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.META.get('HTTP_ORIGIN', '')

        response = self.get_response(request)

        # Only add CORS headers for chrome-extension:// origins
        # and for makeyourreps.com itself (for completeness)
        if origin.startswith('chrome-extension://') or origin in (
            'https://makeyourreps.com',
            'http://localhost:8000',
            'http://127.0.0.1:8000',
        ):
            response['Access-Control-Allow-Origin'] = origin
            response['Access-Control-Allow-Credentials'] = 'true'
            response['Access-Control-Allow-Headers'] = (
                'Accept, Authorization, Content-Type, Cookie, '
                'X-CSRFToken, X-Requested-With'
            )
            response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
            response['Access-Control-Max-Age'] = '86400'

        # Handle preflight
        if request.method == 'OPTIONS' and origin.startswith('chrome-extension://'):
            response.status_code = 200
            response.content = b''

        return response


# ──────────────────────────────────────
# ALSO: Static files CORS
# ──────────────────────────────────────
#
# Your static files (CSS/JS) need to be served with
# Access-Control-Allow-Origin headers so the extension
# can load them as <script src="...">.
#
# If using Nginx, add to the static files location:
#
#   location /static/ {
#       add_header Access-Control-Allow-Origin *;
#       ...
#   }
#
# If using Cloudflare, you can add a Transform Rule or
# use a Page Rule. Or just ensure your static files CDN
# serves with permissive CORS (most do by default).
#
#
# ──────────────────────────────────────
# ALSO: Cookie SameSite for extension
# ──────────────────────────────────────
#
# The extension's background worker sends cookies manually
# in the Cookie header (service workers can't use credentials: include).
# This works because the background script has host_permissions
# for makeyourreps.com and can read cookies via chrome.cookies API.
#
# However, if your session cookie has SameSite=Lax (Django default),
# the server might reject it on cross-origin POST requests.
#
# Fix: In settings.py, set:
#
#   SESSION_COOKIE_SAMESITE = 'None'
#   SESSION_COOKIE_SECURE = True
#   CSRF_COOKIE_SAMESITE = 'None'
#   CSRF_COOKIE_SECURE = True
#
# This is safe because:
#   - Cookies are only sent by the extension (not arbitrary sites)
#   - The extension authenticates via chrome.cookies API which
#     requires explicit host_permissions
#   - HTTPS is enforced via Secure flag
#
# If you don't want to change SameSite globally, the extension
# already works around this by reading cookies via chrome.cookies
# API and sending them as a header, which bypasses SameSite
# restrictions entirely.
#
# ──────────────────────────────────────
# CSRF Exemption for API endpoints
# ──────────────────────────────────────
#
# The extension sends X-CSRFToken header on mutations.
# The background worker reads the csrftoken cookie via
# chrome.cookies API and includes it.
#
# If you're using DRF's SessionAuthentication, CSRF is enforced.
# Since the extension uses JWT (Authorization: Bearer ...),
# CSRF shouldn't be an issue for most endpoints.
#
# If you still hit CSRF errors, you can exempt the API:
#
#   from django.views.decorators.csrf import csrf_exempt
#   # In urls.py for the API router
#   path('api/', csrf_exempt(include(api_router.urls))),
#
# ══════════════════════════════════════════════════════════════════

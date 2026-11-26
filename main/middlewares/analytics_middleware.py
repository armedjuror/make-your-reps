from main.analytics import current_client, detect_client


class AnalyticsClientMiddleware:
    """Tag the request with its client so server-side analytics events carry it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = current_client.set(detect_client(request))
        try:
            return self.get_response(request)
        finally:
            current_client.reset(token)

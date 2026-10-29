from allauth.account.adapter import DefaultAccountAdapter


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        client_type = request.session.get('client_type')
        if client_type == 'extension':
            return '/ext-auth/success/'
        return super().get_login_redirect_url(request)
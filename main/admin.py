from django.contrib import admin
from django.contrib.admin import register

from main.models import Config, ErrorLog, LoginActivity


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

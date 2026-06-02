from django.contrib import admin
from rest_framework_api_key.admin import APIKeyModelAdmin
from rest_framework_api_key.models import APIKey
from .models import UserAPIKey


@admin.register(UserAPIKey)
class UserAPIKeyAdmin(APIKeyModelAdmin):
    # Extend the default admin from djangorestframework-api-key
    list_display = [*APIKeyModelAdmin.list_display, 'user', 'last_used']
    search_fields = [*APIKeyModelAdmin.search_fields, 'user__username', 'user__email']
    list_filter = [*getattr(APIKeyModelAdmin, 'list_filter', ()), 'user', 'last_used']
    list_select_related = ('user',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

# Unregister the default APIKey admin so only the custom UserAPIKey appears
try:
    admin.site.unregister(APIKey)
except Exception:
    pass

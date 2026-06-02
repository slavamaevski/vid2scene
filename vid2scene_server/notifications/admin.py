from django.contrib import admin
from .models import SiteAlert


@admin.register(SiteAlert)
class SiteAlertAdmin(admin.ModelAdmin):
    list_display = ('title', 'alert_type', 'is_active', 'created_at', 'updated_at')
    list_filter = ('alert_type', 'is_active', 'created_at')
    search_fields = ('title', 'message')
    list_editable = ('is_active',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('title', 'message', 'alert_type', 'is_active'),
            'description': 'You can include HTML links in the message. Example: Check out our <a href="https://discord.gg/your-invite" target="_blank">Discord server</a>!'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['activate_alerts', 'deactivate_alerts']
    
    def activate_alerts(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} alerts activated.')
    activate_alerts.short_description = "Activate selected alerts"
    
    def deactivate_alerts(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} alerts deactivated.')
    deactivate_alerts.short_description = "Deactivate selected alerts"

from django.db import models
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


class SiteAlert(models.Model):
    """
    Model to store site-wide alert messages that can be displayed in the header.
    """
    ALERT_TYPES = [
        ('primary', 'Primary (Blue)'),
        ('secondary', 'Secondary (Gray)'),
        ('success', 'Success (Green)'),
        ('danger', 'Danger (Red)'),
        ('warning', 'Warning (Yellow)'),
        ('info', 'Info (Light Blue)'),
        ('light', 'Light'),
        ('dark', 'Dark'),
    ]
    
    title = models.CharField(max_length=100, help_text="Brief title for the alert")
    message = models.TextField(help_text="Alert message content. HTML links are supported: use &lt;a href='https://discord.gg/your-invite' target='_blank'&gt;Join our Discord&lt;/a&gt;")
    alert_type = models.CharField(
        max_length=20,
        choices=ALERT_TYPES,
        default='info',
        help_text="Bootstrap alert type (determines color)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this alert should be displayed"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Site Alert"
        verbose_name_plural = "Site Alerts"
    
    def __str__(self):
        return f"{self.title} ({'Active' if self.is_active else 'Inactive'})"


@receiver([post_save, post_delete], sender=SiteAlert)
def invalidate_site_alerts_cache(sender, instance, **kwargs):
    """
    Signal handler to invalidate the site alerts cache when alerts are modified.
    """
    cache.delete('site_alerts_active')

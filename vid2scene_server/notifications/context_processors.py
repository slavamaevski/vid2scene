from django.core.cache import cache
from .models import SiteAlert


def site_alerts(request):
    """
    Context processor to make active site alerts available in all templates.
    Uses caching to avoid database calls on every request.
    """
    # Cache key for active site alerts
    cache_key = 'site_alerts_active'
    
    # Try to get alerts from cache first
    active_alerts = cache.get(cache_key)
    
    if active_alerts is None:
        # Cache miss - fetch from database
        active_alerts = list(SiteAlert.objects.filter(is_active=True))
        # Cache for 5 minutes (300 seconds)
        cache.set(cache_key, active_alerts, 300)
    
    return {
        'site_alerts': active_alerts
    } 
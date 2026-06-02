from django.conf import settings

def google_settings(request):
    """Adds Google-related settings variables to the context."""
    return {
        'GOOGLE_CLIENT_ID': settings.GOOGLE_CLIENT_ID,
    }

def site_settings(request):
    """Public-facing site identity/integration values for templates."""
    return {
        'contact_email': settings.CONTACT_EMAIL,
        'umami_website_id': settings.UMAMI_WEBSITE_ID,
        'umami_src': settings.UMAMI_SRC,
        'landing_video_base_url': settings.LANDING_VIDEO_BASE_URL,
        'site_url': settings.SITE_URL,
    }

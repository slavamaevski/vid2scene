from .utils import billing_enabled, get_subscription_tier_string, user_can_generate_premium_scene

def subscription_status(request):
    """Make subscription status available to all templates."""
    context = {
        'billing_enabled': billing_enabled(),
        'user_subscription_tier': get_subscription_tier_string(request.user),
        'user_can_generate_premium_scene_web': user_can_generate_premium_scene(request.user, api=False),
        'user_can_generate_premium_scene_api': user_can_generate_premium_scene(request.user, api=True),
    }
    return context
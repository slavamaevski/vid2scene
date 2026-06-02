from functools import wraps
from django.conf import settings
from django.urls import reverse
from django.shortcuts import redirect
from .models import SubscriptionTier


def billing_enabled():
    """Whether the Stripe-backed subscription system is active.

    When disabled (the default for self-hosting) there are no paid tiers, so the
    helpers below grant every user full access and the credit/refund machinery
    stays inert.
    """
    return getattr(settings, 'BILLING_ENABLED', False)


def pro_required(view_func):
    """Decorator that checks for pro subscription"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not billing_enabled():
            return view_func(request, *args, **kwargs)
        if not hasattr(request.user, 'subscription') or not request.user.subscription.check_and_update_pro_active():
            return redirect(reverse('subscribe'))  # Redirect to subscription page
        return view_func(request, *args, **kwargs)
    return wrapper

def is_pro_user(user):
    """Check if user has active pro subscription"""
    if not billing_enabled():
        return True
    if not hasattr(user, 'subscription'):
        return False
    return user.subscription.check_and_update_pro_active()


def is_enterprise_user(user):
    """Check if user has an active Enterprise subscription.

    Enterprise is managed manually, so we only check that the user has a
    subscription record, the tier is ENTERPRISE, and it is marked active.
    """
    if not billing_enabled():
        return True
    if not hasattr(user, 'subscription'):
        return False
    subscription = user.subscription
    return bool(subscription.is_active and subscription.tier == SubscriptionTier.ENTERPRISE)

def is_enterprise_perscene_user(user):
    """Check if user has an active Enterprise Per-Scene subscription."""
    # Per-scene is a credit-metered paid tier; without billing nobody is on it
    # (this keeps the credit-consumption / refund paths dormant when self-hosted).
    if not billing_enabled():
        return False
    if not hasattr(user, 'subscription'):
        return False
    subscription = user.subscription
    return bool(subscription.is_active and subscription.tier == SubscriptionTier.ENTERPRISE_PERSCENE)


def get_subscription_tier_string(user):
    """Get the subscription tier for a user"""
    if not billing_enabled():
        # Self-host: treat everyone as the top tier so all features unlock and
        # the various `.startswith('enterprise')` access checks pass.
        return "enterprise"
    if is_pro_user(user):
        return "pro"
    elif is_enterprise_user(user):
        return "enterprise"
    elif is_enterprise_perscene_user(user):
        return "enterprise_perscene"
    else:
        return "free"


def user_can_generate_premium_scene(user, api=False):
    """
    Check if user can generate premium scenes.
    
    Args:
        user: Django User object
        api: Boolean - True for API usage, False for web usage
    
    Logic:
        - Free users: No for both API and web
        - Pro users: Yes for web, No for API  
        - Enterprise users: Yes for both web and API
        - Enterprise per-scene users: Yes for both IF they have credits, No for both if no credits
    """
    if not billing_enabled():
        return True  # Self-host: premium features available to everyone
    if not hasattr(user, 'subscription'):
        return False  # Free users - no for both
    
    subscription = user.subscription
    
    if is_pro_user(user):
        return not api  # Yes for web (api=False), No for API (api=True)
    
    elif is_enterprise_user(user):
        return True  # Yes for both web and API
    
    elif is_enterprise_perscene_user(user):
        # Yes for both if they have credits, No for both if no credits
        return subscription.api_credits_remaining > 0
    
    else:
        return False  # Free users - no for both
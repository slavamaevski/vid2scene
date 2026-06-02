from rest_framework import permissions
from rest_framework.authentication import get_authorization_header
from subscriptions.utils import get_subscription_tier_string

class IsOwnerOrAdminOrAnonymousForUnowned(permissions.BasePermission):
    """
    Custom permission that allows:
    - Owners of an object to edit their own objects
    - Admin users (superusers) to edit any object
    - Anonymous users to edit ONLY objects with no owner
    """

    def has_object_permission(self, request, view, obj):
        # Allow if user is superuser
        if request.user.is_superuser:
            return True
            
        # Allow if object has no owner (anonymous object)
        if obj.user is None:
            return True
            
        # Allow if user is the owner
        return obj.user == request.user

    def has_permission(self, request, view):
        return True


class APIKeyEnterpriseOnly(permissions.BasePermission):
    """Require an API key and Enterprise (or superuser)."""

    message = "Enterprise API key required."

    def has_permission(self, request, view):
        auth_header = get_authorization_header(request).decode('utf-8') if request else ''
        if not auth_header.startswith('Api-Key '):
            return False
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
           return True
        is_enterprise = get_subscription_tier_string(user).startswith('enterprise')
        return is_enterprise


class NoAPIKeyAllowed(permissions.BasePermission):
    """Block API key authentication - web API only."""

    message = "API keys not allowed. Use session authentication or dev API endpoints."

    def has_permission(self, request, view):
        auth_header = get_authorization_header(request).decode('utf-8') if request else ''
        if auth_header.startswith('Api-Key '):
            return False
        return True

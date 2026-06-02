"""
Simple API key authentication for UserAPIKey model.
"""

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import UserAPIKey


class UserAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Simple API key authentication that sets request.user to the key owner.
    
    Looks for 'Authorization: Api-Key <key>' header and sets request.user
    to the associated user from UserAPIKey model.
    """
    
    def authenticate(self, request):
        """Authenticate request with API key and set user."""
        auth_header = authentication.get_authorization_header(request).decode('utf-8')
        
        if not auth_header.startswith('Api-Key '):
            return None  # Not an API key request
            
        key = auth_header[8:]  # Remove 'Api-Key ' prefix
        if not key:
            return None
            
        try:
            api_key = UserAPIKey.objects.get_from_key(key)
            if api_key.revoked:
                raise exceptions.AuthenticationFailed('API key revoked')
                
            # Update last used timestamp
            api_key.last_used = timezone.now()
            api_key.save(update_fields=['last_used'])
            
            return (api_key.user, api_key)
            
        except UserAPIKey.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid API key')

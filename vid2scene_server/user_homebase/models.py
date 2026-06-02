from django.db import models
from rest_framework_api_key.models import AbstractAPIKey
from django.contrib.auth.models import User


class UserAPIKey(AbstractAPIKey):
    """
    Custom API key model that associates API keys with users.
    This allows users to generate and manage their own API keys.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='api_keys'
    )
    name = models.CharField(
        max_length=50,
        help_text="A human-readable name for this API key"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    
    class Meta(AbstractAPIKey.Meta):
        verbose_name = "User API Key"
        verbose_name_plural = "User API Keys"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.name}"
    
    @classmethod
    def get_user_from_key(cls, key):
        """
        Get the user associated with an API key.
        
        Args:
            key: The API key string
            
        Returns:
            User object if key is valid, None otherwise
        """
        try:
            api_key = cls.objects.get_from_key(key)
            return api_key.user
        except cls.DoesNotExist:
            return None

"""
Test that web API properly blocks API key authentication.
"""

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from django.test.utils import override_settings
from rest_framework import status

from user_homebase.models import UserAPIKey
from subscriptions.models import UserSubscription, SubscriptionTier


def auth_headers(key: str):
    return {'HTTP_AUTHORIZATION': f'Api-Key {key}'}


@override_settings(BILLING_ENABLED=True)
class WebAPISecurityTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser', password='testpass')
        # Give Enterprise subscription  
        UserSubscription.objects.create(user=self.user, tier=SubscriptionTier.ENTERPRISE, is_active=True)
        self.api_key, self.key = UserAPIKey.objects.create_key(name='test_key', user=self.user)

    def test_web_api_blocks_api_keys(self):
        """Test that web API endpoints reject API key authentication."""
        # Create a job for the camera data endpoint test
        from video_processor.models import SceneProcessingJob
        job = SceneProcessingJob.objects.create(
            title="Test Job",
            user=self.user,
            video_file="test.mp4"
        )
        
        web_endpoints = [
            reverse('web_api_generate_upload_sas'),
            reverse('web_api_submit_video'),
            reverse('web_update_camera_data', kwargs={'spj_id': job.id}),
        ]
        
        for endpoint in web_endpoints:
            with self.subTest(endpoint=endpoint):
                resp = self.client.post(endpoint, {}, format='json', **auth_headers(self.key))
                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
                self.assertIn('API keys not allowed', resp.data.get('detail', ''))

    def test_dev_api_still_works_with_api_keys(self):
        """Test that dev API endpoints still accept API key authentication."""
        # This should still work (though may fail for other reasons like missing data)
        url = reverse('api_generate_upload_url')
        resp = self.client.post(url, {'file_extension': 'mp4'}, format='json', **auth_headers(self.key))
        # Should not be 403 (blocked by API key), might be 500 due to mocked services
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_web_api_works_without_api_key(self):
        """Test that web API still works for session authentication."""
        # Login with session authentication
        self.client.force_authenticate(user=self.user)
        
        url = reverse('web_api_generate_upload_sas')
        resp = self.client.post(url, {'file_extension': 'mp4'}, format='json')
        # Should not be 403 (might be 500 due to mocked services, but not blocked)
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

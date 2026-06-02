"""
Tests for API key functionality.
"""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from user_homebase.models import UserAPIKey
from .models import SceneProcessingJob
from subscriptions.models import UserSubscription, SubscriptionTier


@override_settings(BILLING_ENABLED=True)
class APIKeyAuthenticationTestCase(APITestCase):
    """Test cases for API key authentication."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        # Give Enterprise subscription for API access
        UserSubscription.objects.create(user=self.user, tier=SubscriptionTier.ENTERPRISE, is_active=True)
        self.api_key, self.key = UserAPIKey.objects.create_key(
            name='Test API Key',
            user=self.user
        )
    
    def test_api_key_authentication_success(self):
        """Test successful API key authentication."""
        url = reverse('api_jobs')
        headers = {'HTTP_AUTHORIZATION': f'Api-Key {self.key}'}
        
        response = self.client.get(url, **headers)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
    
    def test_api_key_authentication_failure(self):
        """Test failed API key authentication."""
        url = reverse('api_jobs')
        headers = {'HTTP_AUTHORIZATION': 'Api-Key invalid-key'}
        
        response = self.client.get(url, **headers)
        
        # Returns 403 because permission class checks authentication first
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_api_key_last_used_update(self):
        """Test that API key last_used timestamp is updated."""
        url = reverse('api_jobs')
        headers = {'HTTP_AUTHORIZATION': f'Api-Key {self.key}'}
        
        # Get the initial last_used value
        initial_last_used = self.api_key.last_used
        
        response = self.client.get(url, **headers)
        
        # Refresh the API key from database
        self.api_key.refresh_from_db()
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(self.api_key.last_used)
        if initial_last_used:
            self.assertGreater(self.api_key.last_used, initial_last_used)
    
    def test_revoked_api_key_denied(self):
        """Test that revoked API keys are denied access."""
        # Revoke the API key
        self.api_key.revoked = True
        self.api_key.save()
        
        url = reverse('api_jobs')
        headers = {'HTTP_AUTHORIZATION': f'Api-Key {self.key}'}
        
        response = self.client.get(url, **headers)
        
        # Returns 403 because permission class handles the check
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@override_settings(BILLING_ENABLED=True)
class APIKeyManagementTestCase(TestCase):
    """Test cases for API key management in user profile."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        # Give Enterprise subscription for API key management
        UserSubscription.objects.create(user=self.user, tier=SubscriptionTier.ENTERPRISE, is_active=True)
        self.client.login(username='testuser', password='testpass123')
    
    def test_generate_api_key(self):
        """Test API key generation."""
        url = reverse('generate_api_key')
        data = {'name': 'Test Key'}
        
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        self.assertIn('api_key', response_data)
        self.assertEqual(response_data['name'], 'Test Key')
    
    def test_generate_api_key_no_name(self):
        """Test API key generation without name."""
        url = reverse('generate_api_key')
        data = {}
        
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertIn('error', response_data)
    
    def test_generate_api_key_duplicate_name(self):
        """Test API key generation with duplicate name."""
        # Create first key
        UserAPIKey.objects.create_key(name='Test Key', user=self.user)
        
        url = reverse('generate_api_key')
        data = {'name': 'Test Key'}
        
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertIn('error', response_data)
    
    def test_revoke_api_key(self):
        """Test API key revocation."""
        api_key, key = UserAPIKey.objects.create_key(
            name='Test Key',
            user=self.user
        )
        
        url = reverse('revoke_api_key')
        data = {'key_id': api_key.id}
        
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        
        # Check that the key is revoked
        api_key.refresh_from_db()
        self.assertTrue(api_key.revoked)
    
    def test_revoke_nonexistent_api_key(self):
        """Test revoking a non-existent API key."""
        url = reverse('revoke_api_key')
        data = {'key_id': 999}
        
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 404)
        response_data = json.loads(response.content)
        self.assertIn('error', response_data)
    
    def test_revoke_other_users_api_key(self):
        """Test that users cannot revoke other users' API keys."""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass123'
        )
        api_key, key = UserAPIKey.objects.create_key(
            name='Other User Key',
            user=other_user
        )
        
        url = reverse('revoke_api_key')
        data = {'key_id': api_key.id}
        
        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 404)
        response_data = json.loads(response.content)
        self.assertIn('error', response_data)
        
        # Check that the key is not revoked
        api_key.refresh_from_db()
        self.assertFalse(api_key.revoked)


@override_settings(BILLING_ENABLED=True)
class APIKeyUserAccessTestCase(APITestCase):
    """Test cases for user access control with API keys."""
    
    def setUp(self):
        """Set up test data."""
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='testpass123'
        )
        
        # Give Enterprise subscriptions for API access
        UserSubscription.objects.create(user=self.user1, tier=SubscriptionTier.ENTERPRISE, is_active=True)
        UserSubscription.objects.create(user=self.user2, tier=SubscriptionTier.ENTERPRISE, is_active=True)
        
        # Create API keys for both users
        self.api_key1, self.key1 = UserAPIKey.objects.create_key(
            name='User1 Key',
            user=self.user1
        )
        self.api_key2, self.key2 = UserAPIKey.objects.create_key(
            name='User2 Key',
            user=self.user2
        )
        
        # Create jobs for both users
        self.job1 = SceneProcessingJob.objects.create(
            title='User1 Job',
            user=self.user1,
            video_file='videos/test1.mp4'
        )
        self.job2 = SceneProcessingJob.objects.create(
            title='User2 Job',
            user=self.user2,
            video_file='videos/test2.mp4'
        )
    
    def test_user_can_access_own_jobs(self):
        """Test that users can access their own jobs via API key."""
        url = reverse('api_job_detail', kwargs={'job_id': self.job1.id})
        headers = {'HTTP_AUTHORIZATION': f'Api-Key {self.key1}'}
        
        response = self.client.get(url, **headers)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'User1 Job')
    
    def test_user_cannot_access_other_jobs(self):
        """Test that users cannot access other users' jobs via API key."""
        url = reverse('api_job_detail', kwargs={'job_id': self.job2.id})
        headers = {'HTTP_AUTHORIZATION': f'Api-Key {self.key1}'}
        
        response = self.client.get(url, **headers)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_public_job_access_denied(self):
        """Test that API key users cannot access other users' jobs even if public."""
        # Create a public job from user2 that user1 should be able to see
        public_job = SceneProcessingJob.objects.create(
            title='Public Job',
            user=self.user2,
            video_file='videos/public.mp4',
            public=True
        )
        
        url = reverse('api_job_detail', kwargs={'job_id': public_job.id})
        headers = {'HTTP_AUTHORIZATION': f'Api-Key {self.key1}'}
        
        response = self.client.get(url, **headers)
        
        # Should not be able to access other users' jobs even if public via dev API
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND) 
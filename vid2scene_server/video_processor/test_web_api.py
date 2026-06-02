import json
from django.test import TestCase, Client
from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from unittest.mock import patch, Mock

from subscriptions.models import (
    UserSubscription, SubscriptionTier, RefundRequest, CreditTransaction
)
from .models import SceneProcessingJob


@override_settings(BILLING_ENABLED=True)
class RefundWebAPITests(TestCase):
    """Test refund request web API endpoints"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.subscription = UserSubscription.objects.create(
            user=self.user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=5
        )
        self.scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Test Scene',
            video_file='test.mp4'
        )
        
        # Login user
        self.client.login(username='testuser', password='testpass')
    
    def test_request_refund_failed_job_auto_approval(self):
        """Test requesting refund for failed job gets auto-approved"""
        url = reverse('request_refund', args=[self.scene_job.id])
        
        with patch('video_processor.web_api.find_rq_job_with_queue_name') as mock_find_job, \
             patch('video_processor.web_api.get_status_string') as mock_status:
            
            mock_find_job.return_value = (None, None)
            mock_status.return_value = "Failed"
            
            response = self.client.post(url, {
                'reason': 'FAILURE',
                'notes': 'Job failed to complete'
            })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        self.assertTrue(data['success'])
        self.assertTrue(data['auto_approved'])
        self.assertIn('immediately', data['message'])
        
        # Check refund request was created and approved
        refund_request = RefundRequest.objects.filter(scene_processing_job=self.scene_job).first()
        self.assertIsNotNone(refund_request)
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertTrue(refund_request.auto_approved)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 6)
    
    def test_request_refund_finished_job_manual_review(self):
        """Test requesting refund for finished job requires manual review"""
        url = reverse('request_refund', args=[self.scene_job.id])
        
        with patch('video_processor.web_api.find_rq_job_with_queue_name') as mock_find_job, \
             patch('video_processor.web_api.get_status_string') as mock_status:
            
            mock_find_job.return_value = (None, None)
            mock_status.return_value = "Finished"
            
            response = self.client.post(url, {
                'reason': 'UNSATISFIED',
                'notes': 'Quality is not acceptable'
            })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        self.assertTrue(data['success'])
        self.assertFalse(data['auto_approved'])
        self.assertIn('review', data['message'])
        
        # Check refund request was created but not approved
        refund_request = RefundRequest.objects.filter(scene_processing_job=self.scene_job).first()
        self.assertIsNotNone(refund_request)
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.REQUESTED)
        self.assertFalse(refund_request.auto_approved)
        self.assertEqual(refund_request.customer_notes, 'Quality is not acceptable')
        
        # Check credits were NOT added yet
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 5)
    
    def test_request_refund_duplicate_request(self):
        """Test that duplicate refund requests are rejected"""
        # Create existing refund request
        RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            status=RefundRequest.RefundStatus.REQUESTED
        )
        
        url = reverse('request_refund', args=[self.scene_job.id])
        
        with patch('video_processor.web_api.find_rq_job_with_queue_name') as mock_find_job, \
             patch('video_processor.web_api.get_status_string') as mock_status:
            
            mock_find_job.return_value = (None, None)
            mock_status.return_value = "Finished"
            
            response = self.client.post(url, {
                'reason': 'UNSATISFIED',
                'notes': 'Another complaint'
            })
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        
        self.assertIn('already requested', data['error'])
    
    def test_request_refund_non_enterprise_user(self):
        """Test that non-enterprise users cannot request refunds"""
        # Change user to PRO tier
        self.subscription.tier = SubscriptionTier.PRO
        self.subscription.save()
        
        url = reverse('request_refund', args=[self.scene_job.id])
        
        response = self.client.post(url, {
            'reason': 'FAILURE',
            'notes': 'Job failed'
        })
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        
        self.assertIn('Not eligible', data['error'])
    
    def test_request_refund_unauthenticated(self):
        """Test that unauthenticated users cannot request refunds"""
        self.client.logout()
        
        url = reverse('request_refund', args=[self.scene_job.id])
        
        response = self.client.post(url, {
            'reason': 'FAILURE',
            'notes': 'Job failed'
        })
        
        self.assertEqual(response.status_code, 401)
    
    def test_request_refund_wrong_user(self):
        """Test that users cannot request refunds for other users' jobs"""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass'
        )
        other_job = SceneProcessingJob.objects.create(
            user=other_user,
            title='Other Scene',
            video_file='other.mp4'
        )
        
        url = reverse('request_refund', args=[other_job.id])
        
        response = self.client.post(url, {
            'reason': 'FAILURE',
            'notes': 'Job failed'
        })
        
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        
        self.assertIn('Access denied', data['error'])
    
    def test_request_refund_invalid_job_status(self):
        """Test that refunds cannot be requested for jobs with invalid status"""
        url = reverse('request_refund', args=[self.scene_job.id])
        
        with patch('video_processor.web_api.find_rq_job_with_queue_name') as mock_find_job, \
             patch('video_processor.web_api.get_status_string') as mock_status:
            
            mock_find_job.return_value = (None, None)
            mock_status.return_value = "Processing"
            
            response = self.client.post(url, {
                'reason': 'FAILURE',
                'notes': 'Job is taking too long'
            })
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        
        self.assertIn('Cannot request refund', data['error'])
        self.assertIn('Processing', data['error'])
    
    def test_request_refund_nonexistent_job(self):
        """Test requesting refund for non-existent job"""
        url = reverse('request_refund', args=['00000000-0000-0000-0000-000000000000'])
        
        response = self.client.post(url, {
            'reason': 'FAILURE',
            'notes': 'Job failed'
        })
        
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.content)
        
        self.assertIn('Job not found', data['error'])


@override_settings(BILLING_ENABLED=True)
class AprilTagWebAPITests(TestCase):
    """Test AprilTag calibration feature in web API (Enterprise-only)"""
    
    def setUp(self):
        self.client = Client()
        
        # Create test users with different tiers
        self.free_user = User.objects.create_user(
            username='freeuser',
            email='free@example.com',
            password='testpass'
        )
        
        self.pro_user = User.objects.create_user(
            username='prouser',
            email='pro@example.com',
            password='testpass'
        )
        self.pro_subscription = UserSubscription.objects.create(
            user=self.pro_user,
            tier=SubscriptionTier.PRO,
            is_active=True
        )
        
        self.enterprise_user = User.objects.create_user(
            username='enterpriseuser',
            email='enterprise@example.com',
            password='testpass'
        )
        self.enterprise_subscription = UserSubscription.objects.create(
            user=self.enterprise_user,
            tier=SubscriptionTier.ENTERPRISE,
            is_active=True
        )
        
        self.enterprise_perscene_user = User.objects.create_user(
            username='entperscene',
            email='entperscene@example.com',
            password='testpass'
        )
        self.enterprise_perscene_subscription = UserSubscription.objects.create(
            user=self.enterprise_perscene_user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=10
        )
        
        self.submit_url = reverse('web_api_submit_video')
        
        # Mock the blob validation and Azure storage
        # Use a proper UUID format (36 characters)
        self.blob_name = 'videos/550e8400-e29b-41d4-a716-446655440000.mp4'
        
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_enterprise_user_can_use_apriltag(self, mock_get_queue, mock_validate_blob):
        """Test that Enterprise users can submit jobs with AprilTag calibration"""
        mock_queue = Mock()
        mock_rq_job = Mock()
        mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='enterpriseuser', password='testpass')
        
        response = self.client.post(self.submit_url, 
            json.dumps({
                'title': 'Test Scene with AprilTag',
                'blob_name': self.blob_name,
                'public': False,
                'apriltag_size_mm': 95.6
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Check job was created with apriltag_size_mm
        job = SceneProcessingJob.objects.get(title='Test Scene with AprilTag')
        self.assertEqual(job.apriltag_size_mm, 95.6)
        self.assertEqual(job.user, self.enterprise_user)
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_enterprise_perscene_user_can_use_apriltag(self, mock_get_queue, mock_validate_blob):
        """Test that Enterprise Per-Scene users can submit jobs with AprilTag calibration"""
        mock_queue = Mock()
        mock_rq_job = Mock()
        mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='entperscene', password='testpass')
        
        response = self.client.post(self.submit_url, 
            json.dumps({
                'title': 'Test Scene with AprilTag',
                'blob_name': self.blob_name,
                'public': False,
                'apriltag_size_mm': 55.6
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Check job was created with apriltag_size_mm
        job = SceneProcessingJob.objects.get(title='Test Scene with AprilTag')
        self.assertEqual(job.apriltag_size_mm, 55.6)
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_pro_user_cannot_use_apriltag(self, mock_get_queue, mock_validate_blob):
        """Test that Pro users cannot use AprilTag calibration (gets rejected)"""
        mock_queue = Mock()
        mock_rq_job = Mock()
        mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='prouser', password='testpass')
        
        response = self.client.post(self.submit_url, 
            json.dumps({
                'title': 'Test Scene',
                'blob_name': self.blob_name,
                'public': False,
                'apriltag_size_mm': 95.6
            }),
            content_type='application/json'
        )
        
        # Should succeed but apriltag_size_mm should be stripped
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Check job was created WITHOUT apriltag_size_mm
        job = SceneProcessingJob.objects.get(title='Test Scene')
        self.assertIsNone(job.apriltag_size_mm)
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_free_user_cannot_use_apriltag(self, mock_get_queue, mock_validate_blob):
        """Test that Free users cannot use AprilTag calibration"""
        mock_queue = Mock()
        mock_rq_job = Mock()
        mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='freeuser', password='testpass')
        
        response = self.client.post(self.submit_url, 
            json.dumps({
                'title': 'Test Scene',
                'blob_name': self.blob_name,
                'public': False,
                'apriltag_size_mm': 95.6
            }),
            content_type='application/json'
        )
        
        # Should succeed but apriltag_size_mm should be stripped
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Check job was created WITHOUT apriltag_size_mm
        job = SceneProcessingJob.objects.get(title='Test Scene')
        self.assertIsNone(job.apriltag_size_mm)
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_size_validation_min(self, mock_get_queue, mock_validate_blob):
        """Test that AprilTag size below 1mm is rejected"""
        mock_queue = Mock()
        mock_rq_job = Mock()
        mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='enterpriseuser', password='testpass')
        
        response = self.client.post(self.submit_url, 
            json.dumps({
                'title': 'Test Scene',
                'blob_name': self.blob_name,
                'public': False,
                'apriltag_size_mm': 0.5  # Too small
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('1mm and 1000mm', data['error_message'])
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_size_validation_max(self, mock_get_queue, mock_validate_blob):
        """Test that AprilTag size above 1000mm is rejected"""
        mock_queue = Mock()
        mock_rq_job = Mock()
        mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='enterpriseuser', password='testpass')
        
        response = self.client.post(self.submit_url, 
            json.dumps({
                'title': 'Test Scene',
                'blob_name': self.blob_name,
                'public': False,
                'apriltag_size_mm': 1500.0  # Too large
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('1mm and 1000mm', data['error_message'])
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_size_valid_range(self, mock_get_queue, mock_validate_blob):
        """Test that AprilTag sizes in valid range (1-1000mm) are accepted"""
        mock_queue = Mock()
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='enterpriseuser', password='testpass')
        
        # Test various valid sizes
        test_sizes = [1.0, 10.5, 95.6, 250.0, 999.9, 1000.0]
        
        # Fixed UUIDs for deterministic testing
        test_uuids = [
            '550e8400-e29b-41d4-a716-446655440001',
            '550e8400-e29b-41d4-a716-446655440002',
            '550e8400-e29b-41d4-a716-446655440003',
            '550e8400-e29b-41d4-a716-446655440004',
            '550e8400-e29b-41d4-a716-446655440005',
            '550e8400-e29b-41d4-a716-446655440006',
        ]
        
        for i, size in enumerate(test_sizes):
            # Create a new mock RQ job with unique ID for each iteration
            mock_rq_job = Mock()
            mock_rq_job.id = f'rq{i}'
            mock_queue.enqueue.return_value = mock_rq_job
            
            response = self.client.post(self.submit_url, 
                json.dumps({
                    'title': f'Test Scene {i}',
                    'blob_name': f'videos/{test_uuids[i]}.mp4',
                    'public': False,
                    'apriltag_size_mm': size
                }),
                content_type='application/json'
            )
            
            self.assertEqual(response.status_code, 200, f"Size {size}mm failed")
            
            job = SceneProcessingJob.objects.get(title=f'Test Scene {i}')
            self.assertEqual(job.apriltag_size_mm, size)
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_optional(self, mock_get_queue, mock_validate_blob):
        """Test that AprilTag calibration is optional (can submit without it)"""
        mock_queue = Mock()
        mock_rq_job = Mock()
        mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        self.client.login(username='enterpriseuser', password='testpass')
        
        response = self.client.post(self.submit_url, 
            json.dumps({
                'title': 'Test Scene No AprilTag',
                'blob_name': self.blob_name,
                'public': False
                # No apriltag_size_mm provided
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Check job was created without apriltag_size_mm
        job = SceneProcessingJob.objects.get(title='Test Scene No AprilTag')
        self.assertIsNone(job.apriltag_size_mm)

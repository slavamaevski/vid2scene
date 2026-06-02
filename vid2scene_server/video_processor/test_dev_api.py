"""
Fresh tests for dev_api endpoints (Enterprise API key required).
"""

import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from django.test.utils import override_settings
from rest_framework import status

from user_homebase.models import UserAPIKey
from subscriptions.models import UserSubscription, SubscriptionTier
from .models import SceneProcessingJob


def auth_headers(key: str):
    return {'HTTP_AUTHORIZATION': f'Api-Key {key}'}


@override_settings(BILLING_ENABLED=True)
class DevApiBase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='ent', password='x')
        # Give Enterprise subscription
        UserSubscription.objects.create(user=self.user, tier=SubscriptionTier.ENTERPRISE, is_active=True)
        self.api_key, self.key = UserAPIKey.objects.create_key(name='k', user=self.user)


class GenerateUploadURLTests(DevApiBase):
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.BlobServiceClient')
    def test_generate_upload_url(self, mock_blob_service, mock_generate_sas):
        mock_blob = MagicMock()
        mock_blob_service.from_connection_string.return_value = mock_blob
        mock_blob.account_name = 'acct'
        mock_blob.credential.account_key = 'key'
        mock_blob.url = 'http://127.0.0.1:10000/devstoreaccount1/'
        mock_generate_sas.return_value = 'sas'

        url = reverse('api_generate_upload_url')
        resp = self.client.post(url, {'file_extension': 'mp4'}, format='json', **auth_headers(self.key))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('url', resp.data)
        self.assertIn('blob_name', resp.data)


class SubmitJobTests(DevApiBase):
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.BlobServiceClient')
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_submit_job_success(self, mock_get_queue, mock_generate_sas, mock_blob_service, mock_validate_blob, mock_find_rq):
        mock_queue = MagicMock()
        mock_rq_job = MagicMock(); mock_rq_job.id = 'rq123'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue

        url = reverse('api_submit_job')
        blob = f"videos/{uuid.uuid4()}.mp4"
        data = {'title': 't', 'blob_name': blob, 'public': False}
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(SceneProcessingJob.objects.filter(id=resp.data['job_id']).exists())

    def test_submit_job_requires_enterprise(self):
        # Create a PRO user/key
        pro_user = User.objects.create_user(username='pro', password='x')
        UserSubscription.objects.create(user=pro_user, tier=SubscriptionTier.PRO, is_active=True)
        _, pro_key = UserAPIKey.objects.create_key(name='p', user=pro_user)

        url = reverse('api_submit_job')
        resp = self.client.post(url, {}, format='json', **auth_headers(pro_key))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class JobListTests(DevApiBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('api_jobs')
        # Create jobs for this user and another user
        other = User.objects.create_user(username='o', password='x')
        SceneProcessingJob.objects.create(title='mine', user=self.user, video_file=f'videos/{uuid.uuid4()}.mp4')
        SceneProcessingJob.objects.create(title='other', user=other, video_file=f'videos/{uuid.uuid4()}.mp4')

    def test_list_shows_only_own(self):
        resp = self.client.get(self.url, **auth_headers(self.key))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        titles = [j['title'] for j in resp.data]
        self.assertIn('mine', titles)
        self.assertNotIn('other', titles)


class JobDetailUpdateDeleteTests(DevApiBase):
    def setUp(self):
        super().setUp()
        self.job = SceneProcessingJob.objects.create(title='mine', user=self.user, video_file=f'videos/{uuid.uuid4()}.mp4')

    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    def test_get_job(self, mock_find_rq):
        url = reverse('api_job_detail', kwargs={'job_id': self.job.id})
        resp = self.client.get(url, **auth_headers(self.key))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['title'], 'mine')

    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    def test_patch_job(self, mock_find_rq):
        url = reverse('api_job_detail', kwargs={'job_id': self.job.id})
        resp = self.client.patch(url, {'title': 'new', 'public': True}, format='json', **auth_headers(self.key))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.job.refresh_from_db(); self.assertEqual(self.job.title, 'new')

    def test_delete_job(self):
        url = reverse('api_job_detail', kwargs={'job_id': self.job.id})
        resp = self.client.delete(url, **auth_headers(self.key))
        self.assertIn(resp.status_code, (status.HTTP_204_NO_CONTENT, status.HTTP_200_OK))
        self.assertFalse(SceneProcessingJob.objects.filter(id=self.job.id).exists())


class FileEndpointsTests(DevApiBase):
    def setUp(self):
        super().setUp()
        self.job = SceneProcessingJob.objects.create(title='mine', user=self.user, video_file=f'videos/{uuid.uuid4()}.mp4')

    @patch('video_processor.dev_api.BlobServiceClient')
    @patch('video_processor.dev_api.generate_blob_sas')
    def test_preview_redirects(self, *_):
        # Set preview image so endpoint passes existence checks
        self.job.preview_image = 'previews/x.jpg'
        self.job.save()
        url = reverse('api_job_preview_url', kwargs={'job_id': self.job.id})
        resp = self.client.get(url, **auth_headers(self.key))
        # Should be redirect (302) or 200 with URL depending on local settings; accept any 3xx
        self.assertTrue(200 <= resp.status_code < 400)

    def test_download_file_not_available(self):
        # Test when file doesn't exist (no ply_file set)
        url = reverse('api_job_download_file', kwargs={'job_id': self.job.id, 'file_type': 'ply'})
        resp = self.client.get(url, **auth_headers(self.key))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
    
    @patch('video_processor.dev_api.BlobServiceClient')
    @patch('video_processor.dev_api.generate_blob_sas')
    def test_download_file_redirects(self, mock_generate_sas, mock_blob_service):
        # Test when file exists - should return 302 redirect
        mock_blob = MagicMock()
        mock_blob_service.from_connection_string.return_value = mock_blob
        mock_blob.account_name = 'acct'
        mock_blob.credential.account_key = 'key'
        mock_blob.url = 'http://127.0.0.1:10000/devstoreaccount1/'
        mock_generate_sas.return_value = 'sas_token'
        
        # Set PLY file so endpoint passes existence checks
        self.job.ply_file = 'ply_files/test.ply'
        self.job.save()
        
        url = reverse('api_job_download_file', kwargs={'job_id': self.job.id, 'file_type': 'ply'})
        resp = self.client.get(url, **auth_headers(self.key), follow=False)
        self.assertEqual(resp.status_code, status.HTTP_302_FOUND)
        self.assertIn('Location', resp.headers)
    
    def test_download_file_invalid_type(self):
        # Test invalid file type
        url = reverse('api_job_download_file', kwargs={'job_id': self.job.id, 'file_type': 'invalid'})
        resp = self.client.get(url, **auth_headers(self.key))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class CameraTypeDevApiTests(DevApiBase):
    """Test camera_type parameter in dev API"""
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_submit_job_with_orbital_camera_type(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that jobs can be submitted with camera_type='orbital'"""
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_orbital'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = f'videos/{uuid.uuid4()}.mp4'
        data = {
            'title': 'Test Scene Orbital',
            'blob_name': blob_name,
            'public': False,
            'camera_type': 'orbital'
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('job_id', resp.data)
        
        # Check job was created with camera_data containing cameraType
        job = SceneProcessingJob.objects.get(id=resp.data['job_id'])
        self.assertIsNotNone(job.camera_data)
        self.assertEqual(job.camera_data['cameraType'], 'orbital')
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_submit_job_with_drone_camera_type(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that jobs can be submitted with camera_type='drone'"""
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_drone'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = f'videos/{uuid.uuid4()}.mp4'
        data = {
            'title': 'Test Scene Drone',
            'blob_name': blob_name,
            'public': False,
            'camera_type': 'drone'
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        
        # Check job was created with camera_data containing cameraType
        job = SceneProcessingJob.objects.get(id=resp.data['job_id'])
        self.assertIsNotNone(job.camera_data)
        self.assertEqual(job.camera_data['cameraType'], 'drone')
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_submit_job_without_camera_type(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that jobs can be submitted without camera_type (should be None)"""
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_no_camera'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = f'videos/{uuid.uuid4()}.mp4'
        data = {
            'title': 'Test Scene No Camera Type',
            'blob_name': blob_name,
            'public': False
            # No camera_type provided
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        
        # Check job was created without camera_data
        job = SceneProcessingJob.objects.get(id=resp.data['job_id'])
        self.assertIsNone(job.camera_data)
    
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    def test_submit_job_with_invalid_camera_type(self, mock_validate_blob):
        """Test that invalid camera_type values are rejected"""
        url = reverse('api_submit_job')
        blob_name = f'videos/{uuid.uuid4()}.mp4'
        data = {
            'title': 'Test Scene Invalid',
            'blob_name': blob_name,
            'public': False,
            'camera_type': 'invalid_type'
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('camera_type', resp.data['error_message'].lower())


class AprilTagDevApiTests(DevApiBase):
    """Test AprilTag calibration feature in dev API (Enterprise-only)"""
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_enterprise_api_can_use_apriltag(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that Enterprise API users can submit jobs with AprilTag calibration"""
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_ent_apriltag'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = 'videos/850e8400-e29b-41d4-a716-446655440001.mp4'
        data = {
            'title': 'Test Scene with AprilTag',
            'blob_name': blob_name,
            'public': False,
            'apriltag_size_mm': 95.6
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn('job_id', resp.data)
        
        # Check job was created with apriltag_size_mm
        job = SceneProcessingJob.objects.get(id=resp.data['job_id'])
        self.assertEqual(job.apriltag_size_mm, 95.6)
        self.assertEqual(job.user, self.user)
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_enterprise_perscene_api_can_use_apriltag(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that Enterprise Per-Scene API users can use AprilTag calibration"""
        # Create enterprise per-scene user
        ent_perscene_user = User.objects.create_user(username='entperscene', password='x')
        UserSubscription.objects.create(
            user=ent_perscene_user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=10
        )
        _, ent_perscene_key = UserAPIKey.objects.create_key(name='epskey', user=ent_perscene_user)
        
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_ent_perscene'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = 'videos/850e8400-e29b-41d4-a716-446655440002.mp4'
        data = {
            'title': 'Test Scene with AprilTag',
            'blob_name': blob_name,
            'public': False,
            'apriltag_size_mm': 55.6
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(ent_perscene_key))
        
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        
        # Check job was created with apriltag_size_mm
        job = SceneProcessingJob.objects.get(id=resp.data['job_id'])
        self.assertEqual(job.apriltag_size_mm, 55.6)
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_size_validation_min_api(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that AprilTag size below 1mm is rejected via API"""
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_min_val'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = 'videos/850e8400-e29b-41d4-a716-446655440003.mp4'
        data = {
            'title': 'Test Scene',
            'blob_name': blob_name,
            'public': False,
            'apriltag_size_mm': 0.5  # Too small
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('1mm and 1000mm', resp.data['error_message'])
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_size_validation_max_api(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that AprilTag size above 1000mm is rejected via API"""
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_max_val'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = 'videos/850e8400-e29b-41d4-a716-446655440004.mp4'
        data = {
            'title': 'Test Scene',
            'blob_name': blob_name,
            'public': False,
            'apriltag_size_mm': 1500.0  # Too large
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('1mm and 1000mm', resp.data['error_message'])
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_size_valid_range_api(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that AprilTag sizes in valid range (1-1000mm) are accepted via API"""
        mock_queue = MagicMock()
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        
        # Test various valid sizes
        test_sizes = [1.0, 10.5, 95.6, 250.0, 999.9, 1000.0]
        
        # Fixed UUIDs for deterministic testing
        test_blob_names = [
            'videos/650e8400-e29b-41d4-a716-446655440001.mp4',
            'videos/650e8400-e29b-41d4-a716-446655440002.mp4',
            'videos/650e8400-e29b-41d4-a716-446655440003.mp4',
            'videos/650e8400-e29b-41d4-a716-446655440004.mp4',
            'videos/650e8400-e29b-41d4-a716-446655440005.mp4',
            'videos/650e8400-e29b-41d4-a716-446655440006.mp4',
        ]
        
        for i, size in enumerate(test_sizes):
            # Create a new mock RQ job with unique ID for each iteration
            mock_rq_job = MagicMock()
            mock_rq_job.id = f'rq_api_{i}'
            mock_queue.enqueue.return_value = mock_rq_job
            
            data = {
                'title': f'Test Scene {size}mm',
                'blob_name': test_blob_names[i],
                'public': False,
                'apriltag_size_mm': size
            }
            
            resp = self.client.post(url, data, format='json', **auth_headers(self.key))
            
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED, f"Size {size}mm failed")
            
            # Check job was created with correct apriltag_size_mm
            job = SceneProcessingJob.objects.get(id=resp.data['job_id'])
            self.assertEqual(job.apriltag_size_mm, size)
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    @patch('video_processor.job_creation.django_rq.get_queue')
    def test_apriltag_optional_api(self, mock_get_queue, mock_validate_blob, mock_find_rq):
        """Test that AprilTag calibration is optional via API"""
        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = 'rq_optional_test'
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue
        
        url = reverse('api_submit_job')
        blob_name = 'videos/750e8400-e29b-41d4-a716-446655440000.mp4'
        data = {
            'title': 'Test Scene No AprilTag',
            'blob_name': blob_name,
            'public': False
            # No apriltag_size_mm provided
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(self.key))
        
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        
        # Check job was created without apriltag_size_mm
        job = SceneProcessingJob.objects.get(id=resp.data['job_id'])
        self.assertIsNone(job.apriltag_size_mm)
    
    @patch('video_processor.serializers.find_rq_job_with_queue_name', return_value=(None, None))
    @patch('video_processor.job_creation.validate_blob_age', return_value=True)
    def test_pro_api_cannot_use_apriltag(self, mock_validate_blob, mock_find_rq):
        """Test that Pro API users cannot access dev API (and thus AprilTag)"""
        # Create a PRO user/key (dev API requires Enterprise)
        pro_user = User.objects.create_user(username='proapi', password='x')
        UserSubscription.objects.create(user=pro_user, tier=SubscriptionTier.PRO, is_active=True)
        _, pro_key = UserAPIKey.objects.create_key(name='prokey', user=pro_user)
        
        url = reverse('api_submit_job')
        blob_name = 'videos/850e8400-e29b-41d4-a716-446655440099.mp4'
        data = {
            'title': 'Test Scene',
            'blob_name': blob_name,
            'public': False,
            'apriltag_size_mm': 95.6
        }
        
        resp = self.client.post(url, data, format='json', **auth_headers(pro_key))
        
        # Pro users should not have access to dev API at all
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)



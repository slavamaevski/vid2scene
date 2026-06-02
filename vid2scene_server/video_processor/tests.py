from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from .models import SceneProcessingJob

# Create your tests here.

class UpdateCameraDataTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.other_user = User.objects.create_user(username='otheruser', password='otherpass')
        self.admin_user = User.objects.create_superuser(username='adminuser', password='adminpass')
        
        # Create a job owned by a user
        self.spj = SceneProcessingJob.objects.create(
            title='Test Job',
            video_file='videos/test.mp4',
            user=self.user
        )
        
        # Create an anonymous job (no user)
        self.anonymous_spj = SceneProcessingJob.objects.create(
            title='Anonymous Job',
            video_file='videos/anonymous.mp4',
            user=None
        )
        
        self.url = reverse('update-camera-data', kwargs={'spj_id': self.spj.id})
        self.anonymous_url = reverse('update-camera-data', kwargs={'spj_id': self.anonymous_spj.id})
        
        self.valid_payload = {
            "camera_data": {
                "lookAt": {"x": 1.0, "y": 2.0, "z": 3.0},
                "position": {"x": 4.0, "y": 5.0, "z": 6.0},
                "up": {"x": 0.0, "y": 1.0, "z": 0.0}
            }
        }
        self.invalid_payload = {
            "camera_data": {
                "lookAt": {"x": 1.0, "y": 2.0},  # Missing 'z'
                "position": {"x": 4.0, "y": 5.0, "z": 6.0},
                "up": {"x": 0.0, "y": 1.0, "z": 0.0}
            }
        }

    def test_update_camera_data_authenticated(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.put(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"message": "Camera data updated successfully."})
        self.spj.refresh_from_db()
        self.assertEqual(self.spj.camera_data, self.valid_payload['camera_data'])

    def test_update_camera_data_unauthenticated(self):
        self.client.logout()
        response = self.client.put(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('detail', response.data)

    def test_update_camera_data_admin(self):
        self.client.login(username='adminuser', password='adminpass')
        response = self.client.put(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"message": "Camera data updated successfully."})
        self.spj.refresh_from_db()
        self.assertEqual(self.spj.camera_data, self.valid_payload['camera_data'])

    def test_update_camera_data_not_owner(self):
        self.client.login(username='otheruser', password='otherpass')
        response = self.client.put(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('detail', response.data)

    def test_update_camera_data_invalid_data(self):
        self.client.login(username='testuser', password='testpass')
        response = self.client.put(self.url, self.invalid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('camera_data', response.data)

    def test_anonymous_user_update_owned_job(self):
        """Test that anonymous users cannot update jobs owned by users"""
        # Ensure we're not logged in
        self.client.logout()
        response = self.client.put(self.url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('detail', response.data)

    def test_anonymous_user_update_anonymous_job(self):
        """Test that anonymous users can update jobs with no owner"""
        # Ensure we're not logged in
        self.client.logout()
        response = self.client.put(self.anonymous_url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"message": "Camera data updated successfully."})
        self.anonymous_spj.refresh_from_db()
        self.assertEqual(self.anonymous_spj.camera_data, self.valid_payload['camera_data'])

    def test_authenticated_user_update_anonymous_job(self):
        """Test that authenticated users can update anonymous jobs"""
        self.client.login(username='testuser', password='testpass')
        response = self.client.put(self.anonymous_url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"message": "Camera data updated successfully."})
        self.anonymous_spj.refresh_from_db()
        self.assertEqual(self.anonymous_spj.camera_data, self.valid_payload['camera_data'])

    def test_admin_update_anonymous_job(self):
        """Test that admin users can update anonymous jobs"""
        self.client.login(username='adminuser', password='adminpass')
        response = self.client.put(self.anonymous_url, self.valid_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"message": "Camera data updated successfully."})
        self.anonymous_spj.refresh_from_db()
        self.assertEqual(self.anonymous_spj.camera_data, self.valid_payload['camera_data'])

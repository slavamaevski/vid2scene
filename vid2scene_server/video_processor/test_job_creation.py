import json
import uuid
from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth.models import User
from unittest.mock import patch, Mock

from subscriptions.models import (
    UserSubscription, SubscriptionTier, CreditTransaction
)
from .models import SceneProcessingJob
from . import job_creation


def create_unique_mock_job():
    """Create a mock job with a unique ID to avoid database conflicts"""
    mock_job = Mock()
    mock_job.id = f'mock_job_{uuid.uuid4().hex[:8]}'
    return mock_job


@override_settings(BILLING_ENABLED=True)
class CreditConsumptionTests(TestCase):
    """Test credit consumption through CreditTransaction system"""
    
    def setUp(self):
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
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_credit_consumption_creates_transaction(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that creating a scene job creates a credit consumption transaction"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        initial_credits = self.subscription.api_credits_remaining
        initial_transaction_count = CreditTransaction.objects.count()
        
        # Create a scene processing job (this should consume a credit)
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=True,  # This makes it premium for enterprise per-scene users
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Refresh subscription from DB
        self.subscription.refresh_from_db()
        
        # Verify credit was consumed
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits - 1)
        
        # Verify a consumption transaction was created
        self.assertEqual(CreditTransaction.objects.count(), initial_transaction_count + 1)
        
        # Get the consumption transaction
        consumption_transaction = CreditTransaction.objects.filter(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION
        ).first()
        
        self.assertIsNotNone(consumption_transaction)
        self.assertEqual(consumption_transaction.credits_amount, -1)
        self.assertEqual(consumption_transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertEqual(consumption_transaction.scene_processing_job, spj)
        self.assertIn("job successfully queued", consumption_transaction.admin_notes)
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    def test_insufficient_credits_api_call_raises_error(self, mock_validate_blob, mock_generate_sas):
        """Test that insufficient credits for API call raises an error before creating job"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        
        # Set user to have 0 credits
        self.subscription.api_credits_remaining = 0
        self.subscription.save()
        
        initial_job_count = SceneProcessingJob.objects.count()
        initial_transaction_count = CreditTransaction.objects.count()
        
        # Attempt to create a scene processing job
        with self.assertRaises(ValueError) as context:
            job_creation.create_processing_job(
                user=self.user,
                title="Test Scene",
                blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
                is_api_call=True,  # This makes it premium for enterprise per-scene users
                training_num_steps=5000,
                equirectangular=False,
                use_background_sphere=False
            )
        
        # Verify error message
        self.assertIn('Insufficient API credits', str(context.exception))
        
        # Verify no job was created
        self.assertEqual(SceneProcessingJob.objects.count(), initial_job_count)
        
        # Verify no transaction was created
        self.assertEqual(CreditTransaction.objects.count(), initial_transaction_count)
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_insufficient_credits_web_call_creates_non_premium_job(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that insufficient credits for web call creates non-premium job instead of failing"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Set user to have 0 credits
        self.subscription.api_credits_remaining = 0
        self.subscription.save()
        
        initial_job_count = SceneProcessingJob.objects.count()
        initial_transaction_count = CreditTransaction.objects.count()
        
        # Create a scene processing job via web (should succeed as non-premium)
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=False,  # Web call - should create non-premium job
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Verify job was created (no exception raised)
        self.assertIsNotNone(spj)
        self.assertEqual(SceneProcessingJob.objects.count(), initial_job_count + 1)
        
        # Verify no credit was consumed
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 0)
        
        # Verify no consumption transaction was created (non-premium processing)
        self.assertEqual(CreditTransaction.objects.count(), initial_transaction_count)
        
        # Verify job was queued to default queue (non-premium)
        mock_get_queue.assert_called_with("default")
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_non_enterprise_perscene_no_consumption(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that non-enterprise-per-scene users don't consume credits"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Change user to regular enterprise (not per-scene)
        self.subscription.tier = SubscriptionTier.ENTERPRISE
        self.subscription.save()
        
        initial_credits = self.subscription.api_credits_remaining
        initial_transaction_count = CreditTransaction.objects.count()
        
        # Create a scene processing job
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=True,
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Refresh subscription from DB
        self.subscription.refresh_from_db()
        
        # Verify no credit was consumed
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits)
        
        # Verify no consumption transaction was created
        self.assertEqual(CreditTransaction.objects.count(), initial_transaction_count)
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_web_call_consumes_credit_if_available_for_enterprise_perscene(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that enterprise per-scene users consume credits for web calls if they have them"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        initial_credits = self.subscription.api_credits_remaining
        initial_transaction_count = CreditTransaction.objects.count()
        
        # Create a scene processing job via web (not API)
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=False,  # Web call - should consume credits if available for enterprise per-scene
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Refresh subscription from DB
        self.subscription.refresh_from_db()
        
        # Verify credit was consumed (web calls consume credits if available)
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits - 1)
        
        # Verify consumption transaction was created
        self.assertEqual(CreditTransaction.objects.count(), initial_transaction_count + 1)
        
        # Get the consumption transaction
        consumption_transaction = CreditTransaction.objects.filter(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION
        ).first()
        
        self.assertIsNotNone(consumption_transaction)
        self.assertEqual(consumption_transaction.credits_amount, -1)
        self.assertEqual(consumption_transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertEqual(consumption_transaction.scene_processing_job, spj)
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_web_call_no_credits_goes_to_free_tier_for_enterprise_perscene(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that enterprise per-scene users with no credits get free tier processing for web calls"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Set user to have 0 credits
        self.subscription.api_credits_remaining = 0
        self.subscription.save()
        
        initial_transaction_count = CreditTransaction.objects.count()
        
        # Create a scene processing job via web (should succeed as free tier)
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=False,  # Web call - should go to free tier when no credits
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Verify job was created (no exception raised)
        self.assertIsNotNone(spj)
        
        # Verify no credit was consumed (still at 0)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 0)
        
        # Verify no consumption transaction was created (free tier processing)
        self.assertEqual(CreditTransaction.objects.count(), initial_transaction_count)
        
        # Verify job was queued to default queue (free tier)
        mock_get_queue.assert_called_with("default")
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_transaction_linking_to_job(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that consumption transaction is properly linked to the created job"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Create a scene processing job
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene for Linking",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=True,
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Get the consumption transaction
        consumption_transaction = CreditTransaction.objects.filter(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION
        ).first()
        
        # Verify proper linking
        self.assertIsNotNone(consumption_transaction)
        self.assertEqual(consumption_transaction.scene_processing_job, spj)
        self.assertEqual(consumption_transaction.scene_processing_job.id, spj.id)
        self.assertEqual(consumption_transaction.scene_processing_job.title, "Test Scene for Linking")
        
        # Verify reverse relationship works
        related_transactions = spj.credit_transactions.all()
        self.assertEqual(related_transactions.count(), 1)
        self.assertEqual(related_transactions.first(), consumption_transaction)


@override_settings(BILLING_ENABLED=True)
class JobCreationGeneralTests(TestCase):
    """Test general job creation functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.pro_user = User.objects.create_user(
            username='prouser',
            email='pro@example.com',
            password='testpass'
        )
        # Create Pro subscription
        UserSubscription.objects.create(
            user=self.pro_user,
            tier=SubscriptionTier.PRO,
            is_active=True
        )
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_premium_treatment_logic(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that premium treatment is correctly determined for different user types"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.side_effect = lambda *args, **kwargs: create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Test Pro user gets premium treatment for web but not API
        result_web = job_creation.create_processing_job(
            user=self.pro_user,
            title="Pro Web Scene",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=False,  # Web call
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj_web = result_web['spj']
        
        # Verify the job was created (pro users can use web)
        self.assertIsNotNone(spj_web)
        
        # Test free user doesn't get premium treatment
        result_free = job_creation.create_processing_job(
            user=self.user,
            title="Free User Scene",
            blob_name="videos/87654321-4321-8765-2109-876543210987.mp4",
            is_api_call=False,  # Web call
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj_free = result_free['spj']
        
        # Verify the job was created (free users can still use web)
        self.assertIsNotNone(spj_free)
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_enterprise_perscene_no_credits_web_premium_params_adjusted(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that enterprise per-scene users with no credits get premium parameters adjusted on web calls"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Create enterprise per-scene user with no credits
        enterprise_user = User.objects.create_user(
            username='enterprise_perscene_user',
            email='enterprise@example.com',
            password='testpass'
        )
        subscription = UserSubscription.objects.create(
            user=enterprise_user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=0  # No credits
        )
        
        # Create a web job with premium parameters (high training steps) - should succeed with adjustments
        result = job_creation.create_processing_job(
            user=enterprise_user,
            title="Test Scene",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            is_api_call=False,  # Web call
            training_num_steps=40000,  # Premium parameter - should be adjusted down
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Should succeed but with adjusted parameters
        self.assertIsNotNone(spj)
        # Training steps should be adjusted to free tier limit
        from .models import SceneProcessingJob
        self.assertEqual(spj.training_num_steps, SceneProcessingJob.MAX_NUM_STEPS_FREE)
        
        # Should be queued to default queue (free tier)
        mock_get_queue.assert_called_with("default")


@override_settings(BILLING_ENABLED=True)
class CameraTypeJobCreationTests(TestCase):
    """Test camera_type parameter in job creation"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_camera_type_orbital_sets_camera_data(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that camera_type='orbital' sets initial camera_data with cameraType"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Create a scene processing job with camera_type
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene Orbital",
            blob_name="videos/12345678-1234-5678-9012-123456789012.mp4",
            camera_type='orbital',
            is_api_call=False,
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Verify camera_data was set with cameraType
        self.assertIsNotNone(spj.camera_data)
        self.assertIn('cameraType', spj.camera_data)
        self.assertEqual(spj.camera_data['cameraType'], 'orbital')
        self.assertIn('lookAt', spj.camera_data)
        self.assertIn('position', spj.camera_data)
        self.assertIn('up', spj.camera_data)
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_camera_type_drone_sets_camera_data(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that camera_type='drone' sets initial camera_data with cameraType"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Create a scene processing job with camera_type
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene Drone",
            blob_name="videos/87654321-4321-8765-2109-876543210987.mp4",
            camera_type='drone',
            is_api_call=False,
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Verify camera_data was set with cameraType
        self.assertIsNotNone(spj.camera_data)
        self.assertEqual(spj.camera_data['cameraType'], 'drone')
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_no_camera_type_no_camera_data(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that omitting camera_type leaves camera_data as None"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Create a scene processing job without camera_type
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene No Camera Type",
            blob_name="videos/11111111-2222-3333-4444-555555555555.mp4",
            # No camera_type parameter
            is_api_call=False,
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Verify camera_data is None
        self.assertIsNone(spj.camera_data)
    
    @patch('video_processor.job_creation.generate_blob_sas')
    @patch('video_processor.job_creation.validate_blob_age')
    @patch('django_rq.get_queue')
    def test_camera_type_none_no_camera_data(self, mock_get_queue, mock_validate_blob, mock_generate_sas):
        """Test that camera_type=None leaves camera_data as None"""
        # Mock the required functions
        mock_validate_blob.return_value = True
        mock_generate_sas.return_value = 'mock_sas_url'
        mock_queue = Mock()
        mock_queue.enqueue.return_value = create_unique_mock_job()
        mock_get_queue.return_value = mock_queue
        
        # Create a scene processing job with camera_type=None
        result = job_creation.create_processing_job(
            user=self.user,
            title="Test Scene Camera Type None",
            blob_name="videos/99999999-8888-7777-6666-555555555555.mp4",
            camera_type=None,
            is_api_call=False,
            training_num_steps=5000,
            equirectangular=False,
            use_background_sphere=False
        )
        spj = result['spj']
        
        # Verify camera_data is None
        self.assertIsNone(spj.camera_data)


@override_settings(BILLING_ENABLED=True)
class CreditRefundLogicTests(TestCase):
    """Test the should_refund_credit_for_job helper function"""
    
    def setUp(self):
        # Create test users
        self.enterprise_perscene_user = User.objects.create_user(
            username='enterprise_perscene_user',
            email='enterprise@example.com',
            password='testpass'
        )
        self.enterprise_user = User.objects.create_user(
            username='enterprise_user',
            email='regular_enterprise@example.com',
            password='testpass'
        )
        self.free_user = User.objects.create_user(
            username='free_user',
            email='free@example.com',
            password='testpass'
        )
        
        # Create subscriptions
        self.enterprise_perscene_subscription = UserSubscription.objects.create(
            user=self.enterprise_perscene_user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=5
        )
        self.enterprise_subscription = UserSubscription.objects.create(
            user=self.enterprise_user,
            tier=SubscriptionTier.ENTERPRISE,
            is_active=True
        )
        # Free user has no subscription
    
    def test_should_refund_enterprise_perscene_unfinished_with_consumption(self):
        """Test that unfinished enterprise per-scene jobs with consumption transactions should be refunded"""
        from .utils import should_refund_credit_for_job
        
        # Create unfinished job
        spj = SceneProcessingJob.objects.create(
            user=self.enterprise_perscene_user,
            title="Unfinished Job",
            video_file="videos/test.mp4",
            # No ply_file = unfinished
        )
        
        # Create consumption transaction (indicates it was a premium job)
        consumption_transaction = CreditTransaction.objects.create(
            user=self.enterprise_perscene_user,
            scene_processing_job=spj,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
            credits_amount=-1,
            status=CreditTransaction.TransactionStatus.FULFILLED,
            admin_notes="Scene processing"
        )
        
        # Should be eligible for refund
        self.assertTrue(should_refund_credit_for_job(spj))
    
    def test_should_not_refund_finished_job(self):
        """Test that finished jobs (with ply_file) should not be refunded"""
        from .utils import should_refund_credit_for_job
        
        # Create finished job
        spj = SceneProcessingJob.objects.create(
            user=self.enterprise_perscene_user,
            title="Finished Job",
            video_file="videos/test.mp4",
            ply_file="scenes/test.ply"  # Job is finished
        )
        
        # Create consumption transaction
        consumption_transaction = CreditTransaction.objects.create(
            user=self.enterprise_perscene_user,
            scene_processing_job=spj,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
            credits_amount=-1,
            status=CreditTransaction.TransactionStatus.FULFILLED,
            admin_notes="Scene processing"
        )
        
        # Should NOT be eligible for refund (job is finished)
        self.assertFalse(should_refund_credit_for_job(spj))
    
    def test_should_not_refund_non_enterprise_perscene(self):
        """Test that non-enterprise-per-scene users should not get refunds"""
        from .utils import should_refund_credit_for_job
        
        # Create unfinished job for regular enterprise user
        spj = SceneProcessingJob.objects.create(
            user=self.enterprise_user,
            title="Enterprise Job",
            video_file="videos/test.mp4",
            # No ply_file = unfinished
        )
        
        # Should NOT be eligible for refund (not enterprise per-scene)
        self.assertFalse(should_refund_credit_for_job(spj))
        
        # Test free user
        spj_free = SceneProcessingJob.objects.create(
            user=self.free_user,
            title="Free Job",
            video_file="videos/test.mp4",
        )
        
        # Should NOT be eligible for refund (free user)
        self.assertFalse(should_refund_credit_for_job(spj_free))
    
    def test_should_not_refund_without_consumption_transaction(self):
        """Test that jobs without consumption transactions (non-premium) should not be refunded"""
        from .utils import should_refund_credit_for_job
        
        # Create unfinished job without consumption transaction (free tier job)
        spj = SceneProcessingJob.objects.create(
            user=self.enterprise_perscene_user,
            title="Free Tier Job",
            video_file="videos/test.mp4",
            # No ply_file = unfinished
            # No consumption transaction = was free tier
        )
        
        # Should NOT be eligible for refund (wasn't a premium job)
        self.assertFalse(should_refund_credit_for_job(spj))
    
    def test_should_not_refund_already_refunded(self):
        """Test that jobs with existing refund transactions should not be refunded again"""
        from .utils import should_refund_credit_for_job
        
        # Create unfinished job
        spj = SceneProcessingJob.objects.create(
            user=self.enterprise_perscene_user,
            title="Already Refunded Job",
            video_file="videos/test.mp4",
            # No ply_file = unfinished
        )
        
        # Create consumption transaction
        consumption_transaction = CreditTransaction.objects.create(
            user=self.enterprise_perscene_user,
            scene_processing_job=spj,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
            credits_amount=-1,
            status=CreditTransaction.TransactionStatus.FULFILLED,
            admin_notes="Scene processing"
        )
        
        # Create existing refund transaction
        refund_transaction = CreditTransaction.objects.create(
            user=self.enterprise_perscene_user,
            scene_processing_job=spj,
            transaction_type=CreditTransaction.TransactionType.REFUND,
            credits_amount=1,
            status=CreditTransaction.TransactionStatus.FULFILLED,
            admin_notes="Job deleted before completion"
        )
        
        # Should NOT be eligible for refund (already refunded)
        self.assertFalse(should_refund_credit_for_job(spj))
    
    def test_should_not_refund_pending_consumption_transaction(self):
        """Test that jobs with only pending consumption transactions should not be refunded"""
        from .utils import should_refund_credit_for_job
        
        # Create unfinished job
        spj = SceneProcessingJob.objects.create(
            user=self.enterprise_perscene_user,
            title="Pending Transaction Job",
            video_file="videos/test.mp4",
            # No ply_file = unfinished
        )
        
        # Create PENDING consumption transaction (credit not actually deducted)
        consumption_transaction = CreditTransaction.objects.create(
            user=self.enterprise_perscene_user,
            scene_processing_job=spj,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
            credits_amount=-1,
            status=CreditTransaction.TransactionStatus.PENDING,  # Still pending
            admin_notes="Scene processing"
        )
        
        # Should NOT be eligible for refund (credit wasn't actually deducted)
        self.assertFalse(should_refund_credit_for_job(spj))
    
    def test_should_not_refund_anonymous_job(self):
        """Test that anonymous jobs should not be refunded"""
        from .utils import should_refund_credit_for_job
        
        # Create anonymous job
        spj = SceneProcessingJob.objects.create(
            user=None,  # Anonymous
            title="Anonymous Job",
            video_file="videos/test.mp4",
        )
        
        # Should NOT be eligible for refund (no user)
        self.assertFalse(should_refund_credit_for_job(spj))

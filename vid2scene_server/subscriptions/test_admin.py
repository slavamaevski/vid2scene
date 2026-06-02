from django.test import TestCase, RequestFactory
from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.contrib.admin.sites import AdminSite
from django.forms import ModelForm
from django.contrib.messages.storage.fallback import FallbackStorage

from .models import (
    UserSubscription, SubscriptionTier, CreditTransaction, 
    RefundRequest
)
from .admin import RefundRequestAdmin, CreditTransactionAdmin
from video_processor.models import SceneProcessingJob


class MockRequest:
    """Mock request object for admin tests"""
    def __init__(self, user):
        self.user = user
        # Add required attributes for Django messaging
        self.session = {}
        self._messages = FallbackStorage(self)
        self.META = {}
    
    def get_full_path(self):
        return '/admin/test/'


@override_settings(BILLING_ENABLED=True)
class RefundRequestAdminTests(TestCase):
    """Test RefundRequestAdmin functionality"""
    
    def setUp(self):
        self.site = AdminSite()
        self.admin = RefundRequestAdmin(RefundRequest, self.site)
        self.factory = RequestFactory()
        
        # Create users
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass',
            is_staff=True,
            is_superuser=True
        )
        
        # Create subscription
        self.subscription = UserSubscription.objects.create(
            user=self.user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=5
        )
        
        # Create scene job
        self.scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Test Scene',
            video_file='test.mp4'
        )
    
    def test_save_model_approve_from_requested(self):
        """Test admin save_model when changing REQUESTED to APPROVED"""
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            customer_notes="Poor quality scene"
        )
        
        # Mock form data
        class MockForm:
            def __init__(self):
                self.changed_data = ['status']
            
            def cleaned_data(self):
                return {'admin_notes': 'Approved after review'}
            
            @property
            def cleaned_data(self):
                return {'admin_notes': 'Approved after review'}
        
        # Change status to APPROVED
        refund_request.status = RefundRequest.RefundStatus.APPROVED
        
        initial_credits = self.subscription.api_credits_remaining
        
        # Call admin save_model
        mock_request = MockRequest(self.admin_user)
        mock_form = MockForm()
        
        self.admin.save_model(mock_request, refund_request, mock_form, change=True)
        
        # Check request was approved and credits added
        refund_request.refresh_from_db()
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertEqual(refund_request.processed_by, self.admin_user)
        self.assertIsNotNone(refund_request.processed_at)
        self.assertIsNotNone(refund_request.credit_transaction)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 1)
    
    def test_save_model_approve_from_denied(self):
        """Test admin save_model when changing DENIED to APPROVED"""
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            status=RefundRequest.RefundStatus.DENIED
        )
        
        class MockForm:
            def __init__(self):
                self.changed_data = ['status']
            
            @property
            def cleaned_data(self):
                return {'admin_notes': 'Changed decision after support contact'}
        
        # Change status to APPROVED
        refund_request.status = RefundRequest.RefundStatus.APPROVED
        
        initial_credits = self.subscription.api_credits_remaining
        
        # Call admin save_model
        mock_request = MockRequest(self.admin_user)
        mock_form = MockForm()
        
        self.admin.save_model(mock_request, refund_request, mock_form, change=True)
        
        # Check request was approved and credits added
        refund_request.refresh_from_db()
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertIsNotNone(refund_request.credit_transaction)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 1)
    
    def test_save_model_deny_from_requested(self):
        """Test admin save_model when changing REQUESTED to DENIED"""
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            customer_notes="Poor quality scene"
        )
        
        class MockForm:
            def __init__(self):
                self.changed_data = ['status']
            
            @property
            def cleaned_data(self):
                return {'admin_notes': 'Scene quality is acceptable'}
        
        # Change status to DENIED
        refund_request.status = RefundRequest.RefundStatus.DENIED
        
        initial_credits = self.subscription.api_credits_remaining
        
        # Call admin save_model
        mock_request = MockRequest(self.admin_user)
        mock_form = MockForm()
        
        self.admin.save_model(mock_request, refund_request, mock_form, change=True)
        
        # Check request was denied and no credits added
        refund_request.refresh_from_db()
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.DENIED)
        self.assertEqual(refund_request.processed_by, self.admin_user)
        self.assertIsNotNone(refund_request.processed_at)
        self.assertEqual(refund_request.admin_notes, 'Scene quality is acceptable')
        self.assertIsNone(refund_request.credit_transaction)
        
        # Check credits were NOT added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits)
    
    def test_user_email_display(self):
        """Test user_email display method"""
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED
        )
        
        email = self.admin.user_email(refund_request)
        self.assertEqual(email, 'test@example.com')
    
    def test_scene_job_title_display(self):
        """Test scene_job_title display method"""
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED
        )
        
        title = self.admin.scene_job_title(refund_request)
        self.assertEqual(title, 'Test Scene')
    
    
    def test_scene_viewer_link_finished_job(self):
        """Test scene_viewer_link for finished job with PLY file"""
        # Add PLY file to scene job
        self.scene_job.ply_file = 'test.ply'
        self.scene_job.save()
        
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED
        )
        
        link_html = self.admin.scene_viewer_link(refund_request)
        self.assertIn('View Scene', link_html)
        self.assertIn('target="_blank"', link_html)
        self.assertIn(str(self.scene_job.id), link_html)
    
    def test_scene_viewer_link_unfinished_job(self):
        """Test scene_viewer_link for unfinished job without PLY file"""
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED
        )
        
        link_html = self.admin.scene_viewer_link(refund_request)
        self.assertIn('Not Finished', link_html)
        self.assertIn('color: #999', link_html)
    
    def test_cascade_delete_scene_job_removes_refund_requests(self):
        """Test that deleting a scene job cascades to delete associated refund requests"""
        # Create a refund request
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            customer_notes="Test refund request"
        )
        
        refund_request_id = refund_request.id
        
        # Verify the refund request exists
        self.assertTrue(RefundRequest.objects.filter(id=refund_request_id).exists())
        
        # Delete the scene processing job
        self.scene_job.delete()
        
        # Verify the refund request was automatically deleted due to CASCADE
        self.assertFalse(RefundRequest.objects.filter(id=refund_request_id).exists())


@override_settings(BILLING_ENABLED=True)
class CreditTransactionAdminTests(TestCase):
    """Test CreditTransactionAdmin functionality"""
    
    def setUp(self):
        self.site = AdminSite()
        self.admin = CreditTransactionAdmin(CreditTransaction, self.site)
        self.factory = RequestFactory()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass',
            is_staff=True,
            is_superuser=True
        )
        self.subscription = UserSubscription.objects.create(
            user=self.user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            api_credits_remaining=10
        )
    
    def test_transaction_str_representation(self):
        """Test CreditTransaction string representation"""
        transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.REFUND,
            credits_amount=3,
            status=CreditTransaction.TransactionStatus.FULFILLED
        )
        
        expected = f"Transaction #{transaction.id} - testuser - +3 credits (Fulfilled)"
        self.assertEqual(str(transaction), expected)
        
        # Test negative amount
        transaction.credits_amount = -2
        transaction.save()
        
        expected_negative = f"Transaction #{transaction.id} - testuser - -2 credits (Fulfilled)"
        self.assertEqual(str(transaction), expected_negative)
    
    def test_manual_credit_addition_with_auto_fulfill(self):
        """Test creating manual credit addition with auto-fulfill"""
        initial_credits = self.subscription.api_credits_remaining
        
        # Create transaction with auto_processed=True
        transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.ADJUSTMENT,
            credits_amount=25,
            admin_notes="Manual bonus credits",
            auto_processed=True
        )
        
        # Mock form data
        class MockForm:
            def __init__(self):
                self.changed_data = []
        
        mock_form = MockForm()
        mock_request = MockRequest(self.admin_user)
        
        # Call admin save_model (simulates saving in admin)
        self.admin.save_model(mock_request, transaction, mock_form, change=False)
        
        # Refresh subscription from DB
        self.subscription.refresh_from_db()
        
        # Verify credits were added
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 25)
        
        # Verify transaction was fulfilled
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertEqual(transaction.processed_by, self.admin_user)
        self.assertIsNotNone(transaction.fulfilled_at)
    
    def test_manual_credit_deduction_with_auto_fulfill(self):
        """Test creating manual credit deduction with auto-fulfill"""
        initial_credits = self.subscription.api_credits_remaining
        
        # Create transaction with negative amount and auto_processed=True
        transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.ADJUSTMENT,
            credits_amount=-3,
            admin_notes="Manual deduction for refund",
            auto_processed=True
        )
        
        class MockForm:
            def __init__(self):
                self.changed_data = []
        
        mock_form = MockForm()
        mock_request = MockRequest(self.admin_user)
        
        # Call admin save_model
        self.admin.save_model(mock_request, transaction, mock_form, change=False)
        
        # Refresh subscription from DB
        self.subscription.refresh_from_db()
        
        # Verify credits were deducted
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits - 3)
        
        # Verify transaction was fulfilled
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
    
    def test_manual_transaction_without_auto_fulfill(self):
        """Test creating manual transaction without auto-fulfill stays pending"""
        initial_credits = self.subscription.api_credits_remaining
        
        # Create transaction with auto_processed=False
        transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.ADJUSTMENT,
            credits_amount=15,
            admin_notes="Manual credits - needs approval",
            auto_processed=False
        )
        
        class MockForm:
            def __init__(self):
                self.changed_data = []
        
        mock_form = MockForm()
        mock_request = MockRequest(self.admin_user)
        
        # Call admin save_model
        self.admin.save_model(mock_request, transaction, mock_form, change=False)
        
        # Refresh subscription from DB
        self.subscription.refresh_from_db()
        
        # Verify credits were NOT added yet
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits)
        
        # Verify transaction is still pending
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.PENDING)
        self.assertIsNone(transaction.processed_by)
        self.assertIsNone(transaction.fulfilled_at)
    
    def test_default_transaction_type_for_manual_entries(self):
        """Test that manual entries default to ADJUSTMENT type"""
        transaction = CreditTransaction(
            user=self.user,
            credits_amount=10
        )
        
        class MockForm:
            def __init__(self):
                self.changed_data = []
        
        mock_form = MockForm()
        mock_request = MockRequest(self.admin_user)
        
        # Call admin save_model
        self.admin.save_model(mock_request, transaction, mock_form, change=False)
        
        # Verify default transaction type was set
        self.assertEqual(transaction.transaction_type, CreditTransaction.TransactionType.ADJUSTMENT)
    
    
    def test_status_change_sets_metadata(self):
        """Test that changing status to FULFILLED sets processed_by and fulfilled_at"""
        transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.ADJUSTMENT,
            credits_amount=5,
            status=CreditTransaction.TransactionStatus.PENDING
        )
        
        # Simulate changing status in admin
        class MockForm:
            def __init__(self):
                self.changed_data = ['status']
        
        transaction.status = CreditTransaction.TransactionStatus.FULFILLED
        mock_form = MockForm()
        mock_request = MockRequest(self.admin_user)
        
        # Call admin save_model
        self.admin.save_model(mock_request, transaction, mock_form, change=True)
        
        # Verify metadata was set
        self.assertEqual(transaction.processed_by, self.admin_user)
        self.assertIsNotNone(transaction.fulfilled_at)

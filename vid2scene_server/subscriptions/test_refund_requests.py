from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth.models import User
from datetime import datetime, timezone

from .models import (
    UserSubscription, SubscriptionTier, CreditTransaction, 
    RefundRequest, PerSceneCheckoutSessionRecord
)
from video_processor.models import SceneProcessingJob


@override_settings(BILLING_ENABLED=True)
class RefundRequestModelTests(TestCase):
    """Test RefundRequest model functionality"""
    
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
        self.scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Test Scene',
            video_file='test.mp4'
        )
    
    def test_create_refund_request(self):
        """Test creating a basic refund request"""
        request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            customer_notes="The scene quality is poor"
        )
        
        self.assertEqual(request.status, RefundRequest.RefundStatus.REQUESTED)
        self.assertEqual(request.credits_requested, 1)  # Default
        self.assertEqual(request.reason, RefundRequest.RefundReason.QUALITY_UNSATISFIED)
        self.assertEqual(request.customer_notes, "The scene quality is poor")
        self.assertFalse(request.auto_approved)
    
    def test_create_request_auto_approve_technical(self):
        """Test auto-approval for technical failures"""
        initial_credits = self.subscription.api_credits_remaining
        
        request = RefundRequest.create_request(
            user=self.user,
            scene_job=self.scene_job,
            reason=RefundRequest.RefundReason.TECHNICAL_FAILURE,
            customer_notes="Job failed",
            auto_approve_technical=True
        )
        
        self.assertEqual(request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertTrue(request.auto_approved)
        self.assertIsNotNone(request.credit_transaction)
        self.assertEqual(request.credit_transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 1)
    
    def test_approve_refund_request(self):
        """Test manually approving a refund request"""
        request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            customer_notes="Poor quality"
        )
        
        initial_credits = self.subscription.api_credits_remaining
        admin_user = User.objects.create_user(username='admin', email='admin@example.com')
        
        request.approve(processed_by_user=admin_user, admin_notes="Valid complaint")
        
        self.assertEqual(request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertEqual(request.processed_by, admin_user)
        self.assertEqual(request.admin_notes, "Valid complaint")
        self.assertIsNotNone(request.processed_at)
        self.assertIsNotNone(request.credit_transaction)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 1)
    
    def test_approve_from_denied_status(self):
        """Test approving a previously denied request"""
        request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            status=RefundRequest.RefundStatus.DENIED
        )
        
        initial_credits = self.subscription.api_credits_remaining
        
        request.approve(admin_notes="Changed mind after review")
        
        self.assertEqual(request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertIsNotNone(request.credit_transaction)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 1)
    
    def test_approve_from_cancelled_status(self):
        """Test approving a previously cancelled request"""
        request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            status=RefundRequest.RefundStatus.CANCELLED
        )
        
        initial_credits = self.subscription.api_credits_remaining
        
        request.approve(admin_notes="Support decided to approve")
        
        self.assertEqual(request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertIsNotNone(request.credit_transaction)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 1)
    
    def test_deny_refund_request(self):
        """Test denying a refund request"""
        request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED
        )
        
        admin_user = User.objects.create_user(username='admin', email='admin@example.com')
        request.deny(processed_by_user=admin_user, admin_notes="Scene quality is acceptable")
        
        self.assertEqual(request.status, RefundRequest.RefundStatus.DENIED)
        self.assertEqual(request.processed_by, admin_user)
        self.assertEqual(request.admin_notes, "Scene quality is acceptable")
        self.assertIsNotNone(request.processed_at)
        self.assertIsNone(request.credit_transaction)  # No transaction created for denial
    
    def test_cancel_refund_request(self):
        """Test cancelling a refund request"""
        request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=self.scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED
        )
        
        request.cancel()
        
        self.assertEqual(request.status, RefundRequest.RefundStatus.CANCELLED)

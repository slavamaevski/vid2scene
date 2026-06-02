import pytest
from datetime import datetime, timezone
from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth.models import User

from .models import (
    UserSubscription, SubscriptionTier, CreditTransaction, 
    RefundRequest, PerSceneCheckoutSessionRecord
)
from video_processor.models import SceneProcessingJob


@override_settings(BILLING_ENABLED=True)
class CreditTransactionModelTests(TestCase):
    """Test CreditTransaction model functionality"""
    
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
            api_credits_remaining=10
        )
        self.scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Test Scene',
            video_file='test.mp4'
        )
    
    def test_create_refund_transaction_basic(self):
        """Test creating a basic refund transaction"""
        transaction = CreditTransaction.create_refund_transaction(
            user=self.user,
            scene_job=self.scene_job,
            credits_amount=1,
            user_notes="Test refund"
        )
        
        self.assertEqual(transaction.user, self.user)
        self.assertEqual(transaction.transaction_type, CreditTransaction.TransactionType.REFUND)
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.PENDING)
        self.assertEqual(transaction.credits_amount, 1)
        self.assertEqual(transaction.scene_processing_job, self.scene_job)
        self.assertEqual(transaction.user_notes, "Test refund")
        self.assertFalse(transaction.auto_processed)
    
    def test_create_refund_transaction_auto_process(self):
        """Test creating and auto-processing a refund transaction"""
        initial_credits = self.subscription.api_credits_remaining
        
        transaction = CreditTransaction.create_refund_transaction(
            user=self.user,
            scene_job=self.scene_job,
            credits_amount=2,
            auto_process=True
        )
        
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertIsNotNone(transaction.fulfilled_at)
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 2)
    
    def test_fulfill_transaction(self):
        """Test manually fulfilling a pending transaction"""
        transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.REFUND,
            credits_amount=3,
            scene_processing_job=self.scene_job
        )
        
        initial_credits = self.subscription.api_credits_remaining
        admin_user = User.objects.create_user(username='admin', email='admin@example.com')
        
        result = transaction.fulfill(processed_by_user=admin_user, admin_notes="Approved by admin")
        
        self.assertTrue(result)
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertIsNotNone(transaction.fulfilled_at)
        self.assertEqual(transaction.processed_by, admin_user)
        self.assertEqual(transaction.admin_notes, "Approved by admin")
        
        # Check credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits + 3)
    
    def test_fulfill_already_fulfilled_transaction(self):
        """Test that fulfilling an already fulfilled transaction fails gracefully"""
        transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.REFUND,
            status=CreditTransaction.TransactionStatus.FULFILLED,
            credits_amount=1,
            fulfilled_at=datetime.now(timezone.utc)
        )
        
        result = transaction.fulfill()
        self.assertFalse(result)
    
    def test_create_purchase_transaction(self):
        """Test creating a purchase transaction"""
        checkout_session = PerSceneCheckoutSessionRecord.objects.create(
            user=self.user,
            package=PerSceneCheckoutSessionRecord.CreditPackage.SMALL,
            credits_amount=10,
            price_cents=4999,
            stripe_checkout_session_id='cs_test_123'
        )
        
        transaction = CreditTransaction.create_purchase_transaction(
            user=self.user,
            checkout_session=checkout_session,
            credits_amount=10
        )
        
        self.assertEqual(transaction.user, self.user)
        self.assertEqual(transaction.transaction_type, CreditTransaction.TransactionType.PURCHASE)
        self.assertEqual(transaction.credits_amount, 10)
        self.assertEqual(transaction.checkout_session, checkout_session)
        self.assertTrue(transaction.auto_processed)

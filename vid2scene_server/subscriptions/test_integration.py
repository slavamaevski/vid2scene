import json
from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from .models import (
    UserSubscription, SubscriptionTier, CreditTransaction, 
    RefundRequest, PerSceneCheckoutSessionRecord
)
from video_processor.models import SceneProcessingJob


@override_settings(BILLING_ENABLED=True)
class EndToEndIntegrationTests(TestCase):
    """End-to-end integration tests for complete credit management workflows"""
    
    def setUp(self):
        self.client = Client()
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
        self.subscription = UserSubscription.objects.create(
            user=self.user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=0
        )
    
    def test_complete_purchase_to_refund_workflow(self):
        """Test complete workflow: purchase credits → use credit → request refund → get approved"""
        
        # Step 1: User purchases credits
        self.client.login(username='testuser', password='testpass')
        
        # Create checkout session
        with patch('stripe.Price.list') as mock_price_list, \
             patch('stripe.checkout.Session.create') as mock_session_create:
            
            mock_price_list.return_value = Mock(data=[Mock(id='price_123', unit_amount=4999)])
            mock_session_create.return_value = Mock(
                id='cs_test_integration',
                url='https://checkout.stripe.com/pay/cs_test_integration'
            )
            
            response = self.client.post(reverse('create-credits-purchase-checkout-session'), {
                'package': PerSceneCheckoutSessionRecord.CreditPackage.SMALL
            })
        
        self.assertEqual(response.status_code, 200)
        
        # Step 2: Webhook completes the purchase
        session = PerSceneCheckoutSessionRecord.objects.get(
            stripe_checkout_session_id='cs_test_integration'
        )
        
        webhook_payload = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_integration',
                    'payment_status': 'paid',
                    'payment_intent': 'pi_test_integration'
                }
            }
        }
        
        # Create a mock stripe.Event object
        class MockStripeEvent:
            def __init__(self, payload):
                self.type = payload['type']
                self.data = type('obj', (object,), {'object': payload['data']['object']})()
        
        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.return_value = MockStripeEvent(webhook_payload)
            
            self.client.post(
                reverse('collect-stripe-webhook'),
                data=json.dumps(webhook_payload),
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='test_signature'
            )
        
        # Verify credits were added
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 10)
        
        # Verify purchase transaction was created
        purchase_transaction = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.TransactionType.PURCHASE,
            checkout_session=session
        ).first()
        self.assertIsNotNone(purchase_transaction)
        self.assertEqual(purchase_transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        
        # Step 3: User creates a scene job (simulating credit consumption)
        scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Integration Test Scene',
            video_file='integration_test.mp4'
        )
        
        # Simulate credit consumption using proper transaction system
        consumption_transaction = CreditTransaction.objects.create(
            user=self.user,
            scene_processing_job=scene_job,  # Link to the job
            job_title=scene_job.title,  # Set audit trail fields
            job_created_at=scene_job.uploaded_at,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
            credits_amount=-1,
            admin_notes="Test consumption",
            auto_processed=True
        )
        consumption_transaction.fulfill()
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 9)
        
        # Step 4: User requests refund for quality issues
        with patch('video_processor.web_api.find_rq_job_with_queue_name') as mock_find_job, \
             patch('video_processor.web_api.get_status_string') as mock_status:
            
            mock_find_job.return_value = (None, None)
            mock_status.return_value = "Finished"
            
            response = self.client.post(reverse('request_refund', args=[scene_job.id]), {
                'reason': 'UNSATISFIED',
                'notes': 'The scene quality is not acceptable for my use case'
            })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertFalse(data['auto_approved'])  # Quality issues need manual review
        
        # Verify refund request was created
        refund_request = RefundRequest.objects.filter(scene_processing_job=scene_job).first()
        self.assertIsNotNone(refund_request)
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.REQUESTED)
        
        # Credits should still be 9 (not refunded yet)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 9)
        
        # Step 5: Admin approves the refund request
        refund_request.approve(
            processed_by_user=self.admin_user,
            admin_notes="Valid complaint - scene quality was indeed poor"
        )
        
        # Verify refund was processed
        refund_request.refresh_from_db()
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertIsNotNone(refund_request.credit_transaction)
        
        # Verify credits were refunded
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 10)  # Back to 10
        
        # Verify refund transaction was created
        refund_transaction = refund_request.credit_transaction
        self.assertEqual(refund_transaction.transaction_type, CreditTransaction.TransactionType.REFUND)
        self.assertEqual(refund_transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertEqual(refund_transaction.credits_amount, 1)
        
        # Step 6: Verify complete audit trail
        all_transactions = CreditTransaction.objects.filter(user=self.user).order_by('created_at')
        self.assertEqual(all_transactions.count(), 3)
        
        # Purchase transaction
        self.assertEqual(all_transactions[0].transaction_type, CreditTransaction.TransactionType.PURCHASE)
        self.assertEqual(all_transactions[0].credits_amount, 10)
        
        # Consumption transaction
        self.assertEqual(all_transactions[1].transaction_type, CreditTransaction.TransactionType.CONSUMPTION)
        self.assertEqual(all_transactions[1].credits_amount, -1)
        
        # Refund transaction
        self.assertEqual(all_transactions[2].transaction_type, CreditTransaction.TransactionType.REFUND)
        self.assertEqual(all_transactions[2].credits_amount, 1)
    
    def test_technical_failure_auto_refund_workflow(self):
        """Test workflow for technical failure with immediate auto-refund"""
        
        # Set up user with credits
        self.subscription.api_credits_remaining = 5
        self.subscription.save()
        
        # Create scene job
        scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Failed Job',
            video_file='failed_job.mp4'
        )
        
        # Simulate credit consumption using proper transaction system
        consumption_transaction = CreditTransaction.objects.create(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
            credits_amount=-1,
            admin_notes="Test consumption",
            auto_processed=True
        )
        consumption_transaction.fulfill()
        
        # User requests refund for failed job
        self.client.login(username='testuser', password='testpass')
        
        with patch('video_processor.web_api.find_rq_job_with_queue_name') as mock_find_job, \
             patch('video_processor.web_api.get_status_string') as mock_status:
            
            mock_find_job.return_value = (None, None)
            mock_status.return_value = "Failed"
            
            response = self.client.post(reverse('request_refund', args=[scene_job.id]), {
                'reason': 'FAILURE',
                'notes': 'Job failed due to technical issues'
            })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['auto_approved'])  # Technical failures are auto-approved
        
        # Verify immediate refund
        refund_request = RefundRequest.objects.filter(scene_processing_job=scene_job).first()
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertTrue(refund_request.auto_approved)
        
        # Credits should be immediately refunded
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 5)  # Back to original amount
    
    def test_job_deletion_refund_workflow(self):
        """Test workflow for job deletion refunds"""
        
        # Set up user with credits
        self.subscription.api_credits_remaining = 3
        self.subscription.save()
        
        # Create unfinished scene job (no ply_file)
        scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Unfinished Job',
            video_file='unfinished.mp4'
            # No ply_file = unfinished
        )
        
        # Simulate credit consumption using proper transaction system
        consumption_transaction = CreditTransaction.objects.create(
            user=self.user,
            scene_processing_job=scene_job,  # Link to the job
            job_title=scene_job.title,  # Set audit trail fields
            job_created_at=scene_job.uploaded_at,
            transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
            credits_amount=-1,
            admin_notes="Test consumption",
            auto_processed=True
        )
        consumption_transaction.fulfill()
        self.subscription.refresh_from_db()
        credits_after_consumption = self.subscription.api_credits_remaining  # Should be 2
        self.assertEqual(credits_after_consumption, 2)
        
        # User deletes unfinished job (should trigger refund)
        self.client.login(username='testuser', password='testpass')
        
        response = self.client.post(reverse('delete_job', args=[scene_job.id]))
        
        # Job should be deleted and credits refunded
        self.assertFalse(SceneProcessingJob.objects.filter(id=scene_job.id).exists())
        
        # Credits should be refunded back to original amount
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 3)  # Back to original 3
        
        # Verify refund transaction was created
        # Note: scene_processing_job will be NULL after job deletion due to SET_NULL
        refund_transaction = CreditTransaction.objects.filter(
            user=self.user,
            transaction_type=CreditTransaction.TransactionType.REFUND,
            user_notes__icontains="deleted before completion"
        ).first()
        
        self.assertIsNotNone(refund_transaction)
        self.assertEqual(refund_transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertEqual(refund_transaction.credits_amount, 1)
        self.assertIn("deleted before completion", refund_transaction.user_notes)
    
    def test_denied_to_approved_workflow(self):
        """Test workflow where admin changes mind from DENIED to APPROVED"""
        
        # Set up user with credits
        self.subscription.api_credits_remaining = 5
        self.subscription.save()
        
        # Create scene job
        scene_job = SceneProcessingJob.objects.create(
            user=self.user,
            title='Disputed Scene',
            video_file='disputed.mp4'
        )
        
        # Create refund request
        refund_request = RefundRequest.objects.create(
            user=self.user,
            scene_processing_job=scene_job,
            reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
            customer_notes="Scene has artifacts and poor quality"
        )
        
        # Admin initially denies the request
        refund_request.deny(
            processed_by_user=self.admin_user,
            admin_notes="Scene quality appears acceptable"
        )
        
        # Verify denial
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.DENIED)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 5)  # No refund
        
        # User contacts support with more evidence
        # Admin changes decision and approves
        refund_request.approve(
            processed_by_user=self.admin_user,
            admin_notes="After further review and user evidence, approving refund"
        )
        
        # Verify approval and refund
        refund_request.refresh_from_db()
        self.assertEqual(refund_request.status, RefundRequest.RefundStatus.APPROVED)
        self.assertIsNotNone(refund_request.credit_transaction)
        
        # Credits should be refunded
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 6)
        
        # Verify transaction was created
        transaction = refund_request.credit_transaction
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertEqual(transaction.credits_amount, 1)

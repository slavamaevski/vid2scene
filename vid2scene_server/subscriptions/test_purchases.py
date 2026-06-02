import json
from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.test.utils import override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from .models import (
    UserSubscription, SubscriptionTier, CreditTransaction, 
    PerSceneCheckoutSessionRecord
)


@override_settings(BILLING_ENABLED=True)
class PurchaseWorkflowTests(TestCase):
    """Test credit purchase workflow including webhooks"""
    
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
            api_credits_remaining=0
        )
        
        self.client.login(username='testuser', password='testpass')
    
    def test_create_checkout_session(self):
        """Test creating a Stripe checkout session for credit purchase"""
        url = reverse('create-credits-purchase-checkout-session')
        
        with patch('stripe.Price.list') as mock_price_list, \
             patch('stripe.checkout.Session.create') as mock_session_create:
            
            # Mock Stripe price lookup
            mock_price_list.return_value = Mock(
                data=[Mock(id='price_123', unit_amount=4999)]
            )
            
            # Mock Stripe session creation
            mock_session_create.return_value = Mock(
                id='cs_test_123',
                url='https://checkout.stripe.com/pay/cs_test_123'
            )
            
            response = self.client.post(url, {
                'package': PerSceneCheckoutSessionRecord.CreditPackage.SMALL
            })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        self.assertTrue(data['success'])
        self.assertIn('checkout.stripe.com', data['checkout_url'])
        
        # Check checkout session record was created
        session = PerSceneCheckoutSessionRecord.objects.filter(user=self.user).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.package, PerSceneCheckoutSessionRecord.CreditPackage.SMALL)
        self.assertEqual(session.credits_amount, 10)
        self.assertEqual(session.price_cents, 4999)
        self.assertFalse(session.is_completed)
    
    def test_webhook_checkout_session_completed(self):
        """Test Stripe webhook for completed checkout session"""
        # Create checkout session
        session = PerSceneCheckoutSessionRecord.objects.create(
            user=self.user,
            package=PerSceneCheckoutSessionRecord.CreditPackage.MEDIUM,
            credits_amount=25,
            price_cents=11499,
            stripe_checkout_session_id='cs_test_456'
        )
        
        # Mock webhook payload
        webhook_payload = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_456',
                    'payment_status': 'paid',
                    'payment_intent': 'pi_test_789'
                }
            }
        }
        
        url = reverse('collect-stripe-webhook')
        
        # Create a mock stripe.Event object
        class MockStripeEvent:
            def __init__(self, payload):
                self.type = payload['type']
                self.data = type('obj', (object,), {'object': payload['data']['object']})()
        
        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.return_value = MockStripeEvent(webhook_payload)
            
            response = self.client.post(
                url,
                data=json.dumps(webhook_payload),
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='test_signature'
            )
        
        self.assertEqual(response.status_code, 200)
        
        # Check session was marked as completed
        session.refresh_from_db()
        self.assertTrue(session.is_completed)
        self.assertTrue(session.credits_added)
        self.assertEqual(session.stripe_payment_intent_id, 'pi_test_789')
        self.assertIsNotNone(session.completed_at)
        
        # Check credits were added to subscription
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, 25)
        
        # Check CreditTransaction was created
        transaction = CreditTransaction.objects.filter(
            checkout_session=session,
            transaction_type=CreditTransaction.TransactionType.PURCHASE
        ).first()
        
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, CreditTransaction.TransactionStatus.FULFILLED)
        self.assertEqual(transaction.credits_amount, 25)
        self.assertTrue(transaction.auto_processed)
        self.assertIsNotNone(transaction.fulfilled_at)
    
    def test_fulfill_purchase_already_completed(self):
        """Test that fulfilling an already completed purchase doesn't duplicate credits"""
        session = PerSceneCheckoutSessionRecord.objects.create(
            user=self.user,
            package=PerSceneCheckoutSessionRecord.CreditPackage.SMALL,
            credits_amount=10,
            price_cents=4999,
            stripe_checkout_session_id='cs_test_completed',
            credits_added=True
        )
        
        initial_credits = self.subscription.api_credits_remaining
        
        # Try to fulfill again
        session.fulfill_purchase()
        
        # Credits should not be added again
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.api_credits_remaining, initial_credits)
        
        # Should not create duplicate transactions
        transaction_count = CreditTransaction.objects.filter(checkout_session=session).count()
        self.assertEqual(transaction_count, 0)  # No transaction created for already completed
    
    def test_fulfill_purchase_user_no_subscription(self):
        """Test fulfilling purchase for user without subscription fails gracefully"""
        user_no_sub = User.objects.create_user(
            username='nosub',
            email='nosub@example.com'
        )
        
        session = PerSceneCheckoutSessionRecord.objects.create(
            user=user_no_sub,
            package=PerSceneCheckoutSessionRecord.CreditPackage.SMALL,
            credits_amount=10,
            price_cents=4999,
            stripe_checkout_session_id='cs_test_nosub'
        )
        
        # This should not crash, just log an error
        session.fulfill_purchase()
        
        # Session should not be marked as fulfilled
        self.assertFalse(session.credits_added)
        self.assertIsNone(session.completed_at)
    
    def test_create_checkout_non_enterprise_user(self):
        """Test that non-enterprise users cannot create checkout sessions"""
        self.subscription.tier = SubscriptionTier.PRO
        self.subscription.save()
        
        url = reverse('create-credits-purchase-checkout-session')
        
        response = self.client.post(url, {
            'package': PerSceneCheckoutSessionRecord.CreditPackage.SMALL
        })
        
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        
        self.assertIn('Not authorized', data['error'])
    
    def test_create_checkout_invalid_package(self):
        """Test creating checkout with invalid package"""
        url = reverse('create-credits-purchase-checkout-session')
        
        response = self.client.post(url, {
            'package': 'INVALID_PACKAGE'
        })
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        
        self.assertIn('Invalid package', data['error'])
    
    @patch('stripe.Price.list')
    def test_create_checkout_stripe_price_not_found(self, mock_price_list):
        """Test handling when Stripe price is not found"""
        mock_price_list.return_value = Mock(data=[])  # No prices found
        
        url = reverse('create-credits-purchase-checkout-session')
        
        response = self.client.post(url, {
            'package': PerSceneCheckoutSessionRecord.CreditPackage.SMALL
        })
        
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.content)
        
        self.assertIn('configuration error', data['error'])


@override_settings(BILLING_ENABLED=True)
class PerSceneCheckoutModelTests(TestCase):
    """Test PerSceneCheckoutSessionRecord model methods"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        self.subscription = UserSubscription.objects.create(
            user=self.user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            api_credits_remaining=5
        )
    
    def test_package_config_lookup(self):
        """Test package configuration lookup"""
        configs = {
            PerSceneCheckoutSessionRecord.CreditPackage.SMALL: {
                'credits': 10, 'stripe_lookup_key': 'credits_10_small'
            },
            PerSceneCheckoutSessionRecord.CreditPackage.MEDIUM: {
                'credits': 25, 'stripe_lookup_key': 'credits_25_medium'
            },
            PerSceneCheckoutSessionRecord.CreditPackage.LARGE: {
                'credits': 50, 'stripe_lookup_key': 'credits_50_large'
            },
            PerSceneCheckoutSessionRecord.CreditPackage.BULK: {
                'credits': 100, 'stripe_lookup_key': 'credits_100_bulk'
            },
        }
        
        for package, expected_config in configs.items():
            config = PerSceneCheckoutSessionRecord.get_package_config(package)
            self.assertEqual(config['credits'], expected_config['credits'])
            self.assertEqual(config['stripe_lookup_key'], expected_config['stripe_lookup_key'])
    
    def test_package_config_invalid(self):
        """Test package config for invalid package returns defaults"""
        config = PerSceneCheckoutSessionRecord.get_package_config('INVALID')
        
        self.assertEqual(config['credits'], 0)
        self.assertEqual(config['stripe_lookup_key'], '')
    
    def test_str_representation(self):
        """Test string representation of checkout session"""
        session = PerSceneCheckoutSessionRecord.objects.create(
            user=self.user,
            package=PerSceneCheckoutSessionRecord.CreditPackage.LARGE,
            credits_amount=50,
            price_cents=21499,
            stripe_checkout_session_id='cs_test_str'
        )
        
        expected = f"{self.user.username} - 50 Credits - $214.99 (Pending)"
        self.assertEqual(str(session), expected)
        
        # Test completed session
        session.is_completed = True
        session.save()
        
        expected_completed = f"{self.user.username} - 50 Credits - $214.99 (Completed)"
        self.assertEqual(str(session), expected_completed)

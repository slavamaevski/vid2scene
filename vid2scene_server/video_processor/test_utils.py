"""
Unit tests for video_processor.utils module
"""

from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth.models import User

from subscriptions.models import UserSubscription, SubscriptionTier
from .models import SceneProcessingJob
from .utils import validate_user_settings


@override_settings(BILLING_ENABLED=True)
class ValidateUserSettingsTests(TestCase):
    """Test validate_user_settings function with new user_subscription_tier parameter"""
    
    def setUp(self):
        # Create test users with different tiers
        self.free_user = User.objects.create_user(username='free', password='x')
        
        self.pro_user = User.objects.create_user(username='pro', password='x')
        UserSubscription.objects.create(
            user=self.pro_user,
            tier=SubscriptionTier.PRO,
            is_active=True
        )
        
        self.enterprise_user = User.objects.create_user(username='ent', password='x')
        UserSubscription.objects.create(
            user=self.enterprise_user,
            tier=SubscriptionTier.ENTERPRISE,
            is_active=True
        )
        
        self.enterprise_perscene_user = User.objects.create_user(username='entps', password='x')
        UserSubscription.objects.create(
            user=self.enterprise_perscene_user,
            tier=SubscriptionTier.ENTERPRISE_PERSCENE,
            is_active=True,
            api_credits_remaining=10
        )
    
    # =========================================================================
    # Test subscription tier parameter
    # =========================================================================
    
    def test_auto_detect_tier_free(self):
        """Test that tier is auto-detected for free users"""
        result = validate_user_settings(self.free_user)
        # Free user with default settings should pass
        self.assertTrue(result['valid'])
    
    def test_auto_detect_tier_pro(self):
        """Test that tier is auto-detected for pro users"""
        result = validate_user_settings(self.pro_user)
        self.assertTrue(result['valid'])
    
    def test_auto_detect_tier_enterprise(self):
        """Test that tier is auto-detected for enterprise users"""
        result = validate_user_settings(self.enterprise_user)
        self.assertTrue(result['valid'])
    
    def test_explicit_tier_free(self):
        """Test explicit tier parameter for free users"""
        result = validate_user_settings(self.free_user, user_subscription_tier='free')
        self.assertTrue(result['valid'])
    
    def test_explicit_tier_pro(self):
        """Test explicit tier parameter for pro users"""
        result = validate_user_settings(self.pro_user, user_subscription_tier='pro')
        self.assertTrue(result['valid'])
    
    def test_explicit_tier_enterprise(self):
        """Test explicit tier parameter for enterprise users"""
        result = validate_user_settings(self.enterprise_user, user_subscription_tier='enterprise')
        self.assertTrue(result['valid'])
    
    # =========================================================================
    # Test training_max_num_gaussians validation
    # =========================================================================
    
    def test_gaussians_within_range_free(self):
        """Test free user with valid gaussians count"""
        result = validate_user_settings(
            self.free_user,
            training_max_num_gaussians=SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE,
            user_subscription_tier='free'
        )
        self.assertTrue(result['valid'])
    
    def test_gaussians_exceeds_free_limit(self):
        """Test free user exceeding gaussians limit gets adjusted"""
        result = validate_user_settings(
            self.free_user,
            training_max_num_gaussians=10_000_000,  # Way over limit
            user_subscription_tier='free'
        )
        self.assertFalse(result['valid'])
        self.assertIn('training_max_num_gaussians', result['adjusted_values'])
        self.assertEqual(
            result['adjusted_values']['training_max_num_gaussians'],
            SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE
        )
        self.assertIn('gaussians', result['errors'][0].lower())
    
    def test_gaussians_pro_can_exceed_free_limit(self):
        """Test pro user can use more gaussians than free"""
        result = validate_user_settings(
            self.pro_user,
            training_max_num_gaussians=1_500_000,  # Over free limit (1.2M) but under premium limit (2M)
            user_subscription_tier='pro'
        )
        self.assertTrue(result['valid'])
    
    def test_gaussians_below_minimum(self):
        """Test that gaussians below minimum are rejected"""
        result = validate_user_settings(
            self.enterprise_user,
            training_max_num_gaussians=100,  # Below minimum
            user_subscription_tier='enterprise'
        )
        self.assertFalse(result['valid'])
        self.assertIn('at least', result['errors'][0])
    
    def test_gaussians_above_maximum(self):
        """Test that gaussians above maximum are rejected"""
        result = validate_user_settings(
            self.enterprise_user,
            training_max_num_gaussians=50_000_000,  # Above max
            user_subscription_tier='enterprise'
        )
        self.assertFalse(result['valid'])
        self.assertIn('cannot exceed', result['errors'][0])
    
    # =========================================================================
    # Test training_num_steps validation
    # =========================================================================
    
    def test_steps_within_range_free(self):
        """Test free user with valid steps count"""
        result = validate_user_settings(
            self.free_user,
            training_num_steps=SceneProcessingJob.MAX_NUM_STEPS_FREE,
            user_subscription_tier='free'
        )
        self.assertTrue(result['valid'])
    
    def test_steps_exceeds_free_limit(self):
        """Test free user exceeding steps limit gets adjusted"""
        result = validate_user_settings(
            self.free_user,
            training_num_steps=100_000,  # Way over limit
            user_subscription_tier='free'
        )
        self.assertFalse(result['valid'])
        self.assertIn('training_num_steps', result['adjusted_values'])
        self.assertEqual(
            result['adjusted_values']['training_num_steps'],
            SceneProcessingJob.MAX_NUM_STEPS_FREE
        )
        self.assertIn('steps', result['errors'][0].lower())
    
    def test_steps_pro_can_exceed_free_limit(self):
        """Test pro user can use more steps than free"""
        result = validate_user_settings(
            self.pro_user,
            training_num_steps=40_000,  # Over free limit (30K) but under premium limit (40K)
            user_subscription_tier='pro'
        )
        self.assertTrue(result['valid'])
    
    def test_steps_below_minimum(self):
        """Test that steps below minimum are rejected"""
        result = validate_user_settings(
            self.enterprise_user,
            training_num_steps=500,  # Below minimum
            user_subscription_tier='enterprise'
        )
        self.assertFalse(result['valid'])
        self.assertIn('at least', result['errors'][0])
    
    def test_steps_above_maximum(self):
        """Test that steps above maximum are rejected"""
        result = validate_user_settings(
            self.enterprise_user,
            training_num_steps=200_000,  # Above max
            user_subscription_tier='enterprise'
        )
        self.assertFalse(result['valid'])
        self.assertIn('cannot exceed', result['errors'][0])
    
    # =========================================================================
    # Test reconstruction_method validation
    # =========================================================================
    
    def test_glomap_allowed_for_free(self):
        """Test that GLOMAP (default) is allowed for free users"""
        result = validate_user_settings(
            self.free_user,
            reconstruction_method=SceneProcessingJob.ReconstructionMethod.GLOMAP,
            user_subscription_tier='free'
        )
        self.assertTrue(result['valid'])
    
    def test_advanced_method_rejected_for_free(self):
        """Test that advanced methods are rejected for free users"""
        result = validate_user_settings(
            self.free_user,
            reconstruction_method=SceneProcessingJob.ReconstructionMethod.COLMAP,
            user_subscription_tier='free'
        )
        self.assertFalse(result['valid'])
        self.assertEqual(
            result['adjusted_values']['reconstruction_method'],
            SceneProcessingJob.ReconstructionMethod.GLOMAP
        )
        self.assertIn('premium', result['errors'][0].lower())
    
    def test_advanced_method_allowed_for_pro(self):
        """Test that advanced methods are allowed for pro users"""
        result = validate_user_settings(
            self.pro_user,
            reconstruction_method=SceneProcessingJob.ReconstructionMethod.COLMAP,
            user_subscription_tier='pro'
        )
        self.assertTrue(result['valid'])
    
    def test_advanced_method_allowed_for_enterprise(self):
        """Test that advanced methods are allowed for enterprise users"""
        result = validate_user_settings(
            self.enterprise_user,
            reconstruction_method=SceneProcessingJob.ReconstructionMethod.VGGT,
            user_subscription_tier='enterprise'
        )
        self.assertTrue(result['valid'])
    
    # =========================================================================
    # Test AprilTag validation (Enterprise-only)
    # =========================================================================
    
    def test_apriltag_rejected_for_free(self):
        """Test that AprilTag is rejected for free users"""
        result = validate_user_settings(
            self.free_user,
            apriltag_size_mm=95.6,
            user_subscription_tier='free'
        )
        self.assertFalse(result['valid'])
        self.assertIsNone(result['adjusted_values']['apriltag_size_mm'])
        self.assertIn('Enterprise-only', result['errors'][0])
    
    def test_apriltag_rejected_for_pro(self):
        """Test that AprilTag is rejected for pro users"""
        result = validate_user_settings(
            self.pro_user,
            apriltag_size_mm=95.6,
            user_subscription_tier='pro'
        )
        self.assertFalse(result['valid'])
        self.assertIsNone(result['adjusted_values']['apriltag_size_mm'])
        self.assertIn('Enterprise-only', result['errors'][0])
    
    def test_apriltag_allowed_for_enterprise(self):
        """Test that AprilTag is allowed for enterprise users"""
        result = validate_user_settings(
            self.enterprise_user,
            apriltag_size_mm=95.6,
            user_subscription_tier='enterprise'
        )
        self.assertTrue(result['valid'])
    
    def test_apriltag_allowed_for_enterprise_perscene(self):
        """Test that AprilTag is allowed for enterprise per-scene users"""
        result = validate_user_settings(
            self.enterprise_perscene_user,
            apriltag_size_mm=55.6,
            user_subscription_tier='enterprise_perscene'
        )
        self.assertTrue(result['valid'])
    
    def test_apriltag_size_too_small(self):
        """Test that AprilTag size below 1mm is rejected"""
        result = validate_user_settings(
            self.enterprise_user,
            apriltag_size_mm=0.5,
            user_subscription_tier='enterprise'
        )
        self.assertFalse(result['valid'])
        self.assertIn('1mm and 1000mm', result['errors'][0])
    
    def test_apriltag_size_too_large(self):
        """Test that AprilTag size above 1000mm is rejected"""
        result = validate_user_settings(
            self.enterprise_user,
            apriltag_size_mm=1500.0,
            user_subscription_tier='enterprise'
        )
        self.assertFalse(result['valid'])
        self.assertIn('1mm and 1000mm', result['errors'][0])
    
    def test_apriltag_size_valid_range(self):
        """Test that AprilTag sizes in valid range are accepted"""
        test_sizes = [1.0, 10.5, 95.6, 250.0, 999.9, 1000.0]
        
        for size in test_sizes:
            result = validate_user_settings(
                self.enterprise_user,
                apriltag_size_mm=size,
                user_subscription_tier='enterprise'
            )
            self.assertTrue(result['valid'], f"Size {size}mm should be valid")
    
    def test_apriltag_optional(self):
        """Test that AprilTag is optional (None is valid)"""
        result = validate_user_settings(
            self.enterprise_user,
            apriltag_size_mm=None,
            user_subscription_tier='enterprise'
        )
        self.assertTrue(result['valid'])
    
    # =========================================================================
    # Test multiple validation errors
    # =========================================================================
    
    def test_multiple_errors(self):
        """Test that multiple validation errors are all returned"""
        result = validate_user_settings(
            self.free_user,
            training_max_num_gaussians=50_000_000,  # Too many
            training_num_steps=100_000,  # Too many
            reconstruction_method=SceneProcessingJob.ReconstructionMethod.COLMAP,  # Premium
            apriltag_size_mm=95.6,  # Enterprise-only
            user_subscription_tier='free'
        )
        self.assertFalse(result['valid'])
        # Should have multiple errors
        self.assertGreaterEqual(len(result['errors']), 3)
        
        # Should have adjusted values for all violations
        self.assertIn('training_max_num_gaussians', result['adjusted_values'])
        self.assertIn('training_num_steps', result['adjusted_values'])
        self.assertIn('reconstruction_method', result['adjusted_values'])
        self.assertIn('apriltag_size_mm', result['adjusted_values'])
    
    # =========================================================================
    # Test return value structure
    # =========================================================================
    
    def test_return_value_structure_valid(self):
        """Test that valid results have correct structure"""
        result = validate_user_settings(self.enterprise_user)
        
        self.assertIn('valid', result)
        self.assertIn('errors', result)
        self.assertIn('adjusted_values', result)
        
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(len(result['adjusted_values']), 0)
    
    def test_return_value_structure_invalid(self):
        """Test that invalid results have correct structure"""
        result = validate_user_settings(
            self.free_user,
            apriltag_size_mm=95.6,
            user_subscription_tier='free'
        )
        
        self.assertIn('valid', result)
        self.assertIn('errors', result)
        self.assertIn('adjusted_values', result)
        
        self.assertFalse(result['valid'])
        self.assertGreater(len(result['errors']), 0)
        self.assertGreater(len(result['adjusted_values']), 0)


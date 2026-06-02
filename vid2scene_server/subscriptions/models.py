from django.db import models
from django.contrib.auth.models import User
from datetime import datetime, timezone
import stripe
import logging

logger = logging.getLogger(__name__)

class SubscriptionTier(models.TextChoices):
    PRO = 'PRO', 'Pro'
    ENTERPRISE = 'ENTERPRISE', 'Enterprise'
    ENTERPRISE_PERSCENE = 'ENTERPRISE_PERSCENE', 'Enterprise Per-Scene'

class UserSubscription(models.Model):
    """Single record tracking a user's current subscription status"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription')
    tier = models.CharField(max_length=30, choices=SubscriptionTier.choices, default=SubscriptionTier.PRO)
    is_active = models.BooleanField(default=False)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    
    # Simple scene credits for ENTERPRISE_PERSCENE tier
    api_credits_remaining = models.PositiveIntegerField(default=0, help_text="Number of scene API credits remaining")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.tier} ({'Active' if self.is_active else 'Inactive'})"

    def check_and_update_pro_active(self):
        """Check if this is an active PRO subscription"""
        # Check if not active or not PRO
        if not self.is_active or self.tier != SubscriptionTier.PRO:
            return False
            
        # Check if expired
        now = datetime.now(timezone.utc)
        if self.valid_until and self.valid_until < now:
            # Verify with Stripe
            try:
                if not self.stripe_subscription_id:
                    self.is_active = False
                    self.save(update_fields=['is_active', 'updated_at'])
                    return False
                    
                subscription = stripe.Subscription.retrieve(self.stripe_subscription_id)
                
                # Update local record
                is_active = subscription.status == 'active'
                self.is_active = is_active
                
                if is_active:
                    self.valid_until = datetime.fromtimestamp(
                        subscription.current_period_end, 
                        timezone.utc
                    )
                
                self.save(update_fields=['is_active', 'valid_until', 'updated_at'])
                return is_active
                
            except stripe.error.StripeError:
                logger.exception("Failed to verify subscription with Stripe")
                return False
        
        # All checks passed
        return True
    
    
    def add_api_credits(self, credits_amount):
        """Add API credits to this subscription"""
        self.api_credits_remaining += credits_amount
        self.save(update_fields=['api_credits_remaining', 'updated_at'])
        return self.api_credits_remaining

class CheckoutSessionRecord(models.Model):
    """
    Transaction record for checkout sessions.
    Only tracks the checkout process, not subscription state.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    stripe_checkout_session_id = models.CharField(max_length=255, unique=True)
    stripe_price_id = models.CharField(max_length=255)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Optional reference to the resulting subscription (if successful)
    subscription = models.ForeignKey(
        'UserSubscription', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )


class CreditTransaction(models.Model):
    """Record of all credit transactions (purchases, refunds, adjustments)"""
    
    class TransactionType(models.TextChoices):
        PURCHASE = 'PURCHASE', 'Credit Purchase'
        REFUND = 'REFUND', 'Credit Refund'
        ADJUSTMENT = 'ADJUSTMENT', 'Manual Adjustment'
        CONSUMPTION = 'CONSUMPTION', 'Credit Consumption'
    
    class TransactionStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        FULFILLED = 'FULFILLED', 'Fulfilled'
        FAILED = 'FAILED', 'Failed'
        CANCELLED = 'CANCELLED', 'Cancelled'
    
    # Core transaction data
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='credit_transactions')
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    status = models.CharField(max_length=20, choices=TransactionStatus.choices, default=TransactionStatus.PENDING)
    credits_amount = models.IntegerField(help_text="Credits amount (positive for additions, negative for deductions)")
    
    # Optional relationships
    checkout_session = models.OneToOneField(
        'PerSceneCheckoutSessionRecord', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='credit_transaction'
    )
    scene_processing_job = models.ForeignKey(
        'video_processor.SceneProcessingJob', 
        on_delete=models.SET_NULL, 
        null=True,
        blank=True,
        related_name='credit_transactions'
    )
    # Store essential job info for audit trail (preserved even after job deletion)
    job_title = models.CharField(
        max_length=255, 
        blank=True, 
        help_text="Title of the job for audit trail purposes"
    )
    job_created_at = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="Creation timestamp of the job for audit trail purposes"
    )
    
    # Notes and details
    user_notes = models.TextField(blank=True, help_text="User's notes or request details")
    admin_notes = models.TextField(blank=True, help_text="Admin notes and decision details")
    
    # Processing tracking
    auto_processed = models.BooleanField(default=False, help_text="Was this automatically processed?")
    processed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='processed_credit_transactions',
        help_text="Admin who processed this transaction"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['transaction_type', 'status']),
            models.Index(fields=['scene_processing_job']),
            models.Index(fields=['checkout_session']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Credit Transaction"
        verbose_name_plural = "Credit Transactions"
    
    def __str__(self):
        sign = "+" if self.credits_amount > 0 else ""
        return f"Transaction #{self.id} - {self.user.username} - {sign}{self.credits_amount} credits ({self.get_status_display()})"
    
    @property
    def subscription(self):
        """Convenience property to access user's subscription"""
        return self.user.subscription
    
    def fulfill(self, processed_by_user=None, admin_notes=""):
        """Fulfill the transaction by applying credits to user's balance"""
        if self.status == self.TransactionStatus.FULFILLED:
            logger.warning(f"Transaction #{self.id} already fulfilled")
            return False
            
        if self.status not in [self.TransactionStatus.PENDING]:
            raise ValueError(f"Cannot fulfill transaction with status: {self.status}")
        
        try:
            # Apply credits to user's subscription
            if hasattr(self.user, 'subscription'):
                self.user.subscription.add_api_credits(self.credits_amount)
                
                # Update transaction record
                self.status = self.TransactionStatus.FULFILLED
                self.fulfilled_at = datetime.now(timezone.utc)
                self.processed_by = processed_by_user
                if admin_notes:
                    self.admin_notes = admin_notes
                self.save()
                
                logger.info(f"Fulfilled transaction #{self.id}: {self.credits_amount} credits for {self.user.username}")
                return True
            else:
                logger.error(f"User {self.user.username} has no subscription for transaction #{self.id}")
                self.status = self.TransactionStatus.FAILED
                self.admin_notes = "User has no subscription"
                self.save()
                return False
                
        except Exception as e:
            logger.error(f"Failed to fulfill transaction #{self.id}: {str(e)}")
            self.status = self.TransactionStatus.FAILED
            self.admin_notes = f"Error: {str(e)}"
            self.save()
            return False
    
    def cancel(self, processed_by_user=None, admin_notes=""):
        """Cancel the transaction"""
        if self.status == self.TransactionStatus.FULFILLED:
            raise ValueError("Cannot cancel fulfilled transaction")
            
        self.status = self.TransactionStatus.CANCELLED
        self.processed_by = processed_by_user
        if admin_notes:
            self.admin_notes = admin_notes
        self.save()
        
        logger.info(f"Cancelled transaction #{self.id}")
    
    @classmethod
    def create_purchase_transaction(cls, user, checkout_session, credits_amount):
        """Create a purchase transaction for a checkout session"""
        return cls.objects.create(
            user=user,
            transaction_type=cls.TransactionType.PURCHASE,
            credits_amount=credits_amount,
            checkout_session=checkout_session,
            auto_processed=True
        )
    
    @classmethod
    def create_refund_transaction(cls, user, scene_job, credits_amount=1, user_notes="", auto_process=False):
        """Create a refund transaction for a scene processing job"""
        transaction = cls.objects.create(
            user=user,
            transaction_type=cls.TransactionType.REFUND,
            credits_amount=credits_amount,
            scene_processing_job=scene_job,
            job_title=scene_job.title[:255] if scene_job and scene_job.title else "",
            job_created_at=scene_job.uploaded_at if scene_job else None,
            user_notes=user_notes,
            auto_processed=auto_process
        )
        
        if auto_process:
            transaction.fulfill()
            
        return transaction


class RefundRequest(models.Model):
    """User requests for credit refunds - separate from actual credit transactions"""
    
    class RefundReason(models.TextChoices):
        TECHNICAL_FAILURE = 'TECHNICAL_FAILURE', 'Technical Failure'
        QUALITY_UNSATISFIED = 'QUALITY_UNSATISFIED', 'Unsatisfied with Quality'
        OTHER = 'OTHER', 'Other'
    
    class RefundStatus(models.TextChoices):
        REQUESTED = 'REQUESTED', 'Requested'
        APPROVED = 'APPROVED', 'Approved'
        DENIED = 'DENIED', 'Denied'
        CANCELLED = 'CANCELLED', 'Cancelled'
    
    # Core request data
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='refund_requests')
    scene_processing_job = models.ForeignKey(
        'video_processor.SceneProcessingJob', 
        on_delete=models.CASCADE,
        related_name='refund_requests'
    )
    reason = models.CharField(max_length=30, choices=RefundReason.choices)
    status = models.CharField(max_length=20, choices=RefundStatus.choices, default=RefundStatus.REQUESTED)
    credits_requested = models.PositiveIntegerField(default=1, help_text="Number of credits requested for refund")
    
    # Request details
    customer_notes = models.TextField(blank=True, help_text="Customer's explanation of the issue")
    admin_notes = models.TextField(blank=True, help_text="Admin's notes and decision reasoning")
    
    # Processing tracking
    auto_approved = models.BooleanField(default=False, help_text="Was this automatically approved?")
    processed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='processed_refund_requests',
        help_text="Admin who processed this request"
    )
    
    # Link to resulting credit transaction (if approved)
    credit_transaction = models.OneToOneField(
        'CreditTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='refund_request'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['scene_processing_job']),
            models.Index(fields=['status', 'created_at']),
        ]
        verbose_name = "Refund Request"
        verbose_name_plural = "Refund Requests"
    
    def __str__(self):
        return f"Refund Request #{self.id} - {self.user.username} - {self.get_status_display()}"
    
    def approve(self, processed_by_user=None, admin_notes=""):
        """Approve the refund request and create credit transaction"""
        # If already approved, don't create duplicate transaction
        if self.status == self.RefundStatus.APPROVED:
            logger.warning(f"Refund request #{self.id} is already approved")
            return
        
        
        # Create and fulfill credit transaction
        transaction = CreditTransaction.create_refund_transaction(
            user=self.user,
            scene_job=self.scene_processing_job,
            credits_amount=self.credits_requested,
            user_notes=self.customer_notes,
            auto_process=True
        )
        
        # Update refund request
        self.status = self.RefundStatus.APPROVED
        self.processed_at = datetime.now(timezone.utc)
        self.processed_by = processed_by_user
        self.credit_transaction = transaction
        if admin_notes:
            self.admin_notes = admin_notes
        self.save()
        
        logger.info(f"Approved refund request #{self.id} and created transaction #{transaction.id}")
        return transaction
    
    def deny(self, processed_by_user=None, admin_notes=""):
        """Deny the refund request"""
        if self.status != self.RefundStatus.REQUESTED:
            raise ValueError(f"Cannot deny request with status: {self.status}")
        
        self.status = self.RefundStatus.DENIED
        self.processed_at = datetime.now(timezone.utc)
        self.processed_by = processed_by_user
        if admin_notes:
            self.admin_notes = admin_notes
        self.save()
        
        logger.info(f"Denied refund request #{self.id}")
    
    def cancel(self):
        """Cancel the refund request (user-initiated)"""
        if self.status != self.RefundStatus.REQUESTED:
            raise ValueError(f"Cannot cancel request with status: {self.status}")
        
        self.status = self.RefundStatus.CANCELLED
        self.save()
        
        logger.info(f"Cancelled refund request #{self.id}")
    
    @classmethod
    def create_request(cls, user, scene_job, reason, customer_notes="", auto_approve_technical=True):
        """Create a new refund request, with optional auto-approval for technical failures"""
        request = cls.objects.create(
            user=user,
            scene_processing_job=scene_job,
            reason=reason,
            customer_notes=customer_notes
        )
        
        # Auto-approve technical failures
        if auto_approve_technical and reason == cls.RefundReason.TECHNICAL_FAILURE:
            request.auto_approved = True
            request.save()
            request.approve(admin_notes="Automatically approved due to technical failure")
        
        return request


class PerSceneCheckoutSessionRecord(models.Model):
    """Checkout sessions for enterprise per-scene credit purchases"""
    
    class CreditPackage(models.TextChoices):
        SMALL = 'SMALL', '10 Credits - $49.99'
        MEDIUM = 'MEDIUM', '25 Credits - $114.99' 
        LARGE = 'LARGE', '50 Credits - $214.99'
        BULK = 'BULK', '100 Credits - $399.99'
    
    # Package configuration mapping
    PACKAGE_CONFIG = {
        CreditPackage.SMALL: {
            'credits': 10, 
            'stripe_lookup_key': 'credits_10_small'
        },
        CreditPackage.MEDIUM: {
            'credits': 25, 
            'stripe_lookup_key': 'credits_25_medium'
        },
        CreditPackage.LARGE: {
            'credits': 50, 
            'stripe_lookup_key': 'credits_50_large'
        },
        CreditPackage.BULK: {
            'credits': 100, 
            'stripe_lookup_key': 'credits_100_bulk'
        },
    }
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='perscene_checkouts')
    package = models.CharField(max_length=10, choices=CreditPackage.choices)
    credits_amount = models.PositiveIntegerField()
    price_cents = models.PositiveIntegerField(help_text="Price in cents")
    
    # Stripe details
    stripe_checkout_session_id = models.CharField(max_length=255, unique=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    is_completed = models.BooleanField(default=False)
    credits_added = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_completed']),
            models.Index(fields=['stripe_checkout_session_id']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = "Per-Scene Checkout Session"
        verbose_name_plural = "Per-Scene Checkout Sessions"
    
    def __str__(self):
        return f"{self.user.username} - {self.get_package_display()} ({'Completed' if self.is_completed else 'Pending'})"
    
    @classmethod
    def get_package_config(cls, package):
        """Get configuration for a package"""
        return cls.PACKAGE_CONFIG.get(package, {
            'credits': 0, 
            'stripe_lookup_key': ''
        })
    
    def fulfill_purchase(self):
        """Create and fulfill a credit transaction for this purchase"""
        if self.credits_added:
            logger.warning(f"Credits already added for checkout session {self.id}")
            return
        
        # Check if transaction already exists
        existing_transaction = getattr(self, 'credit_transaction', None)
        if existing_transaction:
            if existing_transaction.status == CreditTransaction.TransactionStatus.FULFILLED:
                logger.warning(f"Transaction already fulfilled for checkout session {self.id}")
                return
            # Try to fulfill existing transaction
            transaction = existing_transaction
        else:
            # Create new purchase transaction
            transaction = CreditTransaction.create_purchase_transaction(
                user=self.user,
                checkout_session=self,
                credits_amount=self.credits_amount
            )
        
        # Fulfill the transaction (this applies credits and updates status)
        if transaction.fulfill(admin_notes="Automated fulfillment from Stripe webhook"):
            self.credits_added = True
            self.completed_at = datetime.now(timezone.utc)
            self.save()
            logger.info(f"Fulfilled purchase transaction #{transaction.id}: {self.credits_amount} credits for {self.user.username}")
        else:
            logger.error(f"Failed to fulfill purchase transaction for checkout session {self.id}")

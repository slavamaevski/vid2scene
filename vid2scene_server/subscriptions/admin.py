from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import UserSubscription, CheckoutSessionRecord, CreditTransaction, PerSceneCheckoutSessionRecord, RefundRequest, SubscriptionTier

@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'tier', 'is_active', 'api_credits_remaining', 'valid_until', 'stripe_customer_id', 'created_at')
    list_filter = ('is_active', 'tier', 'created_at', 'api_credits_remaining')
    search_fields = ('user__email', 'user__username', 'stripe_customer_id', 'stripe_subscription_id')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    list_select_related = ('user',)
    list_editable = ('api_credits_remaining',)  # Allow inline editing of credits
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'is_active', 'tier')
        }),
        ('API Credits', {
            'fields': ('api_credits_remaining',),
            'description': 'API credits for Enterprise Per-Scene users. Only applies to ENTERPRISE_PERSCENE tier.'
        }),
        ('Stripe Details', {
            'fields': ('stripe_customer_id', 'stripe_subscription_id', 'valid_until')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
    

@admin.register(CheckoutSessionRecord)
class CheckoutSessionRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_completed', 'created_at', 'subscription_link')
    list_filter = ('is_completed', 'created_at')
    search_fields = ('user__email', 'user__username', 'stripe_checkout_session_id', 'stripe_price_id')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    list_select_related = ('user', 'subscription')
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'is_completed')
        }),
        ('Stripe Details', {
            'fields': ('stripe_checkout_session_id', 'stripe_price_id', 'subscription')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def subscription_link(self, obj):
        if obj.subscription:
            return obj.subscription.tier
        return "-"
    subscription_link.short_description = "Subscription Tier"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'subscription')


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user_email', 'transaction_type', 'status', 
        'credits_amount', 'auto_processed', 'created_at', 'fulfilled_at'
    )
    list_filter = (
        'transaction_type', 'status', 'auto_processed', 'created_at', 'fulfilled_at'
    )
    search_fields = (
        'user__email', 'user__username', 'scene_processing_job__title',
        'user_notes', 'admin_notes'
    )
    readonly_fields = ('created_at', 'processed_by', 'fulfilled_at')
    date_hierarchy = 'created_at'
    list_select_related = ('user', 'scene_processing_job', 'checkout_session', 'processed_by')
    ordering = ['-created_at']
    
    fieldsets = (
        ('Transaction Details', {
            'fields': (
                'user', 'transaction_type', 'status', 
                'credits_amount'
            ),
            'description': 'Use positive numbers for credits to add, negative for deductions. Status will auto-update when saved.'
        }),
        ('Related Objects', {
            'fields': ('scene_processing_job', 'checkout_session'),
            'description': 'Optional: Link to related checkout session or scene processing job'
        }),
        ('Notes', {
            'fields': ('user_notes', 'admin_notes'),
            'description': 'Document the reason for this manual transaction'
        }),
        ('Processing Settings', {
            'fields': ('auto_processed',),
            'description': 'Check to automatically fulfill this transaction upon save'
        }),
        ('Metadata', {
            'fields': ('created_at', 'fulfilled_at', 'processed_by'),
            'classes': ('collapse',),
            'description': 'Automatically managed fields'
        }),
    )
    
    actions = []  # Disable bulk actions for credit transactions
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = "User Email"
    user_email.admin_order_field = 'user__email'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'scene_processing_job', 'checkout_session', 'processed_by'
        )
    
    
    def save_model(self, request, obj, form, change):
        """Handle manual credit transactions"""
        # For new manual transactions
        if not change:
            # Set default transaction type for manual entries
            if not obj.transaction_type:
                obj.transaction_type = CreditTransaction.TransactionType.ADJUSTMENT
            
            # Auto-fulfill if requested
            if obj.auto_processed:
                obj.status = CreditTransaction.TransactionStatus.PENDING
                super().save_model(request, obj, form, change)
                obj.fulfill(processed_by_user=request.user, admin_notes="Manual transaction auto-fulfilled")
                return
        
        # Handle status changes
        if change and 'status' in form.changed_data:
            if obj.status == CreditTransaction.TransactionStatus.FULFILLED:
                if not obj.processed_by:
                    obj.processed_by = request.user
                if not obj.fulfilled_at:
                    obj.fulfilled_at = timezone.now()
        
        super().save_model(request, obj, form, change)


@admin.register(PerSceneCheckoutSessionRecord)
class PerSceneCheckoutSessionRecordAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user_email', 'package', 'credits_amount', 'price_display', 
        'is_completed', 'credits_added', 'created_at', 'completed_at'
    )
    list_filter = (
        'package', 'is_completed', 'credits_added', 'created_at', 'completed_at'
    )
    search_fields = (
        'user__email', 'user__username', 'stripe_checkout_session_id', 'stripe_payment_intent_id'
    )
    readonly_fields = (
        'user', 'package', 'credits_amount', 'price_cents', 
        'stripe_checkout_session_id', 'stripe_payment_intent_id', 
        'created_at', 'completed_at'
    )
    date_hierarchy = 'created_at'
    list_select_related = ('user',)
    ordering = ['-created_at']
    
    fieldsets = (
        ('Checkout Details', {
            'fields': (
                'user', 'package', 'credits_amount', 'price_cents'
            )
        }),
        ('Status', {
            'fields': ('is_completed', 'credits_added')
        }),
        ('Stripe Details', {
            'fields': ('stripe_checkout_session_id', 'stripe_payment_intent_id'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = "User Email"
    user_email.admin_order_field = 'user__email'
    
    def price_display(self, obj):
        return f"${obj.price_cents / 100:.2f}"
    price_display.short_description = "Price"
    price_display.admin_order_field = 'price_cents'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(RefundRequest)
class RefundRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user_email', 'scene_job_title', 'scene_viewer_link', 'reason', 'status', 
        'credits_requested', 'auto_approved', 'created_at', 'processed_at'
    )
    list_filter = (
        'reason', 'status', 'auto_approved', 'created_at', 'processed_at'
    )
    search_fields = (
        'user__email', 'user__username', 'scene_processing_job__title',
        'customer_notes', 'admin_notes'
    )
    readonly_fields = (
        'user', 'scene_processing_job', 'scene_viewer_link', 'reason', 'credits_requested',
        'customer_notes', 'auto_approved', 'created_at', 'credit_transaction'
    )
    date_hierarchy = 'created_at'
    list_select_related = ('user', 'scene_processing_job', 'processed_by', 'credit_transaction')
    ordering = ['-created_at']
    
    fieldsets = (
        ('Request Details', {
            'fields': (
                'user', 'scene_processing_job', 'scene_viewer_link', 'reason', 'status',
                'credits_requested'
            )
        }),
        ('Notes', {
            'fields': ('customer_notes', 'admin_notes')
        }),
        ('Processing', {
            'fields': ('auto_approved', 'processed_by', 'processed_at', 'credit_transaction'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    # No bulk actions - each refund request should be reviewed individually
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = "User Email"
    user_email.admin_order_field = 'user__email'
    
    def scene_job_title(self, obj):
        return obj.scene_processing_job.title if obj.scene_processing_job else "-"
    scene_job_title.short_description = "Scene Job"
    scene_job_title.admin_order_field = 'scene_processing_job__title'
    
    def scene_viewer_link(self, obj):
        if obj.scene_processing_job and obj.scene_processing_job.ply_file:
            viewer_url = reverse('splat_viewer_spj_id', args=[obj.scene_processing_job.id])
            return format_html('<a href="{}" target="_blank">View Scene</a>', viewer_url)
        elif obj.scene_processing_job:
            return format_html('<span style="color: #999;">Not Finished</span>')
        else:
            return "-"
    scene_viewer_link.short_description = "Viewer"
    scene_viewer_link.admin_order_field = 'scene_processing_job__ply_file'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'scene_processing_job', 'processed_by', 'credit_transaction'
        )
    
    
    def save_model(self, request, obj, form, change):
        """Handle status changes by calling appropriate model methods"""
        if change and 'status' in form.changed_data:
            old_status = RefundRequest.objects.get(pk=obj.pk).status if obj.pk else None
            
            # If changing to APPROVED from any other status, call approve() method
            if (old_status != RefundRequest.RefundStatus.APPROVED and 
                obj.status == RefundRequest.RefundStatus.APPROVED):
                
                # Get admin notes from the form
                admin_notes = form.cleaned_data.get('admin_notes', '')
                
                # Call the approve method which creates and fulfills the transaction
                obj.status = RefundRequest.RefundStatus.REQUESTED  # Reset to call approve()
                obj.approve(processed_by_user=request.user, admin_notes=admin_notes)
                return  # approve() already saves the object
            
            # If changing from REQUESTED to DENIED, call deny() method  
            elif (old_status == RefundRequest.RefundStatus.REQUESTED and 
                  obj.status == RefundRequest.RefundStatus.DENIED):
                
                admin_notes = form.cleaned_data.get('admin_notes', '')
                obj.status = RefundRequest.RefundStatus.REQUESTED  # Reset to call deny()
                obj.deny(processed_by_user=request.user, admin_notes=admin_notes)
                return  # deny() already saves the object
            
            # For other status changes, just set metadata
            else:
                if obj.status in [RefundRequest.RefundStatus.APPROVED, RefundRequest.RefundStatus.DENIED]:
                    if not obj.processed_by:
                        obj.processed_by = request.user
                    if not obj.processed_at:
                        obj.processed_at = timezone.now()
        
        super().save_model(request, obj, form, change)

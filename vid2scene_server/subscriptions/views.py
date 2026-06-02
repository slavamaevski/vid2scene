import datetime
from django.shortcuts import render

# Create your views here.
import os
from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
import stripe
from . import models
from .models import PerSceneCheckoutSessionRecord
import logging
from datetime import datetime, timezone
from waffle.decorators import waffle_flag

logger = logging.getLogger(__name__)

# Optional: billing is disabled by default (see settings.BILLING_ENABLED). The
# subscription views below are additionally gated behind the 'enable_subscriptions'
# waffle flag, so they never run without a configured key.
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
stripe.api_version = '2024-12-18.acacia'

@waffle_flag('enable_subscriptions')
def subscribe(request) -> HttpResponse:
    return render(request, 'subscriptions/subscribe.html')

@login_required
@waffle_flag('enable_subscriptions')
def success(request) -> HttpResponse:
    return render(request, 'subscriptions/success.html')

@login_required
@waffle_flag('enable_subscriptions')
def create_checkout_session(request) -> HttpResponse:
    price_lookup_key = request.POST['price_lookup_key']
    try:
        prices = stripe.Price.list(lookup_keys=[price_lookup_key], expand=['data.product'])
        price_item = prices.data[0]

        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {'price': price_item.id, 'quantity': 1},
                # You could add differently priced services here, e.g., standard, business, first-class.
            ],
            mode='subscription',
            success_url=request.build_absolute_uri(reverse('subscribe')) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(reverse('subscribe')),
            customer_email=request.user.email,
            automatic_tax={'enabled': True},
        )

        # We connect the checkout session to the user who initiated the checkout.
        models.CheckoutSessionRecord.objects.create(
            user=request.user,
            stripe_checkout_session_id=checkout_session.id,
            stripe_price_id=price_item.id,
        )

        logger.info('Created checkout session for user_id %s with price %s', 
                   request.user.id, price_item.id)

        return redirect(
            checkout_session.url,  # Either the success or cancel url.
            code=303
        )
    except Exception as e:
        logger.error('Failed to create checkout session for user_id %s: %s', 
                    request.user.id, str(e), exc_info=True)
        return HttpResponse("Server error", status=500)

@login_required
@waffle_flag('enable_subscriptions')
def direct_to_customer_portal(request) -> HttpResponse:
    try:
        # Get user's subscription directly
        if not hasattr(request.user, 'subscription'):
            return HttpResponse("No subscription found", status=404)
            
        if not request.user.subscription.stripe_customer_id:
            return HttpResponse("No customer ID found", status=404)
            
        # Get the previous URL from the referer header, fallback to subscribe page
        previous_url = request.META.get('HTTP_REFERER')
        return_url = request.build_absolute_uri(previous_url) if previous_url else request.build_absolute_uri(reverse('subscribe'))
        
        portal_session = stripe.billing_portal.Session.create(
            customer=request.user.subscription.stripe_customer_id,
            return_url=return_url
        )
        return redirect(portal_session.url, code=303)
    except Exception as e:
        logger.error("Error creating portal session: %s", str(e))
        return HttpResponse("Error creating portal session", status=500)


@login_required
def create_credits_purchase_checkout_session(request):
    """Create Stripe checkout session for credit purchases"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    # Check if user is enterprise per-scene
    if not (hasattr(request.user, 'subscription') and 
            request.user.subscription.tier == models.SubscriptionTier.ENTERPRISE_PERSCENE):
        return JsonResponse({'success': False, 'error': 'Not authorized for credit purchases'}, status=403)
    
    package = request.POST.get('package')
    if package not in PerSceneCheckoutSessionRecord.CreditPackage.values:
        return JsonResponse({'success': False, 'error': 'Invalid package'}, status=400)
    
    try:
        # Get package configuration
        package_config = PerSceneCheckoutSessionRecord.get_package_config(package)
        credits = package_config['credits']
        lookup_key = package_config['stripe_lookup_key']
        
        # Get Stripe price using lookup key
        prices = stripe.Price.list(lookup_keys=[lookup_key], expand=['data.product'])
        if not prices.data:
            logger.error(f'No Stripe price found for lookup key: {lookup_key}')
            return JsonResponse({'success': False, 'error': 'Package configuration error'}, status=500)
            
        price_item = prices.data[0]
        price_cents = price_item.unit_amount  # Get actual price from Stripe
        
        # Create Stripe checkout session
        checkout_session = stripe.checkout.Session.create(
            line_items=[{
                'price': price_item.id,
                'quantity': 1,
            }],
            mode='payment',  # One-time payment, not subscription
            success_url=request.build_absolute_uri(reverse('profile')) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(reverse('profile')),
            customer_email=request.user.email,
            automatic_tax={'enabled': True},
            metadata={
                'user_id': str(request.user.id),
                'package': package,
                'credits': str(credits),
                'lookup_key': lookup_key,
            }
        )
        
        # Create per-scene checkout record
        PerSceneCheckoutSessionRecord.objects.create(
            user=request.user,
            package=package,
            credits_amount=credits,
            price_cents=price_cents,
            stripe_checkout_session_id=checkout_session.id,
        )
        
        logger.info(f'Created per-scene checkout for user {request.user.id}: {credits} credits for ${price_cents/100}')
        
        return JsonResponse({
            'success': True,
            'checkout_url': checkout_session.url
        })
        
    except Exception as e:
        logger.error(f'Failed to create per-scene checkout for user {request.user.id}: {str(e)}', exc_info=True)
        return JsonResponse({'success': False, 'error': 'Failed to create checkout session'}, status=500)

@csrf_exempt
def collect_stripe_webhook(request) -> JsonResponse:
    """
    Stripe sends webhook events to this endpoint.
    We verify the webhook signature and updates the database record.
    """
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
    signature = request.META["HTTP_STRIPE_SIGNATURE"]
    payload = request.body

    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=signature, secret=webhook_secret
        )
    except ValueError as e:  # Invalid payload.
        raise ValueError(e)
    except stripe.error.SignatureVerificationError as e:  # Invalid signature
        raise stripe.error.SignatureVerificationError(e)

    _update_record(event)

    return JsonResponse({'status': 'success'})

def _update_record(webhook_event: stripe.Event):
    data_object = webhook_event.data.object
    event_type = webhook_event.type

    try:
        if event_type == 'checkout.session.completed':
            session_id = data_object['id']
            
            # Try to find subscription checkout first
            subscription_checkout = models.CheckoutSessionRecord.objects.filter(
                stripe_checkout_session_id=session_id
            ).first()
            
            # Try to find per-scene checkout
            perscene_checkout = PerSceneCheckoutSessionRecord.objects.filter(
                stripe_checkout_session_id=session_id
            ).first()
            
            if subscription_checkout:
                # Handle subscription checkout
                subscription, created = models.UserSubscription.objects.update_or_create(
                    user=subscription_checkout.user,
                    defaults={
                        'tier': models.SubscriptionTier.PRO,
                        'is_active': True,
                        'stripe_customer_id': data_object['customer'],
                    }
                )
                
                subscription_checkout.is_completed = True
                subscription_checkout.subscription = subscription
                subscription_checkout.save()
                
                logger.info('Subscription payment succeeded for user_id %s', subscription_checkout.user.id)
                
            elif perscene_checkout:
                # Handle per-scene credit purchase
                try:
                    perscene_checkout.is_completed = True
                    perscene_checkout.stripe_payment_intent_id = data_object.get('payment_intent', '')
                    perscene_checkout.save()
                    
                    # Add credits to user's account
                    perscene_checkout.fulfill_purchase()
                    
                    logger.info(f'Per-scene checkout completed for user {perscene_checkout.user.id}: {perscene_checkout.credits_amount} credits')
                    
                except Exception as e:
                    logger.error(f'Error fulfilling per-scene checkout for session {session_id}: {str(e)}')
            
            else:
                logger.error(f'No checkout record found for session {session_id}')

        elif event_type == 'customer.subscription.created':
            # Get full subscription details
            subscription = stripe.Subscription.retrieve(data_object['id'])
            
            try:
                # Try to find by customer ID
                user_sub = models.UserSubscription.objects.get(
                    stripe_customer_id=subscription.customer
                )
            except models.UserSubscription.DoesNotExist:
                # If not found, try to find through checkout records
                try:
                    checkout_record = models.CheckoutSessionRecord.objects.filter(
                        is_completed=True
                    ).order_by('-created_at').first()
                    
                    if not checkout_record:
                        logger.error('Cannot associate subscription %s with any user', subscription.id)
                        return
                        
                    # Create new subscription record
                    user_sub = models.UserSubscription.objects.create(
                        user=checkout_record.user,
                        tier=models.SubscriptionTier.PRO,
                        is_active=True,
                        stripe_customer_id=subscription.customer
                    )
                    logger.info('Created new subscription for user_id %s', checkout_record.user.id)
                except Exception as e:
                    logger.error('Failed to create subscription record: %s', str(e))
                    return
            
            # Update with data from subscription object
            user_sub.stripe_subscription_id = subscription.id
            user_sub.valid_until = datetime.fromtimestamp(subscription.current_period_end, timezone.utc)
            user_sub.is_active = subscription.status == 'active'
            user_sub.save()
            
            logger.info('Subscription created for user_id %s', user_sub.user.id)

        elif event_type == 'customer.subscription.updated':
            # Get full subscription details
            subscription = stripe.Subscription.retrieve(data_object['id'])
            
            try:
                # Try to find by subscription ID
                user_sub = models.UserSubscription.objects.get(
                    stripe_subscription_id=subscription.id
                )
            except models.UserSubscription.DoesNotExist:
                # Try by customer ID as fallback
                try:
                    user_sub = models.UserSubscription.objects.get(
                        stripe_customer_id=subscription.customer
                    )
                    # Set the subscription ID since it was missing
                    user_sub.stripe_subscription_id = subscription.id
                except models.UserSubscription.DoesNotExist:
                    logger.error('No subscription record found for subscription %s', subscription.id)
                    return
            
            # Update with data from subscription object
            user_sub.valid_until = datetime.fromtimestamp(subscription.current_period_end, timezone.utc)
            user_sub.is_active = subscription.status == 'active'
            user_sub.save()
            
            logger.info('Subscription updated for user_id %s, status: %s', 
                      user_sub.user.id, subscription.status)

        elif event_type == 'customer.subscription.deleted':
            # Get full subscription details
            subscription = stripe.Subscription.retrieve(data_object['id'])
            
            try:
                # Try to find by subscription ID
                user_sub = models.UserSubscription.objects.get(
                    stripe_subscription_id=subscription.id
                )
            except models.UserSubscription.DoesNotExist:
                # Try by customer ID as fallback
                try:
                    user_sub = models.UserSubscription.objects.get(
                        stripe_customer_id=subscription.customer
                    )
                    # Set the subscription ID since it was missing
                    user_sub.stripe_subscription_id = subscription.id
                except models.UserSubscription.DoesNotExist:
                    logger.error('No subscription record found for subscription %s', subscription.id)
                    return
            
            # Mark subscription as inactive
            user_sub.is_active = False
            
            logger.error(subscription)
            # Update end date if cancellation happened
            user_sub.valid_until = datetime.fromtimestamp(subscription.canceled_at, timezone.utc)

            
            user_sub.save()
            
            logger.info('Subscription canceled for user_id %s', user_sub.user.id)
            
        else:
            logger.info('Webhook event %s not handled', event_type)

    except Exception as e:
        logger.error('Error processing webhook %s: %s', event_type, str(e), exc_info=True)

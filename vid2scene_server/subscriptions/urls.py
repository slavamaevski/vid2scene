from django.urls import path
from . import views

urlpatterns = [
    path('subscribe/', views.subscribe, name='subscribe'),
    path('success/', views.success, name='success'),
    path('create-checkout-session/', views.create_checkout_session, name='create-checkout-session'),
    path('direct-to-customer-portal/', views.direct_to_customer_portal, name='direct-to-customer-portal'),
    path('create-credits-purchase-checkout-session/', views.create_credits_purchase_checkout_session, name='create-credits-purchase-checkout-session'),
    path('collect-stripe-webhook/', views.collect_stripe_webhook, name='collect-stripe-webhook'),
]
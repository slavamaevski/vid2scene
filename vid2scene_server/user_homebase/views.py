from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from video_processor.models import SceneProcessingJob
import logging
from django.http import Http404
from django.db.models import Q
from .models import UserAPIKey
from .forms import APIKeyGenerationForm
from subscriptions.utils import get_subscription_tier_string, is_enterprise_user
import datetime
import zoneinfo
# from silk.profiling.profiler import silk_profile

logger = logging.getLogger(__name__)

@login_required
def profile(request):
    logger.info(f"Profile view accessed by user")
    
    # Check for successful credit purchase
    session_id = request.GET.get('session_id')
    if session_id:
        # Verify this was a successful credit purchase
        from subscriptions.models import PerSceneCheckoutSessionRecord
        try:
            checkout = PerSceneCheckoutSessionRecord.objects.get(
                stripe_checkout_session_id=session_id,
                user=request.user,
                is_completed=True
            )
            messages.success(
                request, 
                f'Credits purchased successfully! {checkout.credits_amount} credits have been added to your account.'
            )
        except PerSceneCheckoutSessionRecord.DoesNotExist:
            # Could be a subscription or failed purchase, just ignore
            pass
        
        # Redirect to clean URL (remove session_id parameter)
        return redirect('profile')
    
    # Get user's API keys (only if enterprise user)
    can_use_api_keys = request.user.is_superuser or get_subscription_tier_string(request.user).startswith('enterprise')
    api_keys = UserAPIKey.objects.filter(user=request.user, revoked=False).order_by('-created_at') if can_use_api_keys else []
    form = APIKeyGenerationForm(request.user) if can_use_api_keys else None
    
    return render(request, "user_homebase/profile.html", {
        'api_keys': api_keys,
        'form': form,
        'subscription_tier': get_subscription_tier_string(request.user),
        'can_use_api_keys': can_use_api_keys,
    })

@login_required
def generate_api_key(request):
    """Generate a new API key for the user via AJAX."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    is_enterprise = get_subscription_tier_string(request.user).startswith('enterprise')
    # Check if user is enterprise - API keys are only for enterprise users
    if not request.user.is_superuser and not is_enterprise:
        return JsonResponse({'error': 'API keys are only available for Enterprise users'}, status=403)
    
    try:
        form = APIKeyGenerationForm(request.user, request.POST)
        if form.is_valid():
            # Generate the API key
            api_key, key = UserAPIKey.objects.create_key(
                name=form.cleaned_data['name'],
                user=request.user
            )
            
            logger.info(f"Generated API key '{form.cleaned_data['name']}' for user {request.user.username}")
            
            return JsonResponse({
                'success': True,
                'api_key': key,
                'prefix': api_key.prefix,
                'name': api_key.name,
                'created_at': api_key.created_at.isoformat()
            })
        else:
            return JsonResponse({
                'error': form.errors.get('name', ['Invalid form data'])[0]
            }, status=400)
        
    except Exception as e:
        logger.error(f"Error generating API key for user {request.user.username}: {e}")
        return JsonResponse({'error': 'Failed to generate API key'}, status=500)

@login_required
def revoke_api_key(request):
    """Revoke an API key."""
    if request.method != 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Invalid request method'}, status=405)
        messages.error(request, 'Invalid request method')
        return redirect('profile')
    is_enterprise = get_subscription_tier_string(request.user).startswith('enterprise')
    # Check if user is enterprise - API keys are only for enterprise users
    if not request.user.is_superuser and not is_enterprise:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'API keys are only available for Enterprise users'}, status=403)
        messages.error(request, 'API keys are only available for Enterprise users')
        return redirect('profile')
    
    try:
        key_id = request.POST.get('key_id')
        if not key_id:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Key ID is required'}, status=400)
            messages.error(request, 'Key ID is required')
            return redirect('profile')
        
        # Get the API key and verify ownership
        try:
            api_key = UserAPIKey.objects.get(id=key_id, user=request.user)
        except UserAPIKey.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'API key not found'}, status=404)
            messages.error(request, 'API key not found')
            return redirect('profile')
        
        # Revoke the key
        api_key.revoked = True
        api_key.save()
        
        logger.info(f"Revoked API key '{api_key.name}' for user {request.user.username}")
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': f"API key '{api_key.name}' has been revoked successfully"})
        
        messages.success(request, f"API key '{api_key.name}' has been revoked successfully")
        return redirect('profile')
        
    except Exception as e:
        logger.error(f"Error revoking API key for user {request.user.username}: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Failed to revoke API key. Please try again.'}, status=500)
        messages.error(request, 'Failed to revoke API key. Please try again.')
        return redirect('profile')

# @silk_profile(name='job_status')
@login_required
def job_status(request):
    logger.info(f"Job status view accessed by user")
    if request.user.is_superuser:
        jobs = SceneProcessingJob.objects.all()
        jobs = jobs.order_by('-uploaded_at')[:40]
        logger.info("User is superuser, retrieved last 40 jobs.")
        
        pacific_tz = zoneinfo.ZoneInfo('US/Pacific')
        now_pacific = datetime.datetime.now(pacific_tz)

        # Get start of current day in Pacific time
        start_of_day_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)

        # convert to UTC
        start_of_day_utc = start_of_day_pacific.astimezone(tz=datetime.timezone.utc)
        
        # Count completed jobs (with ply_file) from non-superusers for the current day
        daily_completed_jobs = SceneProcessingJob.objects.filter(
            uploaded_at__gte=start_of_day_utc
        ).exclude(
            ply_file__in=['', None]
        ).filter(
            Q(user__is_superuser=False) | Q(user__isnull=True)
        ).count()
        
        context = {
            "jobs": jobs,
            "daily_completed_jobs": daily_completed_jobs
        }
    else:
        jobs = SceneProcessingJob.objects.filter(user=request.user)
        jobs = jobs.order_by('-uploaded_at')
        logger.info("Retrieved jobs for the current user.")
        context = {
            "jobs": jobs
        }
    
    return render(request, "user_homebase/jobs_status.html", context)

# @silk_profile(name='landing_page')
def landing_page(request):
    from datetime import datetime
    current_year = datetime.now().year
    return render(request, "landing.html", {"current_year": current_year})

def privacy_policy(request):
    return render(request, "privacy.html")

def terms_of_service(request):
    return render(request, "terms.html")

def disable_tracking(request):
    if not request.user.is_superuser:
        raise Http404("Page not found")
    return render(request, 'user_homebase/disable_tracking.html')

def responsible_ai(request):
    return render(request, "responsible_ai.html")

import logging
import django_rq
from .models import SceneProcessingJob
from subscriptions.utils import user_can_generate_premium_scene
from subscriptions.models import SubscriptionTier, CreditTransaction

logger = logging.getLogger(__name__)


def find_rq_job_with_queue_name(rq_job_id):
    """Search RQ queues for a job and return (job, queue_name) or (None, None)."""
    if rq_job_id is None:
        return None, None
    for queue_name in ["default", "high", "enterprise", "internal"]:
        queue = django_rq.get_queue(queue_name)
        job = queue.fetch_job(rq_job_id)
        if job:
            return job, queue_name
    return None, None


def validate_user_settings(user, training_max_num_gaussians=None, training_num_steps=None, reconstruction_method=None, 
                          apriltag_size_mm=None, is_api_call=False, user_subscription_tier=None):
    """
    Validate user settings against plan limits.
    
    Args:
        user: Django User object
        user_subscription_tier: String tier ("free", "pro", "enterprise", "enterprise_perscene")
        
    Returns:
        dict(valid, errors, adjusted_values)
    """
    errors = []
    adjusted_values = {}
    
    # Get subscription tier if not provided
    if user_subscription_tier is None:
        from subscriptions.utils import get_subscription_tier_string
        user_subscription_tier = get_subscription_tier_string(user)
    
    # Determine access levels
    user_has_premium_access = user_subscription_tier in ["pro", "enterprise", "enterprise_perscene"]
    user_is_enterprise = user_subscription_tier in ["enterprise", "enterprise_perscene"]
    
    # Determine tier-specific limits
    user_max_gaussians = SceneProcessingJob.MAX_NUM_GAUSSIANS if user_has_premium_access else SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE
    user_max_steps = SceneProcessingJob.MAX_NUM_STEPS if user_has_premium_access else SceneProcessingJob.MAX_NUM_STEPS_FREE

    if training_max_num_gaussians is not None:
        if training_max_num_gaussians < SceneProcessingJob.MIN_NUM_GAUSSIANS:
            errors.append(f"Number of gaussians must be at least {SceneProcessingJob.MIN_NUM_GAUSSIANS:,}")
        elif training_max_num_gaussians > user_max_gaussians:
            adjusted_values['training_max_num_gaussians'] = user_max_gaussians
            if user_has_premium_access:
                errors.append(f"Number of gaussians cannot exceed {SceneProcessingJob.MAX_NUM_GAUSSIANS:,}")
            else:
                errors.append(
                    f"You are limited to {SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE:,} gaussians. "
                    f"Upgrade to Pro or Enterprise for up to {SceneProcessingJob.MAX_NUM_GAUSSIANS:,} gaussians."
                )

    if training_num_steps is not None:
        if training_num_steps < SceneProcessingJob.MIN_NUM_STEPS:
            errors.append(f"Number of training steps must be at least {SceneProcessingJob.MIN_NUM_STEPS:,}")
        elif training_num_steps > user_max_steps:
            adjusted_values['training_num_steps'] = user_max_steps
            if user_has_premium_access:
                errors.append(f"Number of training steps cannot exceed {SceneProcessingJob.MAX_NUM_STEPS:,}")
            else:
                errors.append(
                    f"You are limited to {SceneProcessingJob.MAX_NUM_STEPS_FREE:,} training steps. "
                    f"Upgrade to Pro or Enterprise for up to {SceneProcessingJob.MAX_NUM_STEPS:,} steps."
                )

    if reconstruction_method is not None:
        # Allow GLOMAP and QUEST for all users, other methods require premium
        allowed_free_methods = [
            SceneProcessingJob.ReconstructionMethod.GLOMAP,
            SceneProcessingJob.ReconstructionMethod.QUEST
        ]
        if reconstruction_method not in allowed_free_methods and not user_has_premium_access:
            adjusted_values['reconstruction_method'] = SceneProcessingJob.ReconstructionMethod.GLOMAP
            errors.append(
                "Advanced reconstruction methods are premium features. "
                "Upgrade to Pro or Enterprise to access additional reconstruction methods."
            )
    
    # Validate AprilTag calibration (Enterprise only)
    if apriltag_size_mm is not None:
        if not user_is_enterprise:
            adjusted_values['apriltag_size_mm'] = None
            errors.append(
                "AprilTag scale calibration is an Enterprise-only feature. "
                "Upgrade to Enterprise to access AprilTag calibration."
            )
        elif apriltag_size_mm < 1.0 or apriltag_size_mm > 1000.0:
            errors.append("AprilTag size must be between 1mm and 1000mm.")

    return {"valid": len(errors) == 0, "errors": errors, "adjusted_values": adjusted_values}


def user_can_access_spj(request, spj: SceneProcessingJob, viewer_only: bool):
    user_based_access = request.user.is_superuser or (request.user == spj.user)
    if not spj.user or spj.user.username == "None":
        return True
    if viewer_only:
        public_access = spj.public or spj.example
        logger.info(f"View-only user access check for SPJ ID {spj.id}: {user_based_access or public_access}")
        return user_based_access or public_access
    logger.info(f"User access check for SPJ ID {spj.id}: {user_based_access}")
    return user_based_access


def get_status_string(spj: SceneProcessingJob, job):
    status = job.get_status() if job else "Not found"
    if spj.ply_file or spj.spz_file or spj.sog_file or spj.lod_file:
        return "Finished"
    if status == "failed":
        return "Failed"
    if spj.preview_image:
        return "Generating 3D scene"
    if status == "queued" and job:
        job_position = job.get_position()
        if job_position is not None:
            position = job_position + 1
            return f"Queued - position: {position}"
        else:
            return "Queued"
    if status == "started":
        return "Processing video"
    return status


def get_percent_complete(spj: SceneProcessingJob):
    spj_preview_image_name = (spj.preview_image.name or '').split('/')[-1]
    import re
    name_regex = r'^(?P<spj_id>[^_]+)_(?P<step_number>\d+)_(?P<preview_number>\d+)\.\w+$'
    match = re.match(name_regex, spj_preview_image_name)
    if match:
        step_number = int(match.group('step_number'))
        percent_complete = (step_number / spj.training_num_steps) * 100
        return min(percent_complete, 100)
    return None


def get_client_ip_ratelimit_key(group, request):
    if not group:
        group = "default"
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
        ip = ip.split(':')[0]
        key = group + ip
        return key
    ip = request.META.get('REMOTE_ADDR')
    key = group + ip
    return key


def should_refund_credit_for_job(spj):
    """
    Determine if a credit should be refunded for a deleted job.
    
    Args:
        spj: SceneProcessingJob instance
        
    Returns:
        bool: True if credit should be refunded, False otherwise
        
    Logic:
        1. Must be an enterprise per-scene user
        2. Must have been a premium job (had a consumption transaction)
        3. Must not have already been refunded
        4. Job must be unfinished (no ply_file)
    """
    # Must be enterprise per-scene user
    if not (spj.user and hasattr(spj.user, 'subscription') and 
            spj.user.subscription.tier == SubscriptionTier.ENTERPRISE_PERSCENE):
        return False
    
    # Job must be unfinished (no ply_file means not completed)
    if spj.ply_file:
        return False
    
    # Check if this was a premium job by looking for consumption transactions
    consumption_transactions = CreditTransaction.objects.filter(
        user=spj.user,
        scene_processing_job=spj,
        transaction_type=CreditTransaction.TransactionType.CONSUMPTION,
        status=CreditTransaction.TransactionStatus.FULFILLED
    )
    
    # If no consumption transaction exists, this wasn't a premium job
    if not consumption_transactions.exists():
        return False
    
    # Check if a refund has already been issued for this job
    existing_refunds = CreditTransaction.objects.filter(
        user=spj.user,
        scene_processing_job=spj,
        transaction_type=CreditTransaction.TransactionType.REFUND,
        status=CreditTransaction.TransactionStatus.FULFILLED
    )
    
    # Don't refund if already refunded
    if existing_refunds.exists():
        return False
    
    return True

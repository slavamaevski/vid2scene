import logging
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from anymail.message import AnymailMessage
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

def can_send_email_to_user(user, job_id):
    """
    Check if we can send an email to the user.
    
    Args:
        user: User instance
        job_id: Job ID for logging purposes
    
    Returns:
        bool: True if email can be sent, False otherwise
    """
    # Check if user is authenticated
    if not user or isinstance(user, AnonymousUser):
        logger.info(f"Job {job_id}: No authenticated user, skipping email notification")
        return False
    
    # Check if user has email and is active
    if not user.email or not user.is_active:
        logger.info(f"Job {job_id}: User {user.username} has no email or is inactive, skipping email notification")
        return False
    
    # Check if email is verified (for allauth users)
    if hasattr(user, 'emailaddress_set'):
        email_address = user.emailaddress_set.filter(primary=True).first()
        if email_address and not email_address.verified:
            logger.info(f"Job {job_id}: User {user.username} email not verified, skipping email notification")
            return False
    
    return True


def send_job_completion_email(scene_processing_job, delay_seconds=None):
    """
    Send an email notification when a job completes successfully using SendGrid templates.
   
    Args:
        scene_processing_job: SceneProcessingJob instance
        delay_seconds: Optional delay in seconds before sending the email (default: None for immediate sending)
    """
    user = scene_processing_job.user
    # Check if we can send email to the user
    if not can_send_email_to_user(user, scene_processing_job.id):
        logger.info(f"Job {scene_processing_job.id}: User {user.username} has no email or is inactive, skipping email notification")
        return
   
    try:
        # Build the dynamic template data
        template_data = {
            'user_name': user.first_name or user.username,
            'job_title': scene_processing_job.title,
            'job_id': str(scene_processing_job.id),
            'view_url': f"{settings.SITE_URL}{reverse('splat_viewer_spj_id', kwargs={'spj_id': scene_processing_job.id})}",
            'status_url': f"{settings.SITE_URL}{reverse('check_status', kwargs={'spj_id': scene_processing_job.id})}",
            'uploaded_at': scene_processing_job.uploaded_at.strftime('%B %d, %Y at %I:%M %p %Z') if scene_processing_job.uploaded_at else 'Unknown',
        }
       
        message = AnymailMessage(
            # When using templates, subject can be omitted or will be overridden by template
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
       
        # Set SendGrid template ID (supported directly by Anymail)
        message.template_id = settings.SENDGRID_JOB_COMPLETION_TEMPLATE_ID
       
        # Set merge data for the template
        message.merge_global_data = {key: str(value) if value is not None else '' for key, value in template_data.items()}

        # Set unsubscribe group for proper unsubscribe links
        message.esp_extra = {
            "asm": {
                "group_id": settings.SENDGRID_JOB_STATUS_UNSUBSCRIBE_GROUP_ID
            }
        }
        
        # Set send_at time if delay is specified
        if delay_seconds:
            send_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            message.send_at = send_at
            logger.info(f"Job completion email scheduled for {send_at} (in {delay_seconds} seconds) for job {scene_processing_job.id}")
        else:
            logger.info(f"Job completion email sent immediately for job {scene_processing_job.id}")
       
        # Send the email
        message.send()
       
    except Exception as e:
        logger.error(f"Failed to send job completion email for job {scene_processing_job.id}: {e}")


def send_job_failure_email(scene_processing_job, error_message):
    """
    Send an email notification when a job fails using SendGrid templates.
   
    Args:
        scene_processing_job: SceneProcessingJob instance
        error_message: The error message to include in the email
    """
    user = scene_processing_job.user
    # Check if we can send email to the user
    if not can_send_email_to_user(user, scene_processing_job.id):
        return
   
    try:
        # Build the dynamic template data
        template_data = {
            'user_name': user.first_name or user.username,
            'job_title': scene_processing_job.title,
            'job_id': str(scene_processing_job.id),
            'error_message': error_message,
            'uploaded_at': scene_processing_job.uploaded_at.strftime('%B %d, %Y at %I:%M %p %Z') if scene_processing_job.uploaded_at else 'Unknown',
        }
       
        message = AnymailMessage(
            # Subject can be omitted when using templates, or will be overridden by template
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
       
        # Set SendGrid template ID
        message.template_id = settings.SENDGRID_JOB_FAILURE_TEMPLATE_ID
       
        # Set merge data for the template
        message.merge_global_data = {key: str(value) if value is not None else '' for key, value in template_data.items()}

                # Set unsubscribe group for proper unsubscribe links
        message.esp_extra = {
            "asm": {
                "group_id": settings.SENDGRID_JOB_STATUS_UNSUBSCRIBE_GROUP_ID
            }
        }
       
        # Send the email
        message.send()
       
        logger.info(f"Job failure email sent for job {scene_processing_job.id}")
       
    except Exception as e:
        logger.error(f"Failed to send job failure email for job {scene_processing_job.id}: {e}")
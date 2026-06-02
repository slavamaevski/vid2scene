from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.utils import timezone
import logging

import waffle

from .utils import find_rq_job_with_queue_name, get_client_ip_ratelimit_key, user_can_access_spj, get_status_string, get_percent_complete
from .job_creation import create_upload_sas_url, create_processing_job
from .permissions import NoAPIKeyAllowed
from django_ratelimit.decorators import ratelimit
from .models import SceneProcessingJob
from subscriptions.models import CreditTransaction, SubscriptionTier, RefundRequest

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([NoAPIKeyAllowed])
@ratelimit(key=get_client_ip_ratelimit_key, rate='6/h')
def generate_upload_sas(request):
    try:
        file_extension = request.data.get('file_extension')
        result = create_upload_sas_url(file_extension)
        return Response(result, status=200)
    except Exception:
        return Response({'error': 'Failed to generate SAS URL.'}, status=500)


@api_view(['POST'])
@permission_classes([NoAPIKeyAllowed])
@ratelimit(key=get_client_ip_ratelimit_key, rate='6/h')
def submit_video(request):
    try:
        # Extract parameters
        title = request.data.get('title')
        public = request.data.get('public', False)
        blob_name = request.data.get('blob_name')
        allow_as_example = request.data.get('allow_as_example', False)
        remove_background = request.data.get('remove_background') if waffle.flag_is_active(request, 'enable_remove_background') else False
        remove_background = remove_background or False
        equirectangular = request.data.get('equirectangular', False)
        use_background_sphere = request.data.get('use_background_sphere', False)
        reconstruction_method = request.data.get('reconstruction_method', SceneProcessingJob.ReconstructionMethod.GLOMAP)
        
        training_max_num_gaussians = int(request.data.get('training_max_num_gaussians', None)) if request.data.get('training_max_num_gaussians', None) is not None else None
        training_num_steps = int(request.data.get('training_num_steps', None)) if request.data.get('training_num_steps', None) is not None else None
        
        # Handle pilgram filter
        pilgram_filter = None
        if waffle.flag_is_active(request, 'enable_pilgram_filters'):
            pilgram_filter = request.data.get('pilgram_filter')
            valid_filter_values = [value for value, _ in SceneProcessingJob.PILGRAM_FILTER_CHOICES if value is not None]
            if pilgram_filter is not None and pilgram_filter not in valid_filter_values:
                pilgram_filter = None
        
        # Handle AprilTag calibration (Enterprise only)
        apriltag_size_mm = request.data.get('apriltag_size_mm')
        if apriltag_size_mm:
            apriltag_size_mm = float(apriltag_size_mm)
        else:
            apriltag_size_mm = None
        
        # Use shared helper function
        result = create_processing_job(
            user=request.user,
            title=title,
            blob_name=blob_name,
            public=public,
            allow_as_example=allow_as_example,
            reconstruction_method=reconstruction_method,
            training_max_num_gaussians=training_max_num_gaussians,
            training_num_steps=training_num_steps,
            remove_background=remove_background,
            equirectangular=equirectangular,
            use_background_sphere=use_background_sphere,
            pilgram_filter=pilgram_filter,
            apriltag_size_mm=apriltag_size_mm,
            is_api_call=False,
        )
        
        spj = result['spj']
        redirect_url = reverse("check_status", kwargs={'spj_id': spj.id})
        
        return Response({'success': True, 'redirect_url': redirect_url}, status=200)
        
    except ValueError as e:
        logger.exception(f"Error in submit_video: {e}")
        return Response({'success': False, 'error_message': str(e)}, status=400)
    except Exception as e:
        logger.exception(f"Error in submit_video: {e}")
        return Response({'success': False, 'error_message': 'An error occurred while processing the request.'}, status=500)


@api_view(['GET'])
@permission_classes([NoAPIKeyAllowed])
def api_job_status(request, job_id):
    try:
        spj = SceneProcessingJob.objects.get(id=job_id)
        if not user_can_access_spj(request, spj, viewer_only=True):
            return Response({'error': 'Job not found'}, status=404)
        job, _ = find_rq_job_with_queue_name(spj.rq_job_id)
        status_str = get_status_string(spj, job)
        percent_complete = get_percent_complete(spj) if spj.preview_image else None
        if status_str == "Finished":
            percent_complete = 100
        return Response({
            'job_id': str(spj.id),
            'title': spj.title,
            'status': status_str,
            'percent_complete': percent_complete,
            'uploaded_at': spj.uploaded_at.isoformat(),
            'public': spj.public,
            'reconstruction_method': spj.reconstruction_method,
            'training_max_num_gaussians': spj.training_max_num_gaussians,
            'training_num_steps': spj.training_num_steps,
        })
    except SceneProcessingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=404)


@api_view(['GET'])
@permission_classes([NoAPIKeyAllowed])
def api_job_download_urls(request, job_id):
    try:
        spj = SceneProcessingJob.objects.get(id=job_id)
        if not user_can_access_spj(request, spj, viewer_only=True):
            return Response({'error': 'Job not found'}, status=404)
        urls = {}
        if spj.ply_file:
            urls['ply'] = f"https://{get_current_site(request)}{reverse('download_ply', kwargs={'spj_id': spj.id})}"
        if spj.spz_file:
            urls['spz'] = f"https://{get_current_site(request)}{reverse('download_spz', kwargs={'spj_id': spj.id})}"
        return Response({
            'job_id': str(spj.id),
            'title': spj.title,
            'download_urls': urls,
            'has_ply': bool(spj.ply_file),
            'has_spz': bool(spj.spz_file),
        })
    except SceneProcessingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=404)


@api_view(['GET'])
@permission_classes([NoAPIKeyAllowed])
def api_job_viewer_url(request, job_id):
    try:
        spj = SceneProcessingJob.objects.get(id=job_id)
        if not user_can_access_spj(request, spj, viewer_only=True):
            return Response({'error': 'Job not found'}, status=404)
        if not spj.ply_file:
            return Response({'error': 'Job not completed yet'}, status=400)
        viewer_url = f"https://{get_current_site(request)}{reverse('splat_viewer_spj_id', kwargs={'spj_id': spj.id})}"
        return Response({'job_id': str(spj.id), 'title': spj.title, 'viewer_url': viewer_url})
    except SceneProcessingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=404)


@api_view(['GET'])
@permission_classes([NoAPIKeyAllowed])
def api_job_preview_url(request, job_id):
    try:
        spj = SceneProcessingJob.objects.get(id=job_id)
        if not user_can_access_spj(request, spj, viewer_only=True):
            return Response({'error': 'Job not found'}, status=404)
        if not spj.preview_image:
            return Response({'error': 'No preview available yet'}, status=400)
        preview_url = f"https://{get_current_site(request)}{reverse('preview_image', kwargs={'spj_id': spj.id})}"
        return Response({'job_id': str(spj.id), 'title': spj.title, 'preview_url': preview_url})
    except SceneProcessingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=404)


@require_http_methods(["POST"])
def request_refund(request, job_id):
    """Handle credit refund requests for enterprise per-scene users"""
    try:
        spj = SceneProcessingJob.objects.get(id=job_id)
        
        # Security checks - authentication first, then authorization
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
            
        if not user_can_access_spj(request, spj, viewer_only=False):
            return JsonResponse({'error': 'Access denied'}, status=403)
            
        if not (hasattr(request.user, 'subscription') and 
                request.user.subscription.tier == SubscriptionTier.ENTERPRISE_PERSCENE):
            return JsonResponse({'error': 'Not eligible for refunds'}, status=400)
            
        # Check for existing refund requests
        existing_refund = RefundRequest.objects.filter(
            scene_processing_job=spj,
            status__in=[RefundRequest.RefundStatus.REQUESTED, RefundRequest.RefundStatus.APPROVED]
        ).first()
        
        if existing_refund:
            return JsonResponse({'error': 'Refund already requested or approved'}, status=400)
            
        # Get current job status
        job, _ = find_rq_job_with_queue_name(spj.rq_job_id)
        status = get_status_string(spj, job)
        
        # Extract refund details
        reason = request.POST.get('reason', '')
        notes = request.POST.get('notes', '')
        
        # AUTO-APPROVAL LOGIC: Technical failures get immediate refund
        if status == "Failed":
            # Create refund request with auto-approval
            refund_request = RefundRequest.create_request(
                user=request.user,
                scene_job=spj,
                reason=RefundRequest.RefundReason.TECHNICAL_FAILURE,
                customer_notes=notes,
                auto_approve_technical=True
            )
            
            logger.info(f"Auto-approved refund for failed job {job_id}")
            
            return JsonResponse({
                'success': True, 
                'message': 'Credit refunded immediately (technical failure)',
                'auto_approved': True
            })
            
        # MANUAL REVIEW: Quality issues for completed jobs
        elif status == "Finished":
            refund_request = RefundRequest.create_request(
                user=request.user,
                scene_job=spj,
                reason=RefundRequest.RefundReason.QUALITY_UNSATISFIED,
                customer_notes=notes,
                auto_approve_technical=False
            )
            
            logger.info(f"Quality refund requested for completed job {job_id}")
            
            # TODO: Send notification to admin for review
            
            return JsonResponse({
                'success': True,
                'message': 'Refund request submitted for review. We\'ll respond within 24 hours.',
                'auto_approved': False
            })
            
        else:
            return JsonResponse({'error': f'Cannot request refund for job with status: {status}'}, status=400)
            
    except SceneProcessingJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)
    except Exception as e:
        logger.error(f"Error processing refund request for job {job_id}: {e}")
        return JsonResponse({'error': 'Internal error'}, status=500)


@api_view(['POST'])
@permission_classes([NoAPIKeyAllowed])
@ratelimit(key=get_client_ip_ratelimit_key, rate='6/h')
def submit_quest(request):
    """Submit a Quest project zip file for processing."""
    try:
        # Extract parameters
        title = request.data.get('title')
        public = request.data.get('public', False)
        blob_name = request.data.get('blob_name')
        allow_as_example = request.data.get('allow_as_example', False)
        
        training_max_num_gaussians = int(request.data.get('training_max_num_gaussians', None)) if request.data.get('training_max_num_gaussians', None) is not None else None
        training_num_steps = int(request.data.get('training_num_steps', None)) if request.data.get('training_num_steps', None) is not None else None
        
        # Force reconstruction method to QUEST
        reconstruction_method = SceneProcessingJob.ReconstructionMethod.QUEST
        logger.info(f"Reconstruction method: {reconstruction_method}")
        
        # Use shared helper function
        result = create_processing_job(
            user=request.user,
            title=title,
            blob_name=blob_name,
            public=public,
            allow_as_example=allow_as_example,
            reconstruction_method=reconstruction_method,
            training_max_num_gaussians=training_max_num_gaussians,
            training_num_steps=training_num_steps,
            remove_background=False,
            equirectangular=False,
            use_background_sphere=False,
            pilgram_filter=None,
            apriltag_size_mm=None,
            is_api_call=False,
        )
        
        spj = result['spj']
        redirect_url = reverse("check_status", kwargs={'spj_id': spj.id})
        
        return Response({'success': True, 'redirect_url': redirect_url}, status=200)
        
    except ValueError as e:
        logger.exception(f"Error in submit_quest: {e}")
        return Response({'success': False, 'error_message': str(e)}, status=400)
    except Exception as e:
        logger.exception(f"Error in submit_quest: {e}")
        return Response({'success': False, 'error_message': 'An error occurred while processing the request.'}, status=500)


@api_view(['POST'])
@permission_classes([NoAPIKeyAllowed])
@ratelimit(key=get_client_ip_ratelimit_key, rate='6/h')
def submit_generate_lod(request):
    """Submit a raw PLY file for LOD generation."""
    try:
        # Extract parameters
        title = request.data.get('title')
        public = request.data.get('public', False)
        blob_name = request.data.get('blob_name')
        allow_as_example = request.data.get('allow_as_example', False)
        
        # Force reconstruction method to GENERATE_LOD
        reconstruction_method = SceneProcessingJob.ReconstructionMethod.GENERATE_LOD
        logger.info(f"Reconstruction method: {reconstruction_method}")
        
        # Use shared helper function
        result = create_processing_job(
            user=request.user,
            title=title,
            blob_name=blob_name,
            public=public,
            allow_as_example=allow_as_example,
            reconstruction_method=reconstruction_method,
            training_max_num_gaussians=None,
            training_num_steps=None,
            remove_background=False,
            equirectangular=False,
            use_background_sphere=False,
            pilgram_filter=None,
            apriltag_size_mm=None,
            is_api_call=False,
        )
        
        spj = result['spj']
        redirect_url = reverse("check_status", kwargs={'spj_id': spj.id})
        
        return Response({'success': True, 'redirect_url': redirect_url}, status=200)
        
    except ValueError as e:
        return Response({'success': False, 'error_message': str(e)}, status=400)
    except Exception as e:
        logger.exception(f"Error in submit_generate_lod: {e}")
        return Response({'success': False, 'error_message': 'An error occurred while processing the request.'}, status=500)

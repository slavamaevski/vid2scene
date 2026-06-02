import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import generics
import logging
 
from django.conf import settings
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from django.shortcuts import redirect

from .models import SceneProcessingJob
from .serializers import JobDetailSerializer, JobListSerializer
from .permissions import APIKeyEnterpriseOnly
from subscriptions.models import SubscriptionTier, CreditTransaction
from .utils import find_rq_job_with_queue_name, should_refund_credit_for_job
from .job_creation import create_upload_sas_url, create_processing_job
import traceback
# from silk.profiling.profiler import silk_profile

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([APIKeyEnterpriseOnly])
def generate_upload_url(request):
    """Generate upload URL for dev API (without rate limits)."""
    try:
        file_extension = request.data.get('file_extension')
        result = create_upload_sas_url(file_extension)
        url = result['sas_url']
        blob_name = result['blob_name']
        api_result = {
            'url': url,
            'blob_name': blob_name,
        }
        return Response(api_result, status=200)
    except Exception:
        return Response({'error': 'Failed to generate upload URL.'}, status=500)


@api_view(['POST'])
@permission_classes([APIKeyEnterpriseOnly])
def submit_job(request):
    """
    Create and start a video processing job.
    Returns job details instead of redirect URL for API consumers.
    """
    
    try:
        # Extract parameters
        title = request.data.get('title')
        public = request.data.get('public', False)
        blob_name = request.data.get('blob_name')
        allow_as_example = request.data.get('allow_as_example', False)
        reconstruction_method = request.data.get('reconstruction_method', SceneProcessingJob.ReconstructionMethod.GLOMAP)
        remove_background = request.data.get('remove_background', False)
        
        training_max_num_gaussians = request.data.get('training_max_num_gaussians')
        training_num_steps = request.data.get('training_num_steps')
        
        if training_max_num_gaussians is not None:
            training_max_num_gaussians = int(training_max_num_gaussians)
        if training_num_steps is not None:
            training_num_steps = int(training_num_steps)
        
        # Handle AprilTag calibration (Enterprise only)
        apriltag_size_mm = request.data.get('apriltag_size_mm')
        if apriltag_size_mm:
            apriltag_size_mm = float(apriltag_size_mm)
        else:
            apriltag_size_mm = None
        
        # Handle camera type preference
        camera_type = request.data.get('camera_type')
        if camera_type and camera_type not in ['orbital', 'drone']:
            raise ValueError(f'Invalid camera_type. Must be "orbital" or "drone".')
            
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
            apriltag_size_mm=apriltag_size_mm,
            remove_background=remove_background,
            camera_type=camera_type,
            is_api_call=True,
        )
            
        spj = result['spj']
        
        # Serialize the job and add success field
        serializer = JobDetailSerializer(spj)
        response_data = serializer.data
        response_data['success'] = True
        
        return Response(response_data, status=201)
        
    except ValueError as e:
        return Response({'success': False, 'error_message': str(e)}, status=400)
    except Exception as e:
        # print the error traceback
        logger.error(f"Error submitting job: {e}")
        logger.error(traceback.format_exc())
        return Response({'success': False, 'error_message': 'An error occurred while processing the request.'}, status=500)


class JobListAPIView(generics.ListAPIView):
    permission_classes = [APIKeyEnterpriseOnly]

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = SceneProcessingJob.objects.all()
        if self.request.user.is_superuser:
            return queryset
        # Return only user's own jobs for enterprise API
        return queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        return JobListSerializer


class JobRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [APIKeyEnterpriseOnly]
    lookup_field = 'id'
    lookup_url_kwarg = 'job_id'

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return super().delete(request, *args, **kwargs)

    def get_queryset(self):
        queryset = SceneProcessingJob.objects.all()
        if self.request.user.is_superuser:
            return queryset
        # Return only user's own jobs for enterprise API
        return queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        return JobDetailSerializer

    def destroy(self, request, *args, **kwargs):
        spj = self.get_object()
        # Only owners can delete their jobs
        if spj.user != request.user:
            return Response({'error': 'Job not found'}, status=404)

        # Check if we need to refund credits for unfinished jobs
        if should_refund_credit_for_job(spj):
            # Create refund transaction for job deletion
            CreditTransaction.create_refund_transaction(
                user=spj.user,
                scene_job=spj,
                credits_amount=1,
                user_notes="Job deleted before completion via API",
                auto_process=True
            )

        # Delete associated files (mirror web delete logic)
        if spj.video_file:
            spj.video_file.delete(save=True)
        if spj.ply_file:
            spj.ply_file.delete(save=True)

        # Remove from RQ if present
        job, _ = find_rq_job_with_queue_name(spj.rq_job_id)
        if job:
            job.delete()

        # Delete the job record
        spj.delete()
        return Response(status=204)




@api_view(['GET', 'HEAD'])
@permission_classes([APIKeyEnterpriseOnly])
def api_job_preview_image(request, job_id):
    """Redirect to a short-lived SAS URL for the preview image (offloads bandwidth)."""
    try:
        spj = SceneProcessingJob.objects.get(id=job_id)
        if spj.user != request.user:
            return Response({'error': 'Job not found'}, status=404)
        if not spj.preview_image:
            return Response({'error': 'No preview available yet'}, status=400)
        # Always redirect to short-lived SAS URL to avoid proxying bytes through app server
        blob_service_client = BlobServiceClient.from_connection_string(
            settings.STORAGES["default"]["OPTIONS"]["connection_string"]
        )
        container_name = settings.STORAGES["default"]["OPTIONS"]["azure_container"]
        blob_name = spj.preview_image.name
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.utcnow() + datetime.timedelta(minutes=5),
        )
        download_url = f"{blob_client.url}?{sas_token}"
        return redirect(download_url)
    except SceneProcessingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=404)


@api_view(['GET', 'HEAD'])
@permission_classes([APIKeyEnterpriseOnly])
def api_job_download_file(request, job_id, file_type):
    """Generate SAS URL for downloading a specific file type (ply or spz)."""
    try:
        spj = SceneProcessingJob.objects.get(id=job_id)
        if spj.user != request.user:
            return Response({'error': 'Job not found'}, status=404)
        
        # Validate file type
        if file_type not in ['ply', 'spz']:
            return Response({'error': 'Invalid file type. Must be "ply" or "spz"'}, status=400)
        
        # Get the appropriate file field
        file_field = spj.ply_file if file_type == 'ply' else spj.spz_file
        if not file_field:
            return Response({
                'error': f'{file_type.upper()} file not available for this job'
            }, status=404)
        
        # Generate SAS URL
        blob_service_client = BlobServiceClient.from_connection_string(
            settings.STORAGES["default"]["OPTIONS"]["connection_string"]
        )
        container_name = settings.STORAGES["default"]["OPTIONS"]["azure_container"]
        blob_name = file_field.name
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.utcnow() + datetime.timedelta(minutes=15),
        )
        download_url = f"{blob_client.url}?{sas_token}"
        
        return redirect(download_url)
        
    except SceneProcessingJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=404)



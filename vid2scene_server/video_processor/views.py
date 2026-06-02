import datetime
import logging
import os
import re
from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from .email_utils import send_job_completion_email

from subscriptions.utils import user_can_generate_premium_scene
from subscriptions.models import SubscriptionTier, CreditTransaction
from .forms import VideoUploadForm
from .models import SceneProcessingJob
from django.core.files.storage import default_storage
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from django.db import models
from rest_framework import generics, status
from rest_framework.response import Response

from .serializers import JobDetailSerializer
from .permissions import IsOwnerOrAdminOrAnonymousForUnowned, NoAPIKeyAllowed
import unicodedata
import urllib.parse
# from silk.profiling.profiler import silk_profile

logger = logging.getLogger(__name__)


from .utils import (
    find_rq_job_with_queue_name,
    user_can_access_spj,
    get_status_string,
    get_percent_complete,
    get_client_ip_ratelimit_key,
    should_refund_credit_for_job,
)




def reset_rq_timeout(request, spj_id):
    if not request.user.is_superuser:
        return JsonResponse({"error": "You are not authorized to reset the timeout."}, status=403)
    spj = SceneProcessingJob.objects.get(id=spj_id)
    
    # Check all queues, starting with most common (default) for efficiency
    rq_job, _ = find_rq_job_with_queue_name(spj.rq_job_id)
    
    if not rq_job:
        return JsonResponse({"error": "Job not found."}, status=404)
    rq_job.timeout = settings.RQ_QUEUES["default"]["DEFAULT_TIMEOUT"]
    rq_job.save()
    return JsonResponse({"message": "Timeout reset successfully."}, status=200)

# @silk_profile(name='check_status')
def check_status(request, spj_id):
    logger.info(f"Checking status for SPJ ID: {spj_id}")
    # Retrieve the video object based on spj_id
    try:
        spj = SceneProcessingJob.objects.get(id=spj_id)
        if not user_can_access_spj(request, spj, viewer_only=False):
            # Check if user is anonymous and scene is private (requires login)
            if request.user.is_anonymous and spj.user and not (spj.public or spj.example):
                logger.info(f"Anonymous user accessing private scene {spj_id}, redirecting to login")
                login_url = reverse('account_login')
                return redirect(f"{login_url}?next={request.path}")
        
            logger.warning(f"User does not have access to SPJ ID: {spj_id}")
            raise Http404("Job not found")

    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist.")
        raise Http404("Job not found")

    # Seeded/example scenes are already finished and never had an RQ job, so a
    # missing rq_job_id is only an error when there's also no output to show.
    if spj.rq_job_id:
        # Check all queues, starting with most common (default) for efficiency
        job, _ = find_rq_job_with_queue_name(spj.rq_job_id)
    elif spj.ply_file or spj.spz_file or spj.sog_file or spj.lod_file:
        job = None
    else:
        logger.error(f"RQ job ID is empty for SPJ ID: {spj_id}")
        raise Http404("Job not found")
    
    # Check the current job status (could be 'queued', 'started', 'finished', 'failed')
    status = get_status_string(spj, job)
    logger.info(f"Job status for SPJ ID {spj_id}: {status}")
    percent_complete = get_percent_complete(spj) if spj.preview_image else None
    if status == "Finished":
        percent_complete = 100

    return render(
        request,
        "status.html",
        {
            "spj": spj,
            "status": status,
            "percent_complete": percent_complete,
        },
    )

def download_ply(request, spj_id):
    return download(request, spj_id, request_ply=True)

def download_spz(request, spj_id):
    return download(request, spj_id, request_ply=False)

def sog_urls(request, spj_id):
    """Generate SAS URLs for all files in the unbundled SOG directory."""
    logger.info(f"SOG URLs request received for SPJ ID: {spj_id}")
    try:
        spj = SceneProcessingJob.objects.get(id=spj_id)

        if not user_can_access_spj(request, spj, viewer_only=True):
            logger.warning(f"User does not have permission to access SOG for SPJ ID: {spj_id}")
            raise Http404("Job not found.")

        if not spj.sog_file:
            logger.error(f"SOG file not found for SPJ ID: {spj_id}")
            raise Http404("SOG data not found.")

        # Derive the SOG directory prefix from the meta.json path
        sog_prefix = os.path.dirname(spj.sog_file.name)
        
        # Security check: Ensure we are only listing files within the sog_files directory
        # and that we are not at the root level.
        # We also check stripping trailing slash to catch 'sog_files/' case
        if not sog_prefix or not sog_prefix.startswith('sog_files/') or sog_prefix.rstrip('/') == 'sog_files':
             logger.error(f"Security: Invalid SOG prefix '{sog_prefix}' for SPJ ID: {spj_id}. Must start with 'sog_files/' and be in a subdirectory.")
             raise Http404("SOG data not found.")

        if sog_prefix and not sog_prefix.endswith('/'):
            sog_prefix += '/'

        # Initialize BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(
            settings.STORAGES["default"]["OPTIONS"]["connection_string"]
        )
        container_name = settings.STORAGES["default"]["OPTIONS"]["azure_container"]
        container_client = blob_service_client.get_container_client(container_name)

        # List all blobs under the SOG prefix
        sas_urls = {}
        for blob in container_client.list_blobs(name_starts_with=sog_prefix):
            blob_client = blob_service_client.get_blob_client(
                container=container_name, blob=blob.name
            )
            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=container_name,
                blob_name=blob.name,
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
            )
            # Use just the filename as the key (e.g., "meta.json", "means_l.webp")
            filename = os.path.basename(blob.name)
            sas_urls[filename] = {
                "url": f"{blob_client.url}?{sas_token}",
                "size": blob.size
            }

        logger.info(f"Generated SAS URLs for {len(sas_urls)} SOG files for SPJ ID: {spj_id}")
        return JsonResponse(sas_urls)

    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist.")
        raise Http404("File not found for this video.")

def lod_urls(request, spj_id):
    """Return per-blob SAS URLs for LOD octree files (secure per-file access).

    Similar to sog_urls, enumerates all blobs under the LOD prefix and generates
    individual SAS tokens for each. Uses relative paths as keys since LOD files
    live in subdirectories (e.g., "0/chunk_0.bin", "lod-meta.json").
    """
    logger.info(f"LOD URLs request received for SPJ ID: {spj_id}")
    try:
        spj = SceneProcessingJob.objects.get(id=spj_id)

        if not user_can_access_spj(request, spj, viewer_only=True):
            logger.warning(f"User does not have permission to access LOD for SPJ ID: {spj_id}")
            raise Http404("Job not found.")

        if not spj.lod_file:
            logger.error(f"LOD file not found for SPJ ID: {spj_id}")
            raise Http404("LOD data not found.")

        # Derive the LOD directory prefix from the lod-meta.json path
        lod_prefix = os.path.dirname(spj.lod_file.name)

        # Security check: ensure prefix is valid
        if not lod_prefix or not lod_prefix.startswith('lod_files/') or lod_prefix.rstrip('/') == 'lod_files':
            logger.error(f"Security: Invalid LOD prefix '{lod_prefix}' for SPJ ID: {spj_id}")
            raise Http404("LOD data not found.")

        if not lod_prefix.endswith('/'):
            lod_prefix += '/'

        # Initialize BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(
            settings.STORAGES["default"]["OPTIONS"]["connection_string"]
        )
        container_name = settings.STORAGES["default"]["OPTIONS"]["azure_container"]
        container_client = blob_service_client.get_container_client(container_name)

        # List all blobs under the LOD prefix and generate per-blob SAS URLs
        sas_urls = {}
        for blob in container_client.list_blobs(name_starts_with=lod_prefix):
            blob_client = blob_service_client.get_blob_client(
                container=container_name, blob=blob.name
            )
            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=container_name,
                blob_name=blob.name,
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
            )
            # Use relative path from LOD root as key (e.g., "lod-meta.json", "0/chunk_0.bin")
            relative_path = blob.name[len(lod_prefix):]
            sas_urls[relative_path] = {
                "url": f"{blob_client.url}?{sas_token}",
                "size": blob.size
            }

        logger.info(f"Generated SAS URLs for {len(sas_urls)} LOD files for SPJ ID: {spj_id}")
        return JsonResponse(sas_urls)

    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist.")
        raise Http404("File not found for this video.")

def download(request, spj_id, request_ply: bool = False):
    logger.info(f"Download request received for SPJ ID: {spj_id}")
    missing_file_string = "File not found for this video."
    try:
        # Retrieve the video object based on job_id
        spj = SceneProcessingJob.objects.get(id=spj_id)
        # Check if the user has view-only access
        if not user_can_access_spj(request, spj, viewer_only=True):
            logger.warning(f"User does not have permission to download file for SPJ ID: {spj_id}")
            raise Http404(missing_file_string)

        if not spj.ply_file and not spj.spz_file:
            logger.error(f"File not found for SPJ ID: {spj_id}")
            raise Http404(missing_file_string)

        if request_ply:
            file_to_download = spj.ply_file
        else:
            file_to_download = spj.spz_file

        logger.info(f"Downloading {file_to_download.name} for SPJ ID: {spj_id}")

        # Check if the file exists in the storage backend
        if default_storage.exists(file_to_download.name):
            logger.info(f"File found for SPJ ID: {spj_id}. Generating SAS URL.")

            # Initialize BlobServiceClient using the connection string
            blob_service_client = BlobServiceClient.from_connection_string(
                settings.STORAGES["default"]["OPTIONS"]["connection_string"]
            )

            # Extract container name and blob name
            container_name = settings.STORAGES["default"]["OPTIONS"]["azure_container"]
            blob_name = file_to_download.name

            # Get the BlobClient for the specific blob
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

            # Generate a safe filename from the title
            extension = 'ply' if request_ply else 'spz'
            # Remove special characters and convert to ASCII-only
            safe_filename = re.sub(r'[^\w\-_\. ]', '', spj.title)  # Remove special characters
            safe_filename = safe_filename.replace(' ', '_')  # Replace spaces with underscores
            
            # Handle non-ASCII characters by transliterating or replacing them
            # First try to normalize and convert to ASCII (transliteration)
            ascii_filename = unicodedata.normalize('NFKD', spj.title).encode('ascii', 'ignore').decode('ascii')
            # Then apply the same safety filters as before
            ascii_filename = re.sub(r'[^\w\-_\. ]', '', ascii_filename)
            ascii_filename = ascii_filename.replace(' ', '_')
            
            # Use the ASCII version if it's not empty, otherwise fall back to the original safe_filename
            download_filename = f"{ascii_filename or safe_filename}.{extension}"
            
            # For Content-Disposition, implement RFC 5987 encoding for the filename
            encoded_filename = urllib.parse.quote(download_filename)
            content_disposition = f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}"

            # Define SAS token parameters
            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=container_name,
                blob_name=blob_name,
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
                content_disposition=content_disposition
            )

            # Construct the full SAS URL
            sas_url = f"{blob_client.url}?{sas_token}"

            logger.info(f"SAS URL generated for SPJ ID: {spj_id}")

            # Option 1: Redirect user to the SAS URL
            return redirect(sas_url)

        else:
            logger.error(f"PLY file does not exist on the server for SPJ ID: {spj_id}")
            raise Http404(missing_file_string)

    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist.")
        raise Http404(missing_file_string)
     
def delete_job(request, spj_id):
    logger.info(f"Delete job request received for SPJ ID: {spj_id}")
    try:
        # Retrieve the video object based on spj_id
        spj = SceneProcessingJob.objects.get(id=spj_id)

        # Check if the user is authorized to delete the job
        if not user_can_access_spj(request, spj, viewer_only=False):
            logger.warning(f"User does not have permission to delete SPJ ID: {spj_id}")
            return JsonResponse({"error": "Job not found."}, status=404)
        
        is_superuser = request.user and request.user.is_superuser
        if spj.example and not is_superuser:
            logger.warning(f"Cannot delete example scene SPJ ID: {spj_id}")
            return JsonResponse({"error": "Scene cannot be deleted because it is an example. Please contact support if you would like to delete this scene."}, status=403)

        # Check if we need to refund credits for unfinished jobs
        if should_refund_credit_for_job(spj):
            logger.info(f"Refunding credit for unfinished job SPJ ID: {spj_id}")
            # Create refund transaction for job deletion
            CreditTransaction.create_refund_transaction(
                user=spj.user,
                scene_job=spj,
                credits_amount=1,
                user_notes="Job deleted before completion",
                auto_process=True
            )

        logger.info(f"Deleting video, PLY, and SOG files for SPJ ID: {spj_id}")
        spj.video_file.delete(save=True)
        spj.ply_file.delete(save=True)

        # Delete all blobs under the SOG directory prefix
        if spj.sog_file:
            sog_prefix = os.path.dirname(spj.sog_file.name)
            if sog_prefix:
                if not sog_prefix.endswith('/'):
                    sog_prefix += '/'
                try:
                    blob_service_client = BlobServiceClient.from_connection_string(
                        settings.STORAGES["default"]["OPTIONS"]["connection_string"]
                    )
                    container_name = settings.STORAGES["default"]["OPTIONS"]["azure_container"]
                    container_client = blob_service_client.get_container_client(container_name)
                    for blob in container_client.list_blobs(name_starts_with=sog_prefix):
                        container_client.delete_blob(blob.name)
                        logger.info(f"Deleted SOG blob: {blob.name}")
                except Exception as e:
                    logger.error(f"Error deleting SOG blobs for SPJ ID: {spj_id}: {e}")
            spj.sog_file.delete(save=True)

        # Delete all blobs under the LOD directory prefix
        if spj.lod_file:
            lod_prefix = os.path.dirname(spj.lod_file.name)
            if lod_prefix:
                if not lod_prefix.endswith('/'):
                    lod_prefix += '/'
                try:
                    blob_service_client = BlobServiceClient.from_connection_string(
                        settings.STORAGES["default"]["OPTIONS"]["connection_string"]
                    )
                    container_name = settings.STORAGES["default"]["OPTIONS"]["azure_container"]
                    container_client = blob_service_client.get_container_client(container_name)
                    for blob in container_client.list_blobs(name_starts_with=lod_prefix):
                        container_client.delete_blob(blob.name)
                        logger.info(f"Deleted LOD blob: {blob.name}")
                except Exception as e:
                    logger.error(f"Error deleting LOD blobs for SPJ ID: {spj_id}: {e}")
            spj.lod_file.delete(save=True)

        # Delete the job from the RQ queue if it exists
        # Check all queues, starting with most common (default) for efficiency
        job, queue_name = find_rq_job_with_queue_name(spj.rq_job_id)
        if job:
            logger.info(f"Deleting job from RQ queue ({queue_name}) for SPJ ID: {spj_id}")
            job.delete()

        # Delete the job
        spj.delete()
        logger.info(f"SPJ ID {spj_id} deleted successfully.")
        return redirect("/user/jobs")

    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist.")
        return JsonResponse({"error": "Job not found."}, status=404)


def preview_image(request, spj_id):
    logger.info(f"Preview image request received for SPJ ID: {spj_id}")
    missing_file_string = "Preview image not found for this video."
    try:
        spj = SceneProcessingJob.objects.get(id=spj_id)
        # Check if the user has view-only access
        if not user_can_access_spj(request, spj, viewer_only=True):
            logger.warning(f"User does not have permission to view preview for SPJ ID: {spj_id}")
            raise Http404(missing_file_string)

        if not spj.preview_image:
            logger.error(f"Preview image not found for SPJ ID: {spj_id}")
            raise Http404(missing_file_string)

        # Check if the file exists in the storage backend
        if default_storage.exists(spj.preview_image.name):
            logger.info(f"Preview image found for SPJ ID: {spj_id}. Preparing response.")
            # Open the file from storage
            file = default_storage.open(spj.preview_image.name, 'rb')
            return FileResponse(file, content_type='image/jpeg')
        else:
            logger.error(f"Preview image does not exist on the server for SPJ ID: {spj_id}")
            raise Http404(missing_file_string)

    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist.")
        raise Http404(missing_file_string)


class SceneProcessingJobCameraDataUpdateView(generics.UpdateAPIView):
    """
    API view to update the camera_data of a SceneProcessingJob.
    """
    queryset = SceneProcessingJob.objects.all()
    serializer_class = JobDetailSerializer
    permission_classes = [NoAPIKeyAllowed, IsOwnerOrAdminOrAnonymousForUnowned]

    lookup_field = 'id'  # The model's primary key field
    lookup_url_kwarg = 'spj_id'  # The URL parameter name for the primary key field

    # Example 
    # {"lookAt":{"x":0.30873,"y":0.0651,"z":0.0566},"position":{"x":0.1978,"y":-0.31153,"z":-2.30261},"up":{"x":0.47527,"y":-0.76384,"z":-0.43665}}

    def get_queryset(self):
        # For superusers, return all jobs
        if self.request.user.is_superuser:
            return super().get_queryset()
        
        # For authenticated users, return their own jobs AND anonymous jobs
        elif self.request.user.is_authenticated:
            return super().get_queryset().filter(
                models.Q(user=self.request.user) | models.Q(user__isnull=True)
            )
        
        # For anonymous users, only return jobs with no user (anonymous jobs)
        else:
            return super().get_queryset().filter(user__isnull=True)

    def update(self, request, *args, **kwargs):
        # Only allow updating the camera_data field
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        camera_data = request.data.get('camera_data')

        if camera_data is None:
            return Response(
                {"error": "camera_data field is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(
            instance,
            data={'camera_data': camera_data},
            partial=partial
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {"message": "Camera data updated successfully."},
            status=status.HTTP_200_OK
        )



# @silk_profile(name='upload_page')
def upload_page(request):
    """
    Renders the upload.html template with the VideoUploadForm.
    """
    logger.info("Rendering upload.html template.")
    
    # If user is superuser, log IP address for testing
    if request.user.is_superuser:
        logger.info(f"Superuser {request.user.username} logged in from IP ratelimit key {get_client_ip_ratelimit_key(None, request)}")

    form = VideoUploadForm(user=request.user)
    # Check if user can generate premium scenes (includes credit check for enterprise_perscene)
    user_has_premium = user_can_generate_premium_scene(request.user, api=False)
    return render(request, 'upload.html', {
        'form': form,
        'max_video_file_size': settings.MAX_VIDEO_FILE_SIZE_FREE if not user_has_premium else settings.MAX_VIDEO_FILE_SIZE_PRO,
        'DEFAULT_NUM_GAUSSIANS': SceneProcessingJob.DEFAULT_NUM_GAUSSIANS,
        'DEFAULT_NUM_STEPS': SceneProcessingJob.DEFAULT_NUM_STEPS,
        'MIN_NUM_GAUSSIANS': SceneProcessingJob.MIN_NUM_GAUSSIANS,
        'MAX_NUM_GAUSSIANS': SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE,
        'MIN_NUM_STEPS': SceneProcessingJob.MIN_NUM_STEPS,
        'MAX_NUM_STEPS': SceneProcessingJob.MAX_NUM_STEPS_FREE,
        'MAX_NUM_GAUSSIANS_PRO': SceneProcessingJob.MAX_NUM_GAUSSIANS,
        'MAX_NUM_STEPS_PRO': SceneProcessingJob.MAX_NUM_STEPS,
        'PILGRAM_FILTER_CHOICES': SceneProcessingJob.PILGRAM_FILTER_CHOICES
    })


def quest_upload_page(request):
    """
    Renders the quest_upload.html template with the QuestUploadForm.
    """
    logger.info("Rendering quest_upload.html template.")
    
    # If user is superuser, log IP address for testing
    if request.user.is_superuser:
        logger.info(f"Superuser {request.user.username} logged in from IP ratelimit key {get_client_ip_ratelimit_key(None, request)}")

    from .forms import QuestUploadForm
    form = QuestUploadForm(user=request.user)
    
    # Check if user can generate premium scenes
    user_has_premium = user_can_generate_premium_scene(request.user, api=False)
    
    return render(request, 'quest_upload.html', {
        'form': form,
        'max_video_file_size': settings.MAX_QUEST_FILE_SIZE_PRO if user_has_premium else settings.MAX_QUEST_FILE_SIZE_FREE,
        'DEFAULT_NUM_GAUSSIANS': SceneProcessingJob.DEFAULT_NUM_GAUSSIANS,
        'DEFAULT_NUM_STEPS': SceneProcessingJob.DEFAULT_NUM_STEPS,
        'MIN_NUM_GAUSSIANS': SceneProcessingJob.MIN_NUM_GAUSSIANS,
        'MAX_NUM_GAUSSIANS': SceneProcessingJob.MAX_NUM_GAUSSIANS_FREE,
        'MIN_NUM_STEPS': SceneProcessingJob.MIN_NUM_STEPS,
        'MAX_NUM_STEPS': SceneProcessingJob.MAX_NUM_STEPS_FREE,
        'MAX_NUM_GAUSSIANS_PRO': SceneProcessingJob.MAX_NUM_GAUSSIANS,
        'MAX_NUM_STEPS_PRO': SceneProcessingJob.MAX_NUM_STEPS,
    })

def generate_lod_upload_page(request):
    """
    Renders the generate_lod_upload.html template with the GenerateLODUploadForm.
    """
    logger.info("Rendering generate_lod_upload.html template.")
    
    # If user is superuser, log IP address for testing
    if request.user.is_superuser:
        logger.info(f"Superuser {request.user.username} logged in from IP ratelimit key {get_client_ip_ratelimit_key(None, request)}")

    from .forms import GenerateLODUploadForm
    form = GenerateLODUploadForm(user=request.user)
    return render(request, 'generate_lod_upload.html', {
        'form': form,
        'max_video_file_size': 6 * 1024 * 1024 * 1024, # 6gb
    })

@login_required
def set_public_status(request, spj_id, public):
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed."}, status=405)
    
    # Validate the public parameter
    if public.lower() not in ['true', 'false']:
        return JsonResponse({"error": "Invalid value for public parameter."}, status=400)
    
    public_bool = public.lower() == 'true'
    
    try:
        spj = SceneProcessingJob.objects.get(id=spj_id)
        
        # Explicitly prevent modification of anonymous scenes
        if not spj.user:
            logger.warning(f"Attempt to modify public status of anonymous scene {spj_id} by user {request.user.username}")
            return JsonResponse({"error": "Cannot modify anonymous scenes."}, status=403)
        
        # Check user permissions for non-anonymous scenes
        if not user_can_access_spj(request, spj, viewer_only=False):
            logger.warning(f"User {request.user.username} attempted to modify scene {spj_id} without permission")
            return JsonResponse({"error": "Job not found."}, status=404)
        
        # Set the public status to the explicit value
        spj.public = public_bool
        spj.save()
        
        logger.info(f"Public status for SPJ ID {spj_id} updated to: {public_bool} by user {request.user.username}")
        
        return redirect('check_status', spj_id=spj_id)
        
    except SceneProcessingJob.DoesNotExist:
        return JsonResponse({"error": "Job not found."}, status=404)

@login_required
def admin_preview_images(request):
    """
    Admin-only view that displays preview images for all scenes.
    """
    if not request.user.is_superuser:
        logger.warning(f"Non-admin user {request.user.username} attempted to access admin preview images")
        raise Http404("Page not found")
    
    # Get all scene processing jobs that have preview images
    scenes = SceneProcessingJob.objects.filter(preview_image__isnull=False).order_by('-uploaded_at')
    
    return render(
        request,
        "admin_previews.html",
        {
            "scenes": scenes,
        },
    )

 

@login_required
def test_job_completion_email(request, spj_id):
    """
    Test endpoint to send a job completion email for a specific job.
    Admin-only access.
    """
    if not request.user.is_superuser:
        logger.warning(f"Non-admin user {request.user.username} attempted to access test email endpoint")
        return Http404("Page not found")
    
    try:
        spj = SceneProcessingJob.objects.get(id=spj_id)
        
        # Send the test email
        send_job_completion_email(spj, delay_seconds=60)
        
        logger.info(f"Test job completion email sent for SPJ ID: {spj_id} by admin {request.user.username}")
        return JsonResponse({
            "success": True,
            "message": f"Test job completion email sent for job '{spj.title}' to {spj.user.email if spj.user else 'No user'}"
        })
        
    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist for test email")
        return JsonResponse({"error": "Job not found."}, status=404)
    except Exception as e:
        logger.error(f"Error sending test job completion email for SPJ ID {spj_id}: {e}")
        return JsonResponse({"error": f"Failed to send test email: {str(e)}"}, status=500)


def autolod_view(request, memory64=False):
    """
    Serves the AutoLOD WASM tool page.
    Requires COOP/COEP headers for SharedArrayBuffer (used by pthreads).
    
    Args:
        memory64: If True, use 64-bit WASM build (supports larger files, slower).
                  If False, use 32-bit build (faster, Safari compatible).
    """
    template = 'autolod64.html' if memory64 else 'autolod.html'
    response = render(request, template)
    # Required headers for SharedArrayBuffer (WASM pthreads)
    response['Cross-Origin-Opener-Policy'] = 'same-origin'
    response['Cross-Origin-Embedder-Policy'] = 'require-corp'
    return response

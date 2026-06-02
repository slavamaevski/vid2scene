from django.shortcuts import render, redirect
from video_processor.models import SceneProcessingJob, is_publicly_shareable
from django.http import Http404
from django.urls import reverse
import logging
from video_processor.views import user_can_access_spj
from django.views.decorators.clickjacking import xframe_options_exempt
logger = logging.getLogger(__name__)


@xframe_options_exempt
def viewer(request, spj_id):
    logger.info(f"Viewer request received for SPJ ID: {spj_id}")
    
    # Retrieve the video object based on spj_id
    try:
        spj = SceneProcessingJob.objects.get(id=spj_id)
        logger.info(f"SceneProcessingJob found for SPJ ID: {spj_id}")
    except SceneProcessingJob.DoesNotExist:
        logger.error(f"SceneProcessingJob with ID {spj_id} does not exist.")
        raise Http404("Could not find splat with given id")
    
    access_granted = user_can_access_spj(request, spj, viewer_only=True)
    is_owner = user_can_access_spj(request, spj, viewer_only=False)
    if not access_granted:
        # Check if user is anonymous and scene is private (requires login)
        if request.user.is_anonymous and spj.user and not (spj.public or spj.example):
            logger.info(f"Anonymous user accessing private scene {spj_id}, redirecting to login")
            login_url = reverse('account_login')
            return redirect(f"{login_url}?next={request.path}")
        
        logger.warning(f"User does not have access to SPJ ID: {spj_id}")
        raise Http404("Could not find splat with given id")
    
    logger.info(f"Rendering viewer for SPJ ID: {spj_id}")
    show_preview = spj.preview_image is not None
    logger.info(f"Show preview: {show_preview}")

    is_shareable = is_publicly_shareable(spj)

    return render(
        request,
        "viewer.html",
        {
            "spj": spj,
            "show_preview": show_preview,
            "is_owner": is_owner,
            "is_shareable": is_shareable,
        }
    )

from django.contrib.staticfiles import finders
from django.http import HttpResponse

def service_worker(request):
    """Serve sw.js from the root with broad scope permissions."""
    # Try to find built file first (prod), then source (dev)
    path = finders.find('sw.js') or finders.find('src/sw.js')

    # Use FileResponse for efficient serving
    from django.http import FileResponse
    response = FileResponse(open(path, 'rb'), content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    # Cache for 5 minutes (300s) to reduce server load while allowing updates quickly
    response['Cache-Control'] = 'public, max-age=300'
    return response
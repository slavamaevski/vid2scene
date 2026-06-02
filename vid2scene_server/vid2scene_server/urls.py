"""
URL configuration for vid2scene_server project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include, re_path
from video_processor import views as vp_views
from video_processor import web_api as vp_web_api
from video_processor import dev_api as vp_dev_api
from viewer import views as viewer_views
from user_homebase import views as user_homebase_views
from user_statistics import views as user_statistics_views
from svraster_webgl_demo import views as svraster_webgl_demo_views
from django.views.generic import TemplateView

def trigger_error(request):
    division_by_zero = 1 / 0

urlpatterns = [
    path("admin/statistics/", user_statistics_views.admin_statistics, name="admin_statistics"),
    path("admin/previews/", vp_views.admin_preview_images, name="admin_preview_images"),
    path("admin/test-email/<uuid:spj_id>/", vp_views.test_job_completion_email, name="test_job_completion_email"),
    path("admin/", admin.site.urls),
    path("django-rq/", include("django_rq.urls")),
    path('accounts/', include('allauth.urls')),
    path("upload/", vp_views.upload_page, name="upload_page"),
    path("upload/quest/", vp_views.quest_upload_page, name="quest_upload_page"),
    path("upload/ply/", vp_views.generate_lod_upload_page, name="generate_lod_upload_page"),
    path("status/<uuid:spj_id>/", vp_views.check_status, name="check_status"),
    re_path(r"downloadPly/(?P<spj_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\.ply)?/?$", vp_views.download_ply, name="download_ply"),
    re_path(r"download/(?P<spj_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\.spz)?/?$", vp_views.download_spz, name="download_spz"),
    path("sog/<uuid:spj_id>/", vp_views.sog_urls, name="sog_urls"),
    path("lod/<uuid:spj_id>/", vp_views.lod_urls, name="lod_urls"),
    path("delete/<uuid:spj_id>/", vp_views.delete_job, name="delete_job"),
    path("set-public/<uuid:spj_id>/<str:public>/", vp_views.set_public_status, name="set_public_status"),
    path("viewer/<uuid:spj_id>/", viewer_views.viewer, name="splat_viewer_spj_id"),
    path("preview/<uuid:spj_id>/", vp_views.preview_image, name="preview_image"),
    
    # WEB API (session-based; used by web client)
    path('web_api/generate-upload-sas/', vp_web_api.generate_upload_sas, name='web_api_generate_upload_sas'),
    path('web_api/submit-video/', vp_web_api.submit_video, name='web_api_submit_video'),
    path('web_api/submit-quest/', vp_web_api.submit_quest, name='web_api_submit_quest'),
    path('web_api/submit-splat/', vp_web_api.submit_generate_lod, name='web_api_submit_generate_lod'),
    path('web_api/jobs/<uuid:job_id>/status/', vp_web_api.api_job_status, name='web_api_job_status'),
    path('web_api/jobs/<uuid:job_id>/downloads/', vp_web_api.api_job_download_urls, name='web_api_job_download_urls'),
    path('web_api/jobs/<uuid:job_id>/viewer/', vp_web_api.api_job_viewer_url, name='web_api_job_viewer_url'),
    path('web_api/jobs/<uuid:job_id>/preview/', vp_web_api.api_job_preview_url, name='web_api_job_preview_url'),
    path('web_api/jobs/<uuid:job_id>/refund/', vp_web_api.request_refund, name='request_refund'),
    path(
        'web_api/scene-processing-jobs/<uuid:spj_id>/camera-data/',
        vp_views.SceneProcessingJobCameraDataUpdateView.as_view(),
        name='web_update_camera_data'
    ),

    # DEV API (Enterprise-only; API key auth; no rate limits)
    path('api/v1/generate-upload-url/', vp_dev_api.generate_upload_url, name='api_generate_upload_url'),
    path('api/v1/submit-job/', vp_dev_api.submit_job, name='api_submit_job'),
    path('api/v1/jobs/', vp_dev_api.JobListAPIView.as_view(), name='api_jobs'),
    path('api/v1/jobs/<uuid:job_id>/', vp_dev_api.JobRetrieveUpdateDestroyAPIView.as_view(), name='api_job_detail'),
    # Removed redundant status endpoint for dev API
    path('api/v1/jobs/<uuid:job_id>/download/<str:file_type>/', vp_dev_api.api_job_download_file, name='api_job_download_file'),
    path('api/v1/jobs/<uuid:job_id>/preview/', vp_dev_api.api_job_preview_image, name='api_job_preview_url'),
    
    path("user/", include("user_homebase.urls")),  # Include the new app's URLs
    path("docs/", include("documentation.urls")),
    path("examples/", include("examples.urls")),
    path("", user_homebase_views.landing_page, name="landing_page"),
    path("responsible-ai/", user_homebase_views.responsible_ai, name="responsible_ai"),
    path("disable-tracking/", user_homebase_views.disable_tracking, name="disable_tracking"),
    path("privacy/", user_homebase_views.privacy_policy, name="privacy_policy"),
    path("terms/", user_homebase_views.terms_of_service, name="terms_of_service"),
    path("voxel/", svraster_webgl_demo_views.svraster_webgl_demo, name="svraster_webgl_demo"),
    path("vid2scene-error-debug/", trigger_error),
    path("sw.js", viewer_views.service_worker, name="service_worker"),
    path("subscriptions/", include("subscriptions.urls")),
    # OpenAPI spec and Swagger UI (minimal)
    path("openapi.yaml", TemplateView.as_view(template_name="openapi.yaml", content_type="text/yaml"), name="openapi_spec"),
    path("docs/api", TemplateView.as_view(template_name="documentation/swagger.html"), name="swagger_ui"),
    # AutoLOD WASM tool (32-bit: faster, Safari compatible)
    path("autolod/", vp_views.autolod_view, name="autolod"),
    # AutoLOD WASM tool (64-bit: supports larger files >1GB, slower)
    path("autolod64/", vp_views.autolod_view, {'memory64': True}, name="autolod64"),

]

# urlpatterns += [path('silk/', include('silk.urls', namespace='silk'))]

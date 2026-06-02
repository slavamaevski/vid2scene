from django.urls import path
from . import views

urlpatterns = [
    path("profile/", views.profile, name="profile"),
    path("jobs/", views.job_status, name="jobs_status"),
    path("api-keys/generate/", views.generate_api_key, name="generate_api_key"),
    path("api-keys/revoke/", views.revoke_api_key, name="revoke_api_key"),
]

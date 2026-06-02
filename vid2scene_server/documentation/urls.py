from django.urls import path
from . import views

urlpatterns = [
    path('', views.api_docs, name='api_docs'),
    path('getting-started/', views.getting_started, name='getting_started'),
    path('authentication/', views.authentication, name='authentication_docs'),
    path('endpoints/', views.endpoints, name='endpoints_docs'),
]

from django.urls import path
from . import views

urlpatterns = [
    path('', views.example_list, name='example_list'),
    path('recording/', views.example_recording, name='example_recording'),
]

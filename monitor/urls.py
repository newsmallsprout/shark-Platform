from django.urls import path
from . import views

urlpatterns = [
    path('config', views.monitor_config),
    path('status', views.monitor_status),
    path('start', views.monitor_start),
    path('stop', views.monitor_stop),
]

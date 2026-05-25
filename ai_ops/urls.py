from django.urls import path
from . import views

urlpatterns = [
    path('webhook/prometheus', views.prometheus_webhook, name='prometheus_webhook'),
    path('incidents', views.incident_list, name='incident_list'),
    path('incidents/<int:pk>', views.incident_detail, name='incident_detail'),
    path('config', views.ai_config, name='ai_config'),
]

from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_summary, name='ai_ops_dashboard'),
    path('webhook/prometheus', views.prometheus_webhook, name='prometheus_webhook'),
    path('incidents', views.incident_list, name='incident_list'),
    path('incidents/<int:pk>', views.incident_detail, name='incident_detail'),
    path('config', views.ai_config, name='ai_config'),
    path('diagnose/<int:incident_id>/', views.diagnose_incident, name='ai_ops_diagnose_incident'),
    path('diagnose/', views.diagnose_incident, name='ai_ops_diagnose'),
    path('tickets/<uuid:ticket_id>', views.ticket_detail, name='ai_ops_ticket_detail'),
    path('tickets/<uuid:ticket_id>/submit/', views.ticket_submit, name='ai_ops_ticket_submit'),
    path('tickets/<uuid:ticket_id>/approve/', views.ticket_approve, name='ai_ops_ticket_approve'),
    path('tickets/<uuid:ticket_id>/reject/', views.ticket_reject, name='ai_ops_ticket_reject'),
]

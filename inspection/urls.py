from django.urls import path
from . import views

urlpatterns = [
    path('config', views.inspection_config),
    path('run', views.run_inspection),
    path('reports', views.history),
    path('reports/<str:report_id>', views.get_report),
]

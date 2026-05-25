from django.urls import path
from . import views

urlpatterns = [
    path('tasks', views.monitor_tasks),
    path('tasks/<int:pk>', views.monitor_task_detail),
    path('logs', views.monitor_logs),
    path('logs/history', views.monitor_logs_history),
    path('logs/index_detail', views.monitor_index_detail),
    path('logs/view', views.monitor_log_view),
    path('logs/download', views.monitor_log_download),
    path('logs/merge_download', views.monitor_log_merge_download),
    path('logs/batch_search', views.monitor_log_batch_search),
]

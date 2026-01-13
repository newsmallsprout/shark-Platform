from django.urls import path
from . import views

urlpatterns = [
    path('connections', views.connection_list),
    path('connections/test', views.connection_test),
    path('connections/<str:conn_id>', views.connection_detail),
    
    path('tasks/list', views.task_list),
    path('tasks/status', views.task_status_list),
    path('tasks/start', views.start_task),
    path('tasks/stop/<str:task_id>', views.stop_task),
    path('tasks/delete/<str:task_id>', views.delete_task),
    path('tasks/logs/<str:task_id>', views.task_logs),
]

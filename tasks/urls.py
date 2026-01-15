from django.urls import path
from . import views

urlpatterns = [
    path('connections', views.connection_list),
    path('connections/test', views.connection_test),
    path('connections/<str:conn_id>', views.connection_detail),
    
    path('tasks/list', views.task_list),
    path('tasks/status', views.task_status_list),
    path('tasks/status/<str:task_id>', views.task_status_detail),
    path('tasks/start', views.start_task),
    path('tasks/start_with_conn_ids', views.start_with_conn_ids),
    path('tasks/start_existing/<str:task_id>', views.start_existing),
    path('tasks/reset_and_start/<str:task_id>', views.reset_and_start),
    path('tasks/stop/<str:task_id>', views.stop_task),
    path('tasks/stop_soft/<str:task_id>', views.stop_task_soft),
    path('tasks/delete/<str:task_id>', views.delete_task),
    path('tasks/logs/<str:task_id>', views.task_logs),
    
    path('mysql/databases', views.mysql_databases),
    path('mysql/databases_by_id/<str:conn_id>', views.mysql_databases_by_id),
    path('mysql/tables', views.mysql_tables),
    path('mysql/tables_by_id/<str:conn_id>', views.mysql_tables_by_id),
]

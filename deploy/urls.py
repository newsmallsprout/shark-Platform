from django.urls import path
from . import views

urlpatterns = [
    path('servers', views.server_list),
    path('run', views.run_deploy),
    path('execute/<str:plan_id>', views.execute_plan),
    path('plans/<str:plan_id>', views.get_plan),
]

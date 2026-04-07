from django.urls import path

from . import views

urlpatterns = [
    path("system/health", views.health_check, name="health_check"),
    path("system/stats", views.system_stats, name="system_stats"),
    path("users", views.user_list, name="user_list"),
    path("users/<int:pk>", views.user_detail, name="user_detail"),
    path("roles", views.role_list, name="role_list"),
    path("permissions", views.permission_list, name="permission_list"),
    path("me", views.me, name="me"),
    path("auth/login", views.login_view, name="api_login"),
    path("auth/logout", views.logout_view, name="api_logout"),
    path("edge/heartbeat", views.edge_heartbeat, name="edge_heartbeat"),
    path("edge/logs", views.edge_logs, name="edge_logs"),
    path("edge/playbooks", views.edge_playbooks_poll, name="edge_playbooks_poll"),
    path(
        "edge/playbooks/<uuid:job_id>/complete",
        views.edge_playbook_complete,
        name="edge_playbook_complete",
    ),
    path("edge/metrics", views.edge_custom_metrics, name="edge_custom_metrics"),
]

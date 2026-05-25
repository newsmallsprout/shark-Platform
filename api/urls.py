from django.urls import path
from . import views

urlpatterns = [
    path('system/stats', views.system_stats, name='system_stats'),
    path('users', views.user_list, name='user_list'),
    path('users/<int:pk>', views.user_detail, name='user_detail'),
    path('roles', views.role_list, name='role_list'),
    path('permissions', views.permission_list, name='permission_list'),
    path('me', views.me, name='me'),
    path('auth/login', views.login_view, name='api_login'),
    path('auth/logout', views.logout_view, name='api_logout'),
]

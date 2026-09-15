from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

urlpatterns = [
    path('system/health', views.health_check, name='health_check'),
    path('system/stats', views.system_stats, name='system_stats'),
    path('users', views.user_list, name='user_list'),
    path('users/<int:pk>', views.user_detail, name='user_detail'),
    path('roles', views.role_list, name='role_list'),
    path('permissions', views.permission_list, name='permission_list'),
    path('me', views.me, name='me'),
    path('auth/login', views.login_view, name='api_login'),
    path('auth/logout', views.logout_view, name='api_logout'),
    # JWT (pentest 认证方式)
    path('auth/token', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh', TokenRefreshView.as_view(), name='token_refresh'),
]

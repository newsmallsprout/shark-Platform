from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', core_views.index, name='index'),
    path('deploy/', include('deploy.urls')),
    path('', include('tasks.urls')), # Tasks and Connections
    path('monitor/', include('monitor.urls')),
    path('inspection/', include('inspection.urls')),
]

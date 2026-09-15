from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),

    # 认证 / 用户 / 角色 / 权限 (api app)
    path('api/', include('api.urls')),
    # 日志监控 (log monitor)
    path('api/monitor/', include('monitor.urls')),
    # 排班管理 (schedule mgmt)
    path('api/', include('schedules.urls')),
    # 渗透测试模块 (pentest 后端合并，挂载 /api/v1/)
    path('api/v1/', include('security.urls')),
]

from django.contrib import admin
from .models import MonitorTask

@admin.register(MonitorTask)
class MonitorTaskAdmin(admin.ModelAdmin):
    list_display = ('name', 'enabled', 'poll_interval_seconds', 'last_run')

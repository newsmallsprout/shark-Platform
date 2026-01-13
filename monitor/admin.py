from django.contrib import admin
from .models import MonitorConfig

@admin.register(MonitorConfig)
class MonitorConfigAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'enabled', 'poll_interval_seconds')

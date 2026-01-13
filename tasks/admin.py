from django.contrib import admin
from .models import Connection, SyncTask

@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'host', 'port')
    search_fields = ('name', 'host')

@admin.register(SyncTask)
class SyncTaskAdmin(admin.ModelAdmin):
    list_display = ('task_id', 'status', 'created_at')
    list_filter = ('status',)

from django.contrib import admin
from .models import Server, DeployPlan

@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'host', 'user', 'port', 'auth_method')
    search_fields = ('name', 'host')

@admin.register(DeployPlan)
class DeployPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'progress', 'created_at')
    list_filter = ('status',)
    readonly_fields = ('created_at',)

from django.contrib import admin
from .models import InspectionConfig

@admin.register(InspectionConfig)
class InspectionConfigAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'prometheus_url')

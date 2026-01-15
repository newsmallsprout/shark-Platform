from django.db import models

class InspectionConfig(models.Model):
    prometheus_url = models.CharField(max_length=1024, blank=True, null=True)
    ark_base_url = models.CharField(max_length=1024, blank=True, null=True)
    ark_api_key = models.CharField(max_length=255, blank=True, null=True)
    ark_model_id = models.CharField(max_length=255, blank=True, null=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super(InspectionConfig, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Inspection Configuration"

class InspectionReport(models.Model):
    report_id = models.CharField(max_length=50, unique=True)
    content = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.report_id

from django.db import models

class MonitorConfig(models.Model):
    # Singleton pattern mostly
    enabled = models.BooleanField(default=False)
    es_hosts = models.CharField(max_length=1024, blank=True, null=True)
    es_username = models.CharField(max_length=255, blank=True, null=True)
    es_password = models.CharField(max_length=255, blank=True, null=True)
    index_pattern = models.CharField(max_length=255, blank=True, null=True)
    slack_webhook_url = models.CharField(max_length=1024, blank=True, null=True)
    poll_interval_seconds = models.IntegerField(default=60)
    alert_keywords = models.JSONField(default=list)
    ignore_keywords = models.JSONField(default=list)
    record_only_keywords = models.JSONField(default=list)

    def save(self, *args, **kwargs):
        self.pk = 1
        super(MonitorConfig, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Monitor Configuration"

from django.db import models

class Server(models.Model):
    AUTH_CHOICES = [
        ('key', 'SSH Key'),
        ('password', 'Password'),
    ]
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=255)
    host = models.CharField(max_length=255)
    port = models.IntegerField(default=22)
    user = models.CharField(max_length=255, default="root")
    auth_method = models.CharField(max_length=20, choices=AUTH_CHOICES, default="key")
    password = models.CharField(max_length=255, blank=True, null=True)
    key_path = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name

class DeployPlan(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('error', 'Error'),
    ]
    id = models.CharField(max_length=100, primary_key=True)
    req = models.JSONField() # The DeployRequest
    artifacts = models.JSONField(default=list)
    commands = models.JSONField(default=list)
    requirements = models.JSONField(default=list)
    targets = models.JSONField(default=list)
    logs = models.JSONField(default=list)
    progress = models.IntegerField(default=0)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="pending")
    error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.id

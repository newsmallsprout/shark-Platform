from django.db import models

class Connection(models.Model):
    id = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=50) # mysql, mongo
    host = models.CharField(max_length=255, blank=True, null=True)
    port = models.IntegerField(null=True, blank=True)
    user = models.CharField(max_length=255, blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    database = models.CharField(max_length=255, blank=True, null=True)
    
    # Mongo specific
    auth_source = models.CharField(max_length=255, default="admin")
    replica_set = models.CharField(max_length=255, blank=True, null=True)
    mongo_hosts = models.TextField(blank=True, null=True) # Store as comma separated or JSON

    # MySQL specific
    use_ssl = models.BooleanField(default=False)

    def __str__(self):
        return self.name

class SyncTask(models.Model):
    task_id = models.CharField(max_length=100, primary_key=True)
    config = models.JSONField(default=dict) # Store the full Pydantic model dump here
    state = models.JSONField(default=dict)  # Store runtime state (log_pos, metrics)
    status = models.CharField(max_length=50, default="stopped")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.task_id

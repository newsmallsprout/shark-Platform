from django.db import models


class TrafficDashboardConfig(models.Model):
    """Singleton (pk=1): Nginx log paths, GeoIP, Prometheus for Blackbox."""

    ACCESS_LOG_MODE_FILE = "file"
    ACCESS_LOG_MODE_REDIS = "redis"
    ACCESS_LOG_MODE_CHOICES = [
        (ACCESS_LOG_MODE_FILE, "Local file (pod / shared volume)"),
        (ACCESS_LOG_MODE_REDIS, "Remote ingest → Redis buffer (separate Nginx host)"),
    ]

    enabled = models.BooleanField(default=True)
    access_log_mode = models.CharField(
        max_length=16,
        default=ACCESS_LOG_MODE_FILE,
        choices=ACCESS_LOG_MODE_CHOICES,
        help_text="file = read access_log_path on Shark; redis = read lines pushed via POST /api/traffic/ingest (needs TRAFFIC_REDIS_URL).",
    )
    access_log_path = models.CharField(
        max_length=1024,
        blank=True,
        help_text="Nginx access log file path (JSON or combined). Empty = env TRAFFIC_NGINX_ACCESS_LOG. Used when access_log_mode=file.",
    )
    error_log_path = models.CharField(
        max_length=1024,
        blank=True,
        help_text="Optional: Nginx error log path (for future use).",
    )
    log_format = models.CharField(
        max_length=32,
        default="json",
        choices=[("json", "JSON lines"), ("combined", "Nginx combined")],
    )
    max_tail_bytes = models.PositiveIntegerField(
        default=5_242_880,
        help_text="Max bytes read from end of access log per request (file mode only).",
    )
    redis_log_key = models.CharField(
        max_length=256,
        default="traffic:access:lines",
        blank=True,
        help_text="Redis list key for buffered access log lines (redis mode).",
    )
    redis_max_lines = models.PositiveIntegerField(
        default=200_000,
        help_text="Max lines kept in Redis list (RPUSH + LTRIM keeps the most recent N lines).",
    )
    dashboard_fetch_max_lines = models.PositiveIntegerField(
        default=35_000,
        help_text="Traffic dashboard: max lines read from Redis list tail per snapshot (lower = faster; ingest cap unchanged).",
    )
    log_sources = models.JSONField(
        default=list,
        blank=True,
        help_text='Multi-site: [{"id":"api","label":"API","file_path":"...","redis_key":"...","log_format":""}]. '
        "id matches go-log-collector stream_key. Optional log_format: json, nginx_json, combined, auto. "
        "Redis: POST /api/edge/logs or /api/traffic/ingest?source=<id>. Empty list = single legacy path / redis_log_key.",
    )
    geoip_db_path = models.CharField(
        max_length=1024,
        blank=True,
        help_text="MaxMind GeoIP2 / GeoLite2 City database path (.mmdb). Empty = env TRAFFIC_GEOIP_DB or no GeoIP.",
    )
    use_inspection_prometheus = models.BooleanField(
        default=True,
        help_text="Use Inspection → Prometheus URL for Blackbox metrics.",
    )
    prometheus_url_override = models.CharField(
        max_length=1024,
        blank=True,
        help_text="If set, overrides Inspection Prometheus for Blackbox queries only.",
    )
    blackbox_promql = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Optional instant vector query for probes, e.g. probe_success. Empty = auto probe_success.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Traffic Dashboard Config"


class TrafficMinuteRollup(models.Model):
    """
    Per-minute aggregates persisted from ingest (Redis buffer → flush job).
    Enables arbitrary time-range charts without re-scanning the full raw log tail.
    """

    bucket_start = models.DateTimeField(
        db_index=True,
        help_text="UTC minute start (inclusive).",
    )
    source_id = models.CharField(
        max_length=64,
        db_index=True,
        default="",
        blank=True,
        help_text="Matches ingest ?source= / X-Traffic-Source; empty = default.",
    )
    requests = models.PositiveIntegerField(default=0)
    sum_latency_ms = models.PositiveBigIntegerField(default=0)
    count_latency = models.PositiveIntegerField(default=0)
    status_2xx = models.PositiveIntegerField(default=0)
    status_4xx = models.PositiveIntegerField(default=0)
    status_5xx = models.PositiveIntegerField(default=0)
    p50_ms = models.FloatField(null=True, blank=True)
    p95_ms = models.FloatField(null=True, blank=True)
    p99_ms = models.FloatField(null=True, blank=True)
    geo_counts = models.JSONField(default=dict, blank=True)
    top_paths = models.JSONField(default=list, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["bucket_start", "source_id"]
        unique_together = [("bucket_start", "source_id")]
        indexes = [
            models.Index(fields=["bucket_start", "source_id"]),
        ]

    def __str__(self):
        return f"{self.bucket_start.isoformat()} {self.source_id!r} n={self.requests}"

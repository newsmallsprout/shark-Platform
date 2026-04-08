import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="LogStream",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("stream_key", models.CharField(db_index=True, max_length=128, unique=True)),
                ("display_name", models.CharField(blank=True, default="", max_length=256)),
                ("notes", models.TextField(blank=True, default="", help_text="运维备注，可选")),
                ("last_event_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-last_event_at", "stream_key"],
            },
        ),
        migrations.CreateModel(
            name="LogEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("stream_key", models.CharField(db_index=True, max_length=128)),
                ("event_time", models.DateTimeField(db_index=True)),
                ("host", models.CharField(blank=True, default="", max_length=255)),
                ("method", models.CharField(blank=True, default="", max_length=16)),
                ("path", models.TextField(blank=True, default="")),
                ("status_code", models.PositiveSmallIntegerField(default=0)),
                ("bytes_sent", models.PositiveIntegerField(default=0)),
                (
                    "request_time",
                    models.FloatField(
                        blank=True,
                        help_text="请求耗时（秒），来自 $request_time",
                        null=True,
                    ),
                ),
                (
                    "upstream_time",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="上游耗时原始串，可能含多值",
                        max_length=64,
                    ),
                ),
                ("parser", models.CharField(blank=True, default="", max_length=32)),
                ("raw_excerpt", models.CharField(blank=True, default="", max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-event_time"],
            },
        ),
        migrations.CreateModel(
            name="LogInsight",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("stream_key", models.CharField(db_index=True, max_length=128)),
                ("insight_type", models.CharField(db_index=True, max_length=64)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("info", "Info"),
                            ("warning", "Warning"),
                            ("critical", "Critical"),
                        ],
                        default="warning",
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(max_length=512)),
                ("body", models.TextField(blank=True, default="")),
                ("evidence", models.JSONField(blank=True, default=dict)),
                ("window_start", models.DateTimeField(blank=True, null=True)),
                ("window_end", models.DateTimeField(blank=True, null=True)),
                (
                    "source",
                    models.CharField(
                        default="detector",
                        help_text="detector | llm | manual",
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="logevent",
            index=models.Index(fields=["stream_key", "event_time"], name="observabil_stream__idx"),
        ),
        migrations.AddIndex(
            model_name="logevent",
            index=models.Index(
                fields=["stream_key", "status_code", "event_time"],
                name="observabil_stream__2_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="loginsight",
            index=models.Index(fields=["stream_key", "-created_at"], name="observabil_stream__3_idx"),
        ),
    ]

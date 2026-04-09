# Generated manually for AgentRun

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_ops", "0012_brain_topology_knowledge_playbook"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentRun",
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
                (
                    "run_id",
                    models.CharField(
                        db_index=True,
                        help_text="与 SSE 频道 agent:run:{run_id} 一致",
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("webhook", "Webhook (Alertmanager)"),
                            ("manual", "Manual (console)"),
                            ("rejection_retry", "Rejection retry"),
                        ],
                        db_index=True,
                        default="manual",
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="queued",
                        max_length=24,
                    ),
                ),
                ("celery_task_id", models.CharField(blank=True, default="", max_length=128)),
                ("error_message", models.TextField(blank=True, default="")),
                ("meta", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "incident",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_runs",
                        to="ai_ops.incident",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="agent_runs",
                        to="ai_ops.ticket",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]

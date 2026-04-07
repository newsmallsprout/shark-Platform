import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_ops", "0011_ticket_replace_smart_ticket"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="ticket_class",
            field=models.CharField(
                choices=[
                    ("reactive", "Reactive (incident-driven)"),
                    ("preventive", "Preventive (prediction)"),
                ],
                db_index=True,
                default="reactive",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="impact_scope",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Blast radius: services, namespaces, SLO impact (AI-filled).",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="ai_confidence",
            field=models.FloatField(
                default=0.0,
                help_text="0..1 confidence for routing / auto-heal eligibility.",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="routing",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="human_approval | auto_heal | knowledge_matched",
                max_length=48,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="auto_heal_dispatched",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="KnowledgeEntry",
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
                ("signature_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("title", models.CharField(default="", max_length=255)),
                ("playbook_body", models.TextField(help_text="可执行脚本或标准化处置步骤")),
                ("hit_count", models.PositiveIntegerField(default=0)),
                ("success_after_apply", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="TopologySnapshot",
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
                    "scope",
                    models.CharField(db_index=True, default="global", max_length=64, unique=True),
                ),
                (
                    "nodes",
                    models.JSONField(default=list, help_text='[{"id","label","healthy"}]'),
                ),
                (
                    "edges",
                    models.JSONField(default=list, help_text='[{"from","to"}]'),
                ),
                ("health_score", models.FloatField(default=100.0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="PlaybookJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("target_node_id", models.CharField(db_index=True, max_length=128)),
                ("script", models.TextField(help_text="Shell script body for edge execution")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("dispatched", "Dispatched"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("result", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "ticket",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="playbook_jobs",
                        to="ai_ops.ticket",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]

# Generated manually for ops_tickets

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemOpsTicket',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, default='')),
                ('inspection_report_id', models.CharField(db_index=True, max_length=64)),
                ('inspection_snapshot', models.JSONField(blank=True, default=dict)),
                ('severity', models.CharField(choices=[('low', '低'), ('medium', '中'), ('high', '高'), ('critical', '紧急')], default='medium', max_length=16)),
                ('status', models.CharField(choices=[('open', '待处理'), ('in_progress', '处理中'), ('resolved', '已解决'), ('closed', '已关闭'), ('cancelled', '已取消')], default='open', max_length=24)),
                ('resolution_notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_system_ops_tickets', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_system_ops_tickets', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]

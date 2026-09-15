# ============================================================
# security/urls.py — 渗透测试 API 路由 (挂载于 /api/v1/)
# ============================================================

from django.urls import path

from . import views

urlpatterns = [
    # Tasks
    path("tasks", views.task_list, name="sec_task_list"),
    path("tasks/<uuid:task_id>", views.task_detail, name="sec_task_detail"),
    path("tasks/<uuid:task_id>/start", views.task_start, name="sec_task_start"),
    path("tasks/<uuid:task_id>/pause", views.task_pause, name="sec_task_pause"),
    path("tasks/<uuid:task_id>/resume", views.task_resume, name="sec_task_resume"),
    # Scans
    path("tasks/<uuid:task_id>/scan", views.scan_session, name="sec_scan_session"),
    path("tasks/<uuid:task_id>/scan/assets", views.scan_assets, name="sec_scan_assets"),
    path("tasks/<uuid:task_id>/scan/tools", views.scan_tools, name="sec_scan_tools"),
    path("tasks/<uuid:task_id>/vulnerabilities", views.task_vulnerabilities, name="sec_task_vulns"),
    path(
        "tasks/<uuid:task_id>/vulnerabilities/<uuid:vuln_id>",
        views.vuln_status,
        name="sec_vuln_status",
    ),
    # Reports
    path("reports", views.report_list, name="sec_report_list"),
    path("reports/tasks/<uuid:task_id>/generate", views.report_generate, name="sec_report_generate"),
    path("reports/<uuid:report_id>", views.report_detail, name="sec_report_detail"),
    path("reports/<uuid:report_id>/submit", views.report_submit, name="sec_report_submit"),
    # Knowledge
    path("knowledge", views.knowledge_list, name="sec_knowledge_list"),
    path("knowledge/ingest/text", views.knowledge_ingest, name="sec_knowledge_ingest"),
    path("knowledge/stats", views.knowledge_stats, name="sec_knowledge_stats"),
    path("knowledge/<uuid:doc_id>", views.knowledge_delete, name="sec_knowledge_delete"),
    # Guided
    path("tasks/<uuid:task_id>/guided/session", views.guided_session, name="sec_guided_session"),
    path("tasks/<uuid:task_id>/guided/messages", views.guided_messages, name="sec_guided_messages"),
    path("tasks/<uuid:task_id>/guided/stage", views.guided_stage, name="sec_guided_stage"),
]

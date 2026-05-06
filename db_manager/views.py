import csv
import sqlparse

from django.http import HttpResponse
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.views import HasRolePermission
from .engines import DBEngineFactory
from .models import BackupPlan, BackupRecord, DBAccessRule, DBInstance, DatabaseConnection, RestoreJob, RollbackJob, SQLAIReview, SQLApprovalOrder, SQLApprovalPolicy, SQLAuditLog, SQLExecutionJob, SQLExecutionPolicy
from .serializers import BackupPlanSerializer, BackupRecordSerializer, DBInstanceSerializer, RestoreJobSerializer, RollbackJobSerializer, SQLApprovalPolicySerializer, SQLExecuteRequestSerializer, SQLExecutionJobSerializer, SQLExecutionPolicySerializer, SQLFormatRequestSerializer
from .services import approval_is_overdue, approve_order, cancel_job, create_execution_job, create_restore_job, create_rollback_job, ensure_instance_access, execute_rollback_job, export_audit_rows, explain_access_preview, explain_sql, filter_accessible_instances, get_schema, get_table_detail, list_approval_applicants, matching_execution_policy, pause_job, recommend_execute_mode, recommend_permission_codename, reject_order, remind_approval, resume_job, run_backup_plan, run_instance_diagnostics, serialize_access_rule, serialize_backup_plan, serialize_execution_policy, serialize_instance, serialize_rollback_job, test_instance, upsert_access_rule, upsert_backup_plan, upsert_execution_policy, upsert_instance


def _normalize_db_connection_extra(conn_type, deployment_mode, extra_config):
    extra = dict(extra_config or {})
    if conn_type == "redis":
        extra["mode"] = "cluster" if deployment_mode == "cluster" else "standalone"
    return extra


def is_readonly(user):
    if user.is_superuser or user.is_staff:
        return False
    if user.has_perm('db_manager.change_databaseconnection'):
        return False
    return True


def _request_meta(request):
    return {
        "client_ip": request.META.get("REMOTE_ADDR"),
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
        "trace_id": request.META.get("HTTP_X_TRACE_ID", ""),
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def connection_list(request):
    if request.method == 'GET':
        conns = DatabaseConnection.objects.all().order_by('-created_at')
        data = []
        for c in conns:
            data.append({
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "deployment_mode": c.deployment_mode,
                "host": c.host,
                "port": c.port,
                "user": c.user,
                "database": c.database
            })
        return Response(data)
    if is_readonly(request.user):
        return Response({"error": "Permission Denied: Read-only account"}, status=403)
    data = request.data
    deployment_mode = data.get('deployment_mode') or 'single'
    if deployment_mode not in ('single', 'cluster'):
        deployment_mode = 'single'
    extra = _normalize_db_connection_extra(
        data.get('type') or '',
        deployment_mode,
        data.get('extra_config', {}),
    )
    conn = DatabaseConnection.objects.create(
        name=data.get('name'),
        type=data.get('type'),
        deployment_mode=deployment_mode,
        host=data.get('host'),
        port=data.get('port', 3306),
        user=data.get('user'),
        password=data.get('password'),
        database=data.get('database'),
        extra_config=extra,
    )
    return Response({"id": conn.id, "msg": "Created"})


@api_view(['GET', 'DELETE', 'PUT'])
@permission_classes([IsAuthenticated])
def connection_detail(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    if request.method == 'GET':
        return Response({
            "id": conn.id,
            "name": conn.name,
            "type": conn.type,
            "deployment_mode": conn.deployment_mode,
            "host": conn.host,
            "port": conn.port,
            "user": conn.user,
            "database": conn.database,
            "extra_config": conn.extra_config
        })
    if request.method == 'DELETE':
        if is_readonly(request.user):
            return Response({"error": "Permission Denied: Read-only account"}, status=403)
        conn.delete()
        return Response({"msg": "Deleted"})
    if is_readonly(request.user):
        return Response({"error": "Permission Denied: Read-only account"}, status=403)
    data = request.data
    conn.name = data.get('name', conn.name)
    if 'deployment_mode' in data:
        dm = data.get('deployment_mode') or 'single'
        conn.deployment_mode = dm if dm in ('single', 'cluster') else 'single'
    conn.host = data.get('host', conn.host)
    conn.port = data.get('port', conn.port)
    conn.user = data.get('user', conn.user)
    if 'password' in data:
        conn.password = data['password']
    conn.database = data.get('database', conn.database)
    base_extra = data.get('extra_config', conn.extra_config)
    conn.extra_config = _normalize_db_connection_extra(conn.type, conn.deployment_mode, base_extra)
    conn.save()
    return Response({"msg": "Updated"})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_connection(request):
    data = request.data
    dm = data.get('deployment_mode') or 'single'
    if dm not in ('single', 'cluster'):
        dm = 'single'
    extra = _normalize_db_connection_extra(
        data.get('type') or '',
        dm,
        data.get('extra_config', {}),
    )
    conn = DatabaseConnection(
        type=data.get('type'),
        deployment_mode=dm,
        host=data.get('host'),
        port=data.get('port'),
        user=data.get('user'),
        password=data.get('password'),
        database=data.get('database'),
        extra_config=extra,
    )
    try:
        engine = DBEngineFactory.get_engine(conn)
        ok, msg = engine.test()
        return Response({"ok": ok, "msg": msg})
    except Exception as e:
        return Response({"ok": False, "msg": str(e)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_saved_connection(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    try:
        engine = DBEngineFactory.get_engine(conn)
        ok, msg = engine.test()
        return Response({"ok": ok, "msg": msg})
    except Exception as e:
        return Response({"ok": False, "msg": str(e)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_structure(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    try:
        engine = DBEngineFactory.get_engine(conn)
        tree = engine.get_structure()
        return Response(tree)
    except Exception as e:
        return Response({"error": str(e)}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def execute_query(request, pk):
    conn = get_object_or_404(DatabaseConnection, pk=pk)
    db = request.data.get('db')
    target = request.data.get('target')
    params = request.data.get('params', {})

    if is_readonly(request.user):
        if conn.type == 'mysql':
            sql = params.get('sql', '').strip().upper()
            allowed_prefixes = ('SELECT', 'SHOW', 'EXPLAIN', 'DESC', 'DESCRIBE')
            if sql and not sql.startswith(allowed_prefixes):
                return Response({"error": "Read-only Access: Only SELECT queries are allowed."}, status=403)
        elif conn.type == 'redis':
            command = params.get('command', '').strip().upper()
            if command:
                cmd_root = command.split()[0]
                safe_cmds = (
                    'GET', 'HGET', 'HGETALL', 'HMGET', 'LINDEX', 'LLEN', 'LRANGE',
                    'SCARD', 'SISMEMBER', 'SMEMBERS', 'SRANDMEMBER', 'ZCARD', 'ZCOUNT',
                    'ZRANGE', 'ZRANK', 'ZSCORE', 'TYPE', 'TTL', 'PTTL', 'EXISTS',
                    'STRLEN', 'KEYS', 'SCAN', 'HSCAN', 'SSCAN', 'ZSCAN', 'INFO', 'DBSIZE',
                    'PING', 'ECHO'
                )
                if cmd_root not in safe_cmds:
                    return Response({"error": f"Read-only Access: Command '{cmd_root}' is not allowed."}, status=403)

    try:
        engine = DBEngineFactory.get_engine(conn)
        result = engine.query(db, target, params)
        return Response(result)
    except Exception as e:
        return Response({"error": str(e)}, status=400)


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def instance_list(request):
    if request.method == 'GET':
        qs = filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")
        db_type = request.query_params.get("db_type")
        environment = request.query_params.get("environment")
        keyword = request.query_params.get("keyword")
        if db_type:
            qs = qs.filter(db_type=db_type)
        if environment:
            qs = qs.filter(environment=environment)
        if keyword:
            qs = qs.filter(Q(name__icontains=keyword) | Q(host__icontains=keyword))
        return Response([serialize_instance(item) for item in qs.order_by("-updated_at", "-created_at")])

    serializer = DBInstanceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    instance = upsert_instance(serializer.validated_data, request.user)
    return Response(serialize_instance(instance), status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRolePermission])
def instance_detail(request, pk):
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="view"), pk=pk)
    if request.method == 'GET':
        return Response(serialize_instance(instance))
    if request.method == 'DELETE':
        instance.delete()
        return Response({"msg": "deleted"})
    serializer = DBInstanceSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    payload["id"] = instance.id
    instance = upsert_instance(payload, request.user)
    return Response(serialize_instance(instance))


@api_view(['POST'])
@permission_classes([HasRolePermission])
def instance_test(request, pk):
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="view"), pk=pk)
    ok, message = test_instance(instance)
    return Response({"ok": ok, "msg": message, "instance": serialize_instance(instance)})


@api_view(['GET'])
@permission_classes([HasRolePermission])
def instance_schema(request, pk):
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="view"), pk=pk)
    ensure_instance_access(request.user, instance, action="view", database_name=request.query_params.get("database", ""))
    return Response(get_schema(instance))


@api_view(['GET'])
@permission_classes([HasRolePermission])
def instance_table_detail(request, pk):
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="view"), pk=pk)
    database_name = request.query_params.get("database") or instance.default_database
    table_name = request.query_params.get("table") or ""
    if not table_name:
        return Response({"error": "table is required"}, status=400)
    ensure_instance_access(request.user, instance, action="view", database_name=database_name, sql=f"SELECT * FROM {table_name}")
    return Response(get_table_detail(instance, database_name, table_name))


@api_view(['POST'])
@permission_classes([HasRolePermission])
def sql_format(request):
    serializer = SQLFormatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return Response({"formatted_sql": sqlparse.format(serializer.validated_data["sql"], reindent=True, keyword_case="upper")})


@api_view(['POST'])
@permission_classes([HasRolePermission])
def sql_explain(request):
    serializer = SQLExecuteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="query"), pk=serializer.validated_data["instance_id"])
    ensure_instance_access(request.user, instance, action="query", database_name=serializer.validated_data.get("database", ""), sql=serializer.validated_data["sql"])
    result = explain_sql(instance, serializer.validated_data.get("database", ""), serializer.validated_data["sql"])
    return Response(result)


@api_view(['POST'])
@permission_classes([HasRolePermission])
def sql_job_create(request):
    serializer = SQLExecuteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="query"), pk=serializer.validated_data["instance_id"])
    try:
        job, report, order = create_execution_job(
            instance=instance,
            user=request.user,
            database_name=serializer.validated_data.get("database", ""),
            sql=serializer.validated_data["sql"],
            execute_mode=serializer.validated_data.get("execute_mode", ""),
            request_meta=_request_meta(request),
            applicant_user_id=serializer.validated_data.get("applicant_user_id"),
            approval_reason=request.data.get("approval_reason", ""),
            cc_user_ids=request.data.get("cc_user_ids", []),
            approval_flow=request.data.get("approval_flow", []),
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)
    matched_execution_policy = matching_execution_policy(instance, serializer.validated_data.get("database", ""), serializer.validated_data["sql"], report=report)
    return Response({
        "job": SQLExecutionJobSerializer(job).data,
        "report": report,
        "recommended_execute_mode": job.execute_mode,
        "required_permission": recommend_permission_codename(serializer.validated_data["sql"], report=report),
        "execution_policy": serialize_execution_policy(matched_execution_policy) if matched_execution_policy else None,
        "approval_order_id": order.id if order else None,
    }, status=201)


@api_view(['GET'])
@permission_classes([HasRolePermission])
def sql_job_list(request):
    qs = SQLExecutionJob.objects.select_related("instance", "user").filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view"))
    status_value = request.query_params.get("status")
    instance_id = request.query_params.get("instance_id")
    if status_value:
        qs = qs.filter(status=status_value)
    if instance_id:
        qs = qs.filter(instance_id=instance_id)
    return Response(SQLExecutionJobSerializer(qs.order_by("-created_at")[:100], many=True).data)


@api_view(['GET'])
@permission_classes([HasRolePermission])
def sql_job_detail(request, pk):
    job = get_object_or_404(SQLExecutionJob.objects.select_related("instance", "user").filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")), pk=pk)
    payload = SQLExecutionJobSerializer(job).data
    payload["ai_review"] = SQLAIReview.objects.filter(job=job).values().first()
    payload["result"] = getattr(job, "result", None) and {
        "result_type": job.result.result_type,
        "columns_json": job.result.columns_json,
        "rows_json": job.result.rows_json,
        "total_rows": job.result.total_rows,
        "preview_rows": job.result.preview_rows,
        "execution_stats_json": job.result.execution_stats_json,
    }
    return Response(payload)


@api_view(['GET'])
@permission_classes([HasRolePermission])
def sql_job_logs(request, pk):
    job = get_object_or_404(SQLExecutionJob.objects.filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")), pk=pk)
    return Response(list(job.logs.values("seq", "level", "message", "created_at")))


@api_view(['GET'])
@permission_classes([HasRolePermission])
def sql_job_result(request, pk):
    job = get_object_or_404(SQLExecutionJob.objects.filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")), pk=pk)
    if not hasattr(job, "result"):
        return Response({"error": "result not ready"}, status=404)
    result = job.result
    return Response({
        "result_type": result.result_type,
        "columns_json": result.columns_json,
        "rows_json": result.rows_json,
        "total_rows": result.total_rows,
        "preview_rows": result.preview_rows,
        "warnings_json": result.warnings_json,
        "execution_stats_json": result.execution_stats_json,
    })


@api_view(['POST'])
@permission_classes([HasRolePermission])
def sql_job_cancel(request, pk):
    job = get_object_or_404(SQLExecutionJob.objects.filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")), pk=pk)
    cancel_job(job)
    return Response({"msg": "cancelled", "job": SQLExecutionJobSerializer(job).data})


@api_view(['POST'])
@permission_classes([HasRolePermission])
def sql_job_pause(request, pk):
    job = get_object_or_404(SQLExecutionJob.objects.filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")), pk=pk)
    pause_job(job)
    return Response({"msg": "pause requested", "job": SQLExecutionJobSerializer(job).data})


@api_view(['POST'])
@permission_classes([HasRolePermission])
def sql_job_resume(request, pk):
    job = get_object_or_404(SQLExecutionJob.objects.filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")), pk=pk)
    resume_job(job, request_meta=_request_meta(request))
    return Response({"msg": "resumed", "job": SQLExecutionJobSerializer(job).data})


@api_view(['GET'])
@permission_classes([HasRolePermission])
def approval_list(request):
    qs = SQLApprovalOrder.objects.select_related("job", "applicant").filter(job__instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="approve")).order_by("-submitted_at")
    return Response([
        {
            "id": item.id,
            "job_id": item.job_id,
            "job_status": item.job.status,
            "applicant": item.applicant.username,
            "status": item.status,
            "reason": item.reason,
            "cc_users": item.cc_users_json,
            "requested_flow": item.requested_flow_json,
            "request_payload": item.request_payload_json,
            "current_node": item.current_node,
            "pending_steps": list(item.steps.filter(action="pending").values("step_no", "approver_role", "comment")),
            "overdue": approval_is_overdue(item),
            "submitted_at": item.submitted_at,
            "approved_at": item.approved_at,
            "rejected_at": item.rejected_at,
        }
        for item in qs[:100]
    ])


@api_view(['GET'])
@permission_classes([HasRolePermission])
def approval_detail(request, pk):
    order = get_object_or_404(SQLApprovalOrder.objects.select_related("job", "applicant").filter(job__instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="approve")), pk=pk)
    return Response({
        "id": order.id,
        "job": SQLExecutionJobSerializer(order.job).data,
        "applicant": order.applicant.username,
        "status": order.status,
        "reason": order.reason,
        "cc_users": order.cc_users_json,
        "requested_flow": order.requested_flow_json,
        "request_payload": order.request_payload_json,
        "submitted_at": order.submitted_at,
        "approved_at": order.approved_at,
        "rejected_at": order.rejected_at,
        "overdue": approval_is_overdue(order),
        "steps": list(order.steps.values("step_no", "approver_role", "action", "comment", "acted_at")),
        "ai_review": SQLAIReview.objects.filter(job=order.job).values().first(),
    })


@api_view(['POST'])
@permission_classes([HasRolePermission])
def approval_approve(request, pk):
    order = get_object_or_404(SQLApprovalOrder.objects.select_related("job").filter(job__instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="approve")), pk=pk)
    approve_order(order, request.user, request_meta=_request_meta(request))
    return Response({"msg": "approved"})


@api_view(['POST'])
@permission_classes([HasRolePermission])
def approval_reject(request, pk):
    order = get_object_or_404(SQLApprovalOrder.objects.select_related("job").filter(job__instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="approve")), pk=pk)
    reject_order(order, request.user, request.data.get("comment", ""))
    return Response({"msg": "rejected"})


@api_view(['POST'])
@permission_classes([HasRolePermission])
def approval_remind(request, pk):
    order = get_object_or_404(SQLApprovalOrder.objects.select_related("job").filter(job__instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="approve")), pk=pk)
    remind_approval(order, request.user)
    return Response({"msg": "reminded"})


@api_view(['GET'])
@permission_classes([HasRolePermission])
def audit_list(request):
    qs = SQLAuditLog.objects.select_related("instance", "user").filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")).order_by("-created_at")
    instance_id = request.query_params.get("instance_id")
    success = request.query_params.get("success")
    if instance_id:
        qs = qs.filter(instance_id=instance_id)
    if success in ("true", "false"):
        qs = qs.filter(success=(success == "true"))
    return Response([
        {
            "id": item.id,
            "job_id": item.job_id,
            "instance_name": item.instance.name,
            "username": item.user.username,
            "database_name": item.database_name,
            "sql_type": item.sql_type,
            "risk_level": item.risk_level,
            "affected_rows": item.affected_rows,
            "duration_ms": item.duration_ms,
            "success": item.success,
            "created_at": item.created_at,
        }
        for item in qs[:200]
    ])


@api_view(['GET'])
@permission_classes([HasRolePermission])
def audit_detail(request, pk):
    audit = get_object_or_404(SQLAuditLog.objects.select_related("instance", "user").filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")), pk=pk)
    return Response({
        "id": audit.id,
        "job_id": audit.job_id,
        "username": audit.user.username,
        "instance_name": audit.instance.name,
        "database_name": audit.database_name,
        "sql_text": audit.sql_text,
        "normalized_sql": audit.normalized_sql,
        "sql_type": audit.sql_type,
        "table_names_json": audit.table_names_json,
        "affected_rows": audit.affected_rows,
        "duration_ms": audit.duration_ms,
        "risk_level": audit.risk_level,
        "success": audit.success,
        "client_ip": audit.client_ip,
        "user_agent": audit.user_agent,
        "trace_id": audit.trace_id,
        "created_at": audit.created_at,
    })


@api_view(['GET'])
@permission_classes([HasRolePermission])
def audit_export(request):
    qs = SQLAuditLog.objects.select_related("instance", "user").filter(
        instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="view")
    ).order_by("-created_at")
    instance_id = request.query_params.get("instance_id")
    success = request.query_params.get("success")
    if instance_id:
        qs = qs.filter(instance_id=instance_id)
    if success in ("true", "false"):
        qs = qs.filter(success=(success == "true"))
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="db_audit_export.csv"'
    response.write('\ufeff')
    writer = csv.DictWriter(response, fieldnames=[
        "id", "job_id", "instance_name", "username", "database_name", "sql_type",
        "risk_level", "affected_rows", "duration_ms", "success", "created_at", "sql_text"
    ])
    writer.writeheader()
    for row in export_audit_rows(qs[:2000]):
        writer.writerow(row)
    return response


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def approval_policy_list(request):
    if request.method == 'GET':
        qs = SQLApprovalPolicy.objects.order_by('-updated_at', '-created_at')
        return Response(SQLApprovalPolicySerializer(qs, many=True).data)
    serializer = SQLApprovalPolicySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    policy = serializer.save()
    return Response(SQLApprovalPolicySerializer(policy).data, status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRolePermission])
def approval_policy_detail(request, pk):
    policy = get_object_or_404(SQLApprovalPolicy, pk=pk)
    if request.method == 'GET':
        return Response(SQLApprovalPolicySerializer(policy).data)
    if request.method == 'DELETE':
        policy.delete()
        return Response({"msg": "deleted"})
    serializer = SQLApprovalPolicySerializer(policy, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def backup_plan_list(request):
    if request.method == 'GET':
        plans = BackupPlan.objects.select_related('instance').filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")).order_by('-updated_at', '-created_at')
        return Response([serialize_backup_plan(plan) for plan in plans])
    serializer = BackupPlanSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup"), pk=serializer.validated_data["instance"].id if isinstance(serializer.validated_data["instance"], DBInstance) else serializer.validated_data["instance"])
    plan = upsert_backup_plan(serializer.validated_data, request.user)
    plan.instance = instance
    plan.save(update_fields=["instance", "updated_at"])
    return Response(serialize_backup_plan(plan), status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRolePermission])
def backup_plan_detail(request, pk):
    plan = get_object_or_404(BackupPlan.objects.select_related('instance').filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")), pk=pk)
    if request.method == 'GET':
        return Response(serialize_backup_plan(plan))
    if request.method == 'DELETE':
        plan.delete()
        return Response({"msg": "deleted"})
    serializer = BackupPlanSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    payload["id"] = plan.id
    plan = upsert_backup_plan(payload, request.user)
    return Response(serialize_backup_plan(plan))


@api_view(['POST'])
@permission_classes([HasRolePermission])
def backup_plan_run(request, pk):
    plan = get_object_or_404(BackupPlan.objects.select_related('instance').filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")), pk=pk)
    record = run_backup_plan(plan)
    return Response(BackupRecordSerializer(record).data)


@api_view(['GET'])
@permission_classes([HasRolePermission])
def backup_record_list(request):
    qs = BackupRecord.objects.select_related('instance', 'plan').filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")).order_by('-created_at')
    instance_id = request.query_params.get("instance_id")
    if instance_id:
        qs = qs.filter(instance_id=instance_id)
    return Response(BackupRecordSerializer(qs[:200], many=True).data)


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def restore_job_list(request):
    if request.method == 'GET':
        qs = RestoreJob.objects.select_related('instance', 'backup_record').filter(instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")).order_by('-created_at')
        return Response(RestoreJobSerializer(qs[:200], many=True).data)
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup"), pk=request.data.get("instance"))
    job = create_restore_job(
        instance_id=instance.id,
        backup_record_id=request.data.get("backup_record"),
        restore_mode=request.data.get("restore_mode", "backup"),
        target_time=request.data.get("target_time"),
        target_txn_id=request.data.get("target_txn_id", ""),
        user=request.user,
    )
    return Response(RestoreJobSerializer(job).data, status=201)


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def rollback_job_list(request):
    if request.method == 'GET':
        qs = RollbackJob.objects.select_related('instance', 'source_audit').filter(
            instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")
        ).order_by('-created_at')
        return Response([serialize_rollback_job(item) for item in qs[:200]])
    audit_id = request.data.get("source_audit")
    audit = None
    instance = None
    if audit_id:
        audit = get_object_or_404(
            SQLAuditLog.objects.select_related("instance").filter(
                instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")
            ),
            pk=audit_id
        )
        instance = audit.instance
    else:
        instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup"), pk=request.data.get("instance"))
    job = create_rollback_job(instance=instance, user=request.user, audit=audit, source_txn_id=request.data.get("source_txn_id", ""))
    return Response(serialize_rollback_job(job), status=201)


@api_view(['POST'])
@permission_classes([HasRolePermission])
def rollback_job_execute(request, pk):
    job = get_object_or_404(RollbackJob.objects.select_related('instance').filter(
        instance__in=filter_accessible_instances(request.user, DBInstance.objects.all(), action="backup")
    ), pk=pk)
    execute_rollback_job(job)
    return Response({"msg": "rollback started", "job": serialize_rollback_job(job)})


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def access_rule_list(request):
    if request.method == 'GET':
        qs = DBAccessRule.objects.select_related('instance', 'user').order_by('-updated_at', '-created_at')
        return Response([serialize_access_rule(item) for item in qs])
    rule = upsert_access_rule(request.data)
    return Response(serialize_access_rule(rule), status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRolePermission])
def access_rule_detail(request, pk):
    rule = get_object_or_404(DBAccessRule.objects.select_related('instance', 'user'), pk=pk)
    if request.method == 'GET':
        return Response(serialize_access_rule(rule))
    if request.method == 'DELETE':
        rule.delete()
        return Response({"msg": "deleted"})
    payload = dict(request.data)
    payload["id"] = rule.id
    rule = upsert_access_rule(payload)
    return Response(serialize_access_rule(rule))


@api_view(['POST'])
@permission_classes([HasRolePermission])
def access_rule_preview(request):
    instance = get_object_or_404(DBInstance, pk=request.data.get("instance_id"))
    result = explain_access_preview(
        user_id=request.data.get("user_id"),
        group_name=request.data.get("group_name", ""),
        instance=instance,
        database_name=request.data.get("database", ""),
        sql=request.data.get("sql", ""),
    )
    return Response(result)


@api_view(['GET', 'POST'])
@permission_classes([HasRolePermission])
def execution_policy_list(request):
    if request.method == 'GET':
        qs = SQLExecutionPolicy.objects.order_by('priority', '-updated_at', '-created_at')
        return Response([serialize_execution_policy(item) for item in qs])
    serializer = SQLExecutionPolicySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    policy = upsert_execution_policy(serializer.validated_data)
    return Response(serialize_execution_policy(policy), status=201)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([HasRolePermission])
def execution_policy_detail(request, pk):
    policy = get_object_or_404(SQLExecutionPolicy, pk=pk)
    if request.method == 'GET':
        return Response(serialize_execution_policy(policy))
    if request.method == 'DELETE':
        policy.delete()
        return Response({"msg": "deleted"})
    serializer = SQLExecutionPolicySerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    payload["id"] = policy.id
    policy = upsert_execution_policy(payload)
    return Response(serialize_execution_policy(policy))


@api_view(['GET'])
@permission_classes([HasRolePermission])
def permission_subjects(request):
    from django.contrib.auth.models import Group, User

    users = User.objects.all().prefetch_related('groups')
    roles = Group.objects.all()
    return Response({
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_staff": user.is_staff,
                "groups": [group.name for group in user.groups.all()],
            }
            for user in users
        ],
        "roles": [
            {
                "id": role.id,
                "name": role.name,
            }
            for role in roles
        ],
    })


@api_view(['GET'])
@permission_classes([HasRolePermission])
def sql_completion(request):
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="query"), pk=request.query_params.get("instance_id"))
    engine = DBEngineFactory.get_engine(instance)
    keyword = request.query_params.get("keyword", "")
    database_name = request.query_params.get("database") or instance.default_database
    suggest_tables = request.query_params.get("suggest_tables", "").strip().lower() in ("1", "true", "yes", "on")
    items = (
        engine.completion_items(database_name, keyword, suggest_tables=suggest_tables)
        if hasattr(engine, "completion_items")
        else []
    )
    return Response({"items": items[:400]})


@api_view(['GET'])
@permission_classes([HasRolePermission])
def approval_applicant_list(request):
    return Response({"users": list_approval_applicants()})


@api_view(['GET'])
@permission_classes([HasRolePermission])
def instance_diagnostics(request, pk):
    instance = get_object_or_404(filter_accessible_instances(request.user, DBInstance.objects.all(), action="view"), pk=pk)
    report = run_instance_diagnostics(instance)
    return Response(report)

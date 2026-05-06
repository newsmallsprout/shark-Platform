import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
import gzip
import base64
import tarfile
from datetime import timedelta

import requests
import sqlparse
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from shark_platform.celery import app as celery_app

from .engines import DBEngineFactory
from .models import BackupPlan, BackupRecord, DBAccessRule, DBInstance, DBInstanceSecret, RestoreJob, RollbackJob, SQLAIReview, SQLApprovalOrder, SQLApprovalPolicy, SQLApprovalStep, SQLAuditLog, SQLExecutionJob, SQLExecutionLog, SQLExecutionPolicy, SQLExecutionResult


JOB_THREADS = {}
JOB_LOCK = threading.Lock()
BACKUP_THREADS = {}
RESTORE_THREADS = {}
ROLLBACK_THREADS = {}

try:
    import boto3
except ImportError:
    boto3 = None
try:
    import psycopg2.extras
except ImportError:
    psycopg2 = None


def _normalize_sql(sql: str) -> str:
    return sqlparse.format(sql or "", keyword_case="upper", strip_comments=False, reindent=True).strip()


def _hash_sql(sql: str) -> str:
    return hashlib.sha256((sql or "").encode("utf-8")).hexdigest()


def _sql_type(sql: str) -> str:
    parsed = sqlparse.parse(sql or "")
    if not parsed:
        return "UNKNOWN"
    for token in parsed[0].tokens:
        value = str(token).strip()
        if value:
            return value.split()[0].upper()
    return "UNKNOWN"


def _extract_tables(sql: str):
    return sorted(set(re.findall(r'(?:from|join|update|into|table)\s+[`"]?([a-zA-Z0-9_.-]+)', sql or "", re.IGNORECASE)))


def _sql_action(sql: str):
    sql_type = _sql_type(sql)
    if sql_type in {"SELECT", "SHOW", "DESC", "DESCRIBE", "EXPLAIN", "WITH"}:
        return "query"
    if sql_type in {"INSERT", "UPDATE", "DELETE", "MERGE"}:
        return "dml"
    if sql_type in {"ALTER", "DROP", "TRUNCATE", "CREATE", "RENAME"}:
        return "ddl"
    return "query"


def recommend_execute_mode(sql: str):
    return "transaction" if _sql_action(sql) in {"dml", "ddl"} else "auto_commit"


def recommend_permission_codename(sql: str, report=None):
    action = _sql_action(sql)
    risk_level = (report or {}).get("risk_level", "low")
    if risk_level in {"high", "critical"}:
        return "run_sql_high_risk"
    if action == "ddl":
        return "run_sql_ddl"
    if action == "dml":
        return "run_sql_dml"
    return "run_sql_query"


def serialize_execution_policy(policy: SQLExecutionPolicy):
    return {
        "id": policy.id,
        "name": policy.name,
        "priority": policy.priority,
        "environment_scope": policy.environment_scope,
        "db_type_scope": policy.db_type_scope,
        "sql_type_scope": policy.sql_type_scope,
        "risk_scope": policy.risk_scope,
        "database_pattern": policy.database_pattern,
        "auto_execute_mode": policy.auto_execute_mode,
        "require_approval": policy.require_approval,
        "allow_direct_execute": policy.allow_direct_execute,
        "enabled": policy.enabled,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }


def upsert_execution_policy(data):
    policy_id = data.get("id")
    policy = SQLExecutionPolicy.objects.filter(id=policy_id).first() if policy_id else None
    if policy is None:
        policy = SQLExecutionPolicy()
    for field in [
        "name", "priority", "environment_scope", "db_type_scope", "sql_type_scope",
        "risk_scope", "database_pattern", "auto_execute_mode", "require_approval",
        "allow_direct_execute", "enabled"
    ]:
        if field in data:
            setattr(policy, field, data.get(field))
    policy.save()
    return policy


def _permission_codenames(user):
    permissions = set()
    for item in user.get_all_permissions():
        permissions.add(item.split(".")[-1])
    return permissions


def is_db_admin_or_dba(user):
    if not user:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if user.groups.filter(name__in=["Admin", "DBA"]).exists():
        return True
    return "approve_sql_execution" in _permission_codenames(user)


def list_approval_applicants():
    users = User.objects.all().prefetch_related("groups")
    result = []
    for user in users:
        if not is_db_admin_or_dba(user):
            continue
        result.append({
            "id": user.id,
            "username": user.username,
            "is_staff": user.is_staff,
            "groups": [group.name for group in user.groups.all()],
        })
    return result


def resolve_applicant(applicant_user_id, fallback_user):
    if applicant_user_id:
        applicant = User.objects.filter(id=applicant_user_id).first()
        if not applicant:
            raise ValueError("申请人不存在")
        if not is_db_admin_or_dba(applicant):
            raise ValueError("申请人必须具备管理员或 DBA 权限")
        return applicant
    if not is_db_admin_or_dba(fallback_user):
        raise ValueError("当前用户不具备管理员或 DBA 权限，无法作为申请人")
    return fallback_user


def _backup_root():
    return Path(getattr(settings, "BASE_DIR", Path.cwd())) / "runtime" / "db_backups"


def _trace_id(request_meta=None):
    return (request_meta or {}).get("trace_id") or uuid.uuid4().hex


def _cipher():
    key = base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY or "shark-platform").encode("utf-8")).digest())
    return Fernet(key)


def _storage_client(storage_config):
    if not boto3:
        return None
    if not storage_config or not storage_config.get("bucket"):
        return None
    endpoint = storage_config.get("endpoint")
    if endpoint and ('s3.amazonaws.com' in endpoint or endpoint.strip() == ''):
        endpoint = None
    return boto3.client(
        "s3",
        region_name=storage_config.get("region"),
        aws_access_key_id=storage_config.get("access_key"),
        aws_secret_access_key=storage_config.get("secret_key"),
        endpoint_url=endpoint or None,
    )


def _compress_file(path: Path):
    gz_path = path.with_suffix(path.suffix + ".gz")
    with open(path, "rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    path.unlink(missing_ok=True)
    return gz_path


def _encrypt_file(path: Path):
    encrypted = path.with_suffix(path.suffix + ".enc")
    encrypted.write_bytes(_cipher().encrypt(path.read_bytes()))
    path.unlink(missing_ok=True)
    return encrypted


def _download_from_object_storage(record: BackupRecord):
    metadata = record.metadata_json or {}
    object_key = metadata.get("object_key")
    storage_config = getattr(getattr(record, "plan", None), "storage_config", None) or {}
    client = _storage_client(storage_config)
    if not client or not object_key or not storage_config.get("bucket"):
        return None
    local_dir = _backup_root() / "downloaded" / record.instance.name
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / Path(object_key).name
    client.download_file(storage_config["bucket"], object_key, str(local_path))
    return local_path


def _sha256_file(path: Path):
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_restore_file(record: BackupRecord):
    file_path = Path(record.file_uri or "")
    if (not record.file_uri or not file_path.exists()) and record.plan_id:
        downloaded = _download_from_object_storage(record)
        if downloaded:
            file_path = downloaded
    if not file_path.exists():
        raise RuntimeError("缺少可用备份文件")
    if file_path.suffix == ".enc":
        decrypted = file_path.with_suffix("")
        decrypted.write_bytes(_cipher().decrypt(file_path.read_bytes()))
        file_path = decrypted
    if file_path.suffix == ".gz":
        extracted = file_path.with_suffix("")
        with gzip.open(file_path, "rb") as src, open(extracted, "wb") as dst:
            shutil.copyfileobj(src, dst)
        file_path = extracted
    return file_path


def _cleanup_local_backups(plan: BackupPlan):
    if not plan.retention_days:
        return
    expire_before = timezone.now() - timedelta(days=plan.retention_days)
    stale = plan.records.filter(created_at__lt=expire_before)
    for record in stale:
        try:
            if record.file_uri:
                Path(record.file_uri).unlink(missing_ok=True)
        except Exception:
            pass


def _cleanup_s3_backups(plan: BackupPlan):
    storage_config = plan.storage_config or {}
    client = _storage_client(storage_config)
    if not client or not plan.retention_days:
        return
    expire_before = timezone.now() - timedelta(days=plan.retention_days)
    stale = plan.records.filter(created_at__lt=expire_before)
    bucket = storage_config.get("bucket")
    for record in stale:
        key = (record.metadata_json or {}).get("object_key")
        if not key:
            continue
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            pass


def _should_use_celery():
    """配置了 Broker 即走 Celery；若 Worker 未启动作业会一直 queued。
    可设环境变量 DB_MANAGER_USE_THREAD_EXECUTOR=1 强制用进程内线程执行 SQL。"""
    if os.environ.get("DB_MANAGER_USE_THREAD_EXECUTOR", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    return bool(getattr(settings, "CELERY_BROKER_URL", "") or os.environ.get("CELERY_BROKER_URL"))


def _match_pattern(value: str, pattern: str) -> bool:
    if not pattern or pattern == "*":
        return True
    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    return re.match(regex, value or "") is not None


def _user_rule_matches(rule: DBAccessRule, user) -> bool:
    if rule.user_id and rule.user_id == user.id:
        return True
    if rule.group_name and user.groups.filter(name=rule.group_name).exists():
        return True
    return False


def _rule_allows(rule: DBAccessRule, action: str, instance: DBInstance, database_name: str = "", table_names=None, sql_type: str = "") -> bool:
    if not rule.enabled:
        return False
    if rule.instance_id and rule.instance_id != instance.id:
        return False
    if action not in (rule.actions or []):
        return False
    if database_name and not _match_pattern(database_name, rule.database_pattern or "*"):
        return False
    if sql_type and rule.sql_types and sql_type not in rule.sql_types:
        return False
    for table_name in table_names or []:
        short_name = table_name.split(".")[-1]
        if not _match_pattern(short_name, rule.table_pattern or "*") and not _match_pattern(table_name, rule.table_pattern or "*"):
            return False
    return True


def filter_accessible_instances(user, queryset=None, action: str = "view"):
    queryset = queryset or DBInstance.objects.all()
    if user.is_superuser or user.is_staff:
        return queryset
    rules = list(DBAccessRule.objects.filter(enabled=True))
    allowed_ids = set()
    for rule in rules:
        if not _user_rule_matches(rule, user):
            continue
        if action not in (rule.actions or []):
            continue
        if rule.instance_id:
            allowed_ids.add(rule.instance_id)
        else:
            allowed_ids.update(queryset.values_list("id", flat=True))
    return queryset.filter(id__in=allowed_ids)


def ensure_instance_access(user, instance: DBInstance, action: str = "view", database_name: str = "", sql: str = ""):
    if user.is_superuser or user.is_staff:
        return
    sql_type = _sql_type(sql) if sql else ""
    table_names = _extract_tables(sql) if sql else []
    rules = DBAccessRule.objects.filter(enabled=True)
    for rule in rules:
        if not _user_rule_matches(rule, user):
            continue
        if _rule_allows(rule, action=action, instance=instance, database_name=database_name, table_names=table_names, sql_type=sql_type):
            return
    raise PermissionError("当前用户没有该实例或对象范围的操作权限")


def explain_access_preview(user_id=None, group_name="", instance=None, database_name="", sql=""):
    sql_type = _sql_type(sql)
    action = _sql_action(sql)
    matched = []
    conflicts = []
    table_names = _extract_tables(sql)
    rules = DBAccessRule.objects.filter(enabled=True).select_related("instance", "user")
    for rule in rules:
        subject_ok = False
        if user_id and rule.user_id == user_id:
            subject_ok = True
        if group_name and rule.group_name == group_name:
            subject_ok = True
        if not user_id and not group_name:
            subject_ok = True
        if not subject_ok:
            continue
        if _rule_allows(rule, action=action, instance=instance, database_name=database_name, table_names=table_names, sql_type=sql_type):
            matched.append(serialize_access_rule(rule))
        elif set(rule.actions or []).intersection([action]):
            conflicts.append(rule.name)
    return {
        "action": action,
        "sql_type": sql_type,
        "matched_rules": matched,
        "conflicts": conflicts[:10],
        "allowed": bool(matched),
    }


def serialize_instance(instance: DBInstance):
    return {
        "id": instance.id,
        "name": instance.name,
        "db_type": instance.db_type,
        "deployment_mode": instance.deployment_mode,
        "environment": instance.environment,
        "host": instance.host,
        "port": instance.port,
        "default_database": instance.default_database,
        "read_only": instance.read_only,
        "owner_team": instance.owner_team,
        "tags": instance.tags,
        "extra_config": instance.extra_config,
        "status": instance.status,
        "last_health_check_at": instance.last_health_check_at,
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
        "username": getattr(getattr(instance, "secret", None), "username", ""),
        "password_set": bool(getattr(getattr(instance, "secret", None), "password_encrypted", "")),
    }


def upsert_instance(data, user):
    instance_id = data.get("id")
    instance = DBInstance.objects.filter(id=instance_id).first() if instance_id else None
    if instance is None:
        instance = DBInstance(created_by=user)

    for field in ["name", "db_type", "deployment_mode", "environment", "host", "port", "default_database", "read_only", "owner_team", "tags", "extra_config"]:
        if field in data:
            setattr(instance, field, data.get(field))
    if instance.db_type == "redis":
        extra = dict(instance.extra_config or {})
        extra["mode"] = "cluster" if instance.deployment_mode == "cluster" else "standalone"
        instance.extra_config = extra
    instance.save()

    secret = getattr(instance, "secret", None)
    if secret is None:
        secret = DBInstanceSecret(instance=instance)
    if "username" in data:
        secret.username = data.get("username") or ""
    if "password" in data and data.get("password") not in (None, ""):
        secret.set_password(data.get("password") or "")
    secret.save()
    return instance


def test_instance(instance: DBInstance):
    engine = DBEngineFactory.get_engine(instance)
    ok, message = engine.test()
    instance.status = "online" if ok else "error"
    instance.last_health_check_at = timezone.now()
    instance.save(update_fields=["status", "last_health_check_at", "updated_at"])
    return ok, message


def get_schema(instance: DBInstance):
    engine = DBEngineFactory.get_engine(instance)
    return engine.get_structure()


def get_table_detail(instance: DBInstance, database_name: str, table_name: str):
    engine = DBEngineFactory.get_engine(instance)
    if instance.db_type == "mysql":
        result = engine.query(database_name, table_name, {"page": 1, "pageSize": 20})
        return {"columns": result.get("headers", []), "sample_rows": result.get("rows", []), "total": result.get("total", 0)}
    if instance.db_type == "postgresql":
        result = engine.query(database_name, table_name, {"page": 1, "pageSize": 20})
        return {"columns": result.get("headers", []), "sample_rows": result.get("rows", []), "total": result.get("total", 0)}
    return {"columns": [], "sample_rows": [], "total": 0}


def explain_sql(instance: DBInstance, database_name: str, sql: str):
    engine = DBEngineFactory.get_engine(instance)
    if hasattr(engine, "explain") and instance.db_type in ("mysql", "postgresql"):
        return engine.explain(database_name or instance.default_database, sql)
    return {"headers": [], "rows": [], "total": 0}


def _heuristic_review(instance: DBInstance, sql: str, explain_result):
    normalized = _normalize_sql(sql)
    sql_type = _sql_type(normalized)
    findings_security = []
    findings_performance = []
    findings_permission = []
    suggestions = []
    blocking = []
    decision = "allow"
    risk_level = "low"

    lowered = normalized.lower()
    if sql_type in {"UPDATE", "DELETE"} and " where " not in f" {lowered} ":
        findings_security.append("检测到无 WHERE 的更新或删除语句。")
        blocking.append("禁止执行无 WHERE 的 UPDATE/DELETE。")
        decision = "block"
        risk_level = "critical"
    if sql_type in {"DROP", "TRUNCATE"}:
        findings_security.append("检测到高危破坏性 SQL。")
        blocking.append("生产环境建议走审批并在备份后执行。")
        decision = "block"
        risk_level = "critical"
    if sql_type == "ALTER":
        findings_performance.append("DDL 可能触发表锁或长时间元数据锁。")
        suggestions.append("建议评估在线 DDL 或维护窗口执行。")
        decision = "warn" if decision == "allow" else decision
        risk_level = "high" if risk_level in ("low", "medium") else risk_level
    if "select *" in lowered:
        findings_performance.append("存在 SELECT *，建议按需选择字段。")
        suggestions.append("减少返回字段，降低网络与排序成本。")
        if decision == "allow":
            decision = "warn"
        if risk_level == "low":
            risk_level = "medium"
    if " join " in lowered and " on " not in lowered:
        findings_security.append("JOIN 缺少明确 ON 条件，可能引发笛卡尔积。")
        if decision == "allow":
            decision = "warn"
        if risk_level == "low":
            risk_level = "medium"
    if instance.read_only and sql_type not in {"SELECT", "SHOW", "DESC", "DESCRIBE", "EXPLAIN"}:
        findings_permission.append("当前实例标记为只读，不允许执行写入类语句。")
        blocking.append("只读实例禁止写操作。")
        decision = "block"
        risk_level = "critical"
    if explain_result.get("rows"):
        findings_performance.append("已生成执行计划，可结合索引命中情况进一步确认。")

    return {
        "sql_type": sql_type,
        "risk_level": risk_level,
        "decision": decision,
        "syntax_ok": True,
        "security_risk_level": "high" if findings_security else "low",
        "performance_risk_level": "high" if findings_performance else "low",
        "permission_risk_level": "high" if findings_permission else "low",
        "sql_summary": f"{instance.db_type.upper()} {sql_type} 语句，涉及 {', '.join(_extract_tables(normalized)) or '未识别对象'}",
        "security_findings": findings_security,
        "performance_findings": findings_performance,
        "permission_findings": findings_permission,
        "optimization_suggestions": suggestions or ["建议先执行 EXPLAIN 并确认索引命中。"],
        "blocking_reasons": blocking,
        "rewrite_sql": normalized,
        "explain_summary": f"执行计划返回 {explain_result.get('total', 0)} 行。",
        "raw_report": {"explain": explain_result},
    }


def sql_precheck_report(instance: DBInstance, database_name: str, sql: str):
    """Rule-based SQL assessment plus optional EXPLAIN (no LLM)."""
    explain_result = {"headers": [], "rows": [], "total": 0}
    sql_type = _sql_type(sql)
    if instance.db_type in ("mysql", "postgresql") and sql_type in {"SELECT", "UPDATE", "DELETE"}:
        try:
            explain_result = explain_sql(instance, database_name, sql)
        except Exception:
            explain_result = {"headers": [], "rows": [], "total": 0}
    return _heuristic_review(instance, sql, explain_result)


def matching_approval_policy(instance: DBInstance, sql: str, report=None):
    sql_type = _sql_type(sql)
    policies = SQLApprovalPolicy.objects.filter(enabled=True)
    for policy in policies:
        if policy.environment_scope and instance.environment not in policy.environment_scope:
            continue
        if policy.db_type_scope and instance.db_type not in policy.db_type_scope:
            continue
        if policy.sql_type_scope and sql_type not in policy.sql_type_scope:
            continue
        if policy.risk_scope and report and report.get("risk_level") not in policy.risk_scope:
            continue
        return policy
    return None


def matching_execution_policy(instance: DBInstance, database_name: str, sql: str, report=None):
    sql_type = _sql_type(sql)
    risk_level = (report or {}).get("risk_level", "low")
    policies = SQLExecutionPolicy.objects.filter(enabled=True).order_by("priority", "-updated_at")
    for policy in policies:
        if policy.environment_scope and instance.environment not in policy.environment_scope:
            continue
        if policy.db_type_scope and instance.db_type not in policy.db_type_scope:
            continue
        if policy.sql_type_scope and sql_type not in policy.sql_type_scope:
            continue
        if policy.risk_scope and risk_level not in policy.risk_scope:
            continue
        if database_name and not _match_pattern(database_name, policy.database_pattern or "*"):
            continue
        return policy
    return None


def need_approval(instance: DBInstance, sql: str, report=None):
    sql_type = _sql_type(sql)
    execution_policy = matching_execution_policy(instance, instance.default_database, sql, report=report)
    if execution_policy and execution_policy.require_approval:
        return True
    policy = matching_approval_policy(instance, sql, report=report)
    if policy:
        return True
    if instance.environment == "prod" and sql_type in {"ALTER", "DROP", "TRUNCATE", "UPDATE", "DELETE", "INSERT"}:
        return True
    if report and report.get("risk_level") in {"high", "critical"}:
        return True
    if report and report.get("decision") == "warn":
        return True
    return False


def append_job_log(job: SQLExecutionJob, message: str, level: str = "info"):
    seq = (job.logs.order_by("-seq").first().seq + 1) if job.logs.exists() else 1
    SQLExecutionLog.objects.create(job=job, seq=seq, level=level, message=message)


def _write_audit(job: SQLExecutionJob, request_meta=None, before_image=None, after_image=None, txn_snapshot=None):
    SQLAuditLog.objects.update_or_create(
        job=job,
        defaults={
            "user": job.user,
            "instance": job.instance,
            "database_name": job.database_name,
            "sql_text": job.sql_text,
            "normalized_sql": _normalize_sql(job.sql_text),
            "sql_type": job.sql_type,
            "table_names_json": _extract_tables(job.sql_text),
            "affected_rows": job.affected_rows,
            "duration_ms": job.duration_ms,
            "risk_level": job.risk_level,
            "before_image_json": before_image or [],
            "after_image_json": after_image or [],
            "txn_snapshot_json": txn_snapshot or {},
            "success": job.status == "success",
            "client_ip": (request_meta or {}).get("client_ip"),
            "user_agent": (request_meta or {}).get("user_agent", ""),
            "trace_id": job.trace_id or (request_meta or {}).get("trace_id", ""),
        },
    )


def _run_sql_job(job_id: int, request_meta=None):
    job = SQLExecutionJob.objects.select_related("instance", "user").get(id=job_id)
    started = time.time()
    engine = DBEngineFactory.get_engine(job.instance)
    job.status = "running"
    job.progress_percent = 10
    job.started_at = timezone.now()
    job.save(update_fields=["status", "progress_percent", "started_at", "updated_at"])
    append_job_log(job, f"[trace:{job.trace_id}] SQL 作业开始执行")
    job.progress_percent = 18
    job.save(update_fields=["progress_percent", "updated_at"])
    before_image = []
    after_image = []
    txn_snapshot = {"before": _capture_txn_snapshot(job.instance, job.database_name)}
    try:
        if job.execute_mode == "dry_run":
            result = {"headers": [], "rows": [], "affected_rows": 0, "execution_context": {}}
            append_job_log(job, f"[trace:{job.trace_id}] Dry Run 模式未实际执行 SQL")
            job.progress_percent = 80
            job.save(update_fields=["progress_percent", "updated_at"])
        else:
            before_image = _capture_before_image(job.instance, job.database_name, job.sql_text)
            job.progress_percent = 42
            job.save(update_fields=["progress_percent", "updated_at"])
            append_job_log(job, f"[trace:{job.trace_id}] 变更前快照已采集")
            result = engine.execute_sql(job.database_name or job.instance.default_database, job.sql_text)
            job.progress_percent = 72
            job.save(update_fields=["progress_percent", "updated_at"])
            append_job_log(job, f"[trace:{job.trace_id}] SQL 已在数据库执行完毕")
            if job.sql_type == "UPDATE":
                after_image = _capture_before_image(job.instance, job.database_name, f"DELETE FROM {_extract_tables(job.sql_text)[0]} WHERE {_extract_where_clause(job.sql_text)}")
                append_job_log(job, f"[trace:{job.trace_id}] 变更后对比快照已采集")
        txn_snapshot["after"] = _capture_txn_snapshot(job.instance, job.database_name)
        job.progress_percent = 88
        job.save(update_fields=["progress_percent", "updated_at"])
        SQLExecutionResult.objects.update_or_create(
            job=job,
            defaults={
                "result_type": "table",
                "columns_json": result.get("headers", []),
                "rows_json": result.get("rows", [])[:200],
                "total_rows": len(result.get("rows", [])),
                "preview_rows": min(len(result.get("rows", [])), 200),
                "warnings_json": [],
                "execution_stats_json": {"engine": job.instance.db_type},
            },
        )
        job.execution_context = result.get("execution_context", {})
        job.status = "success"
        job.progress_percent = 100
        job.affected_rows = result.get("affected_rows", len(result.get("rows", [])))
        job.duration_ms = int((time.time() - started) * 1000)
        job.finished_at = timezone.now()
        job.save(update_fields=["execution_context", "status", "progress_percent", "affected_rows", "duration_ms", "finished_at", "updated_at"])
        append_job_log(job, f"[trace:{job.trace_id}] SQL 作业执行成功", "success")
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.duration_ms = int((time.time() - started) * 1000)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "duration_ms", "finished_at", "updated_at"])
        append_job_log(job, f"[trace:{job.trace_id}] SQL 作业执行失败: {exc}", "error")
    finally:
        _write_audit(job, request_meta=request_meta, before_image=before_image, after_image=after_image, txn_snapshot=txn_snapshot)
        with JOB_LOCK:
            JOB_THREADS.pop(job.id, None)


def create_execution_job(instance: DBInstance, user, database_name: str, sql: str, execute_mode: str = "", request_meta=None, applicant_user_id=None, approval_reason="", cc_user_ids=None, approval_flow=None):
    action = _sql_action(sql)
    sql_type = _sql_type(sql)
    ensure_instance_access(user, instance, action=action, database_name=database_name or instance.default_database, sql=sql)
    report = sql_precheck_report(instance, database_name, sql)
    execution_policy = matching_execution_policy(instance, database_name or instance.default_database, sql, report=report)
    actual_execute_mode = "dry_run" if execute_mode == "dry_run" else (execution_policy.auto_execute_mode if execution_policy else recommend_execute_mode(sql))
    job = SQLExecutionJob.objects.create(
        instance=instance,
        user=user,
        database_name=database_name or instance.default_database,
        sql_text=sql,
        sql_hash=_hash_sql(sql),
        sql_type=sql_type,
        execute_mode=actual_execute_mode,
        status="queued",
        risk_level=report.get("risk_level", "low"),
        trace_id=_trace_id(request_meta),
    )
    SQLAIReview.objects.update_or_create(
        job=job,
        defaults={
            "model_name": "rules",
            "prompt_version": "db-manager-v1",
            "syntax_ok": report.get("syntax_ok", True),
            "security_risk_level": report.get("security_risk_level", "low"),
            "performance_risk_level": report.get("performance_risk_level", "low"),
            "permission_risk_level": report.get("permission_risk_level", "low"),
            "decision": report.get("decision", "allow"),
            "sql_summary": report.get("sql_summary", ""),
            "explain_summary": report.get("explain_summary", ""),
            "rewrite_sql": report.get("rewrite_sql", ""),
            "optimization_suggestions": report.get("optimization_suggestions", []),
            "blocking_reasons": report.get("blocking_reasons", []),
            "raw_report": report.get("raw_report", {}),
        },
    )
    if report.get("decision") == "block":
        job.status = "failed"
        job.error_message = "规则预审阻断执行"
        job.save(update_fields=["status", "error_message", "updated_at"])
        append_job_log(job, f"[trace:{job.trace_id}] 规则预审阻断执行", "error")
        _write_audit(job, request_meta=request_meta)
        return job, report, None
    matched_policy = matching_approval_policy(instance, sql, report=report)
    must_apply = bool((execution_policy and not execution_policy.allow_direct_execute) or report.get("risk_level") in {"high", "critical"})
    need_apply = must_apply or need_approval(instance, sql, report=report) or bool(matched_policy)
    if need_apply:
        applicant = resolve_applicant(applicant_user_id, user)
        cc_users = []
        for cc_user_id in cc_user_ids or []:
            cc_user = User.objects.filter(id=cc_user_id).first()
            if cc_user:
                cc_users.append({"id": cc_user.id, "username": cc_user.username})
        default_reason = "命中高危 SQL 强制申请策略" if report.get("risk_level") in {"high", "critical"} else ("命中 SQL 执行策略" if execution_policy else "命中审批策略")
        order = SQLApprovalOrder.objects.create(
            job=job,
            applicant=applicant,
            reason=approval_reason or default_reason,
            cc_users_json=cc_users,
            requested_flow_json=approval_flow or [],
            request_payload_json={
                "policy_id": execution_policy.id if execution_policy else None,
                "policy_name": execution_policy.name if execution_policy else "",
                "matched_approval_policy": matched_policy.name if matched_policy else "",
                "allow_direct_execute": False if must_apply else True,
            },
        )
        flow = approval_flow or (matched_policy.approval_flow if matched_policy else []) or [{"group_name": "DBA", "sla_minutes": 60}]
        for idx, step in enumerate(flow, start=1):
            SQLApprovalStep.objects.create(
                order=order,
                step_no=idx,
                approver_role=step.get("group_name", ""),
                comment=f"SLA {step.get('sla_minutes', matched_policy.sla_minutes if matched_policy else 60)} 分钟",
            )
        job.status = "waiting_approval"
        job.save(update_fields=["status", "updated_at"])
        append_job_log(job, f"[trace:{job.trace_id}] SQL 作业进入审批流程，申请人: {applicant.username}")
        return job, report, order
    start_job_async(job, request_meta=request_meta)
    return job, report, None


def start_job_async(job: SQLExecutionJob, request_meta=None):
    if _should_use_celery():
        celery_app.send_task("db_manager.run_sql_job", args=[job.id, request_meta or {}])
        return
    with JOB_LOCK:
        if job.id in JOB_THREADS:
            return
        thread = threading.Thread(target=_run_sql_job, args=(job.id, request_meta), daemon=True)
        JOB_THREADS[job.id] = thread
        thread.start()


def approve_order(order: SQLApprovalOrder, approver, request_meta=None):
    current_step = order.steps.filter(action="pending").order_by("step_no").first()
    if current_step:
        current_step.action = "approved"
        current_step.approver = approver
        current_step.acted_at = timezone.now()
        current_step.comment = f"{current_step.comment}\napproved by {approver.username}".strip()
        current_step.save(update_fields=["action", "approver", "acted_at", "comment"])
    job = order.job
    next_step = order.steps.filter(action="pending").order_by("step_no").first()
    if next_step:
        order.current_node = next_step.step_no
        order.save(update_fields=["current_node"])
        append_job_log(job, f"[trace:{job.trace_id}] 当前审批节点通过，进入下一节点 {next_step.step_no}", "success")
        return
    order.status = "approved"
    order.approved_at = timezone.now()
    order.save(update_fields=["status", "approved_at"])
    append_job_log(job, f"[trace:{job.trace_id}] 审批通过，审批人: {approver.username}", "success")
    job.status = "queued"
    job.save(update_fields=["status", "updated_at"])
    start_job_async(job, request_meta=request_meta)


def reject_order(order: SQLApprovalOrder, approver, comment=""):
    current_step = order.steps.filter(action="pending").order_by("step_no").first()
    if current_step:
        current_step.action = "rejected"
        current_step.approver = approver
        current_step.acted_at = timezone.now()
        current_step.comment = comment
        current_step.save(update_fields=["action", "approver", "acted_at", "comment"])
    order.status = "rejected"
    order.rejected_at = timezone.now()
    order.reason = comment or order.reason
    order.save(update_fields=["status", "rejected_at", "reason"])
    job = order.job
    job.status = "cancelled"
    job.error_message = "审批拒绝"
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
    append_job_log(job, f"审批拒绝，审批人: {approver.username}", "warning")
    _write_audit(job)


def cancel_job(job: SQLExecutionJob):
    job.cancel_requested = True
    ctx = job.execution_context or {}
    engine = DBEngineFactory.get_engine(job.instance)
    if hasattr(engine, "cancel_query"):
        thread_id = ctx.get("thread_id")
        backend_pid = ctx.get("backend_pid")
        engine.cancel_query(thread_id or backend_pid)
    job.status = "cancelled"
    job.finished_at = timezone.now()
    job.save(update_fields=["cancel_requested", "status", "finished_at", "updated_at"])
    append_job_log(job, "SQL 作业已取消", "warning")
    _write_audit(job)


def pause_job(job: SQLExecutionJob):
    job.pause_requested = True
    if job.status == "queued":
        job.status = "paused"
    job.save(update_fields=["pause_requested", "status", "updated_at"])
    append_job_log(job, "已请求暂停 SQL 作业", "warning")


def resume_job(job: SQLExecutionJob, request_meta=None):
    if job.status == "paused":
        job.pause_requested = False
        job.status = "queued"
        job.save(update_fields=["pause_requested", "status", "updated_at"])
        append_job_log(job, "SQL 作业恢复排队")
        start_job_async(job, request_meta=request_meta)


def serialize_backup_plan(plan: BackupPlan):
    return {
        "id": plan.id,
        "instance": plan.instance_id,
        "instance_name": plan.instance.name,
        "name": plan.name,
        "backup_type": plan.backup_type,
        "schedule_expr": plan.schedule_expr,
        "retention_days": plan.retention_days,
        "storage_uri": plan.storage_uri,
        "storage_config": plan.storage_config,
        "compression_enabled": plan.compression_enabled,
        "encryption_enabled": plan.encryption_enabled,
        "enabled": plan.enabled,
        "last_run_at": plan.last_run_at,
        "next_run_at": plan.next_run_at,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def serialize_access_rule(rule: DBAccessRule):
    conflicts = []
    for other in DBAccessRule.objects.exclude(id=rule.id).filter(enabled=True):
        if rule.instance_id and other.instance_id and rule.instance_id != other.instance_id:
            continue
        if set(rule.actions or []).intersection(other.actions or []) and (
            _match_pattern(rule.database_pattern, other.database_pattern) or _match_pattern(other.database_pattern, rule.database_pattern)
        ) and (
            _match_pattern(rule.table_pattern, other.table_pattern) or _match_pattern(other.table_pattern, rule.table_pattern)
        ):
            conflicts.append(other.name)
    return {
        "id": rule.id,
        "name": rule.name,
        "user_id": rule.user_id,
        "username": rule.user.username if rule.user_id else "",
        "group_name": rule.group_name,
        "instance": rule.instance_id,
        "instance_name": rule.instance.name if rule.instance_id else "全部实例",
        "database_pattern": rule.database_pattern,
        "table_pattern": rule.table_pattern,
        "sql_types": rule.sql_types,
        "actions": rule.actions,
        "match_explanation": f"{rule.instance.name if rule.instance_id else '全部实例'} / {rule.database_pattern} / {rule.table_pattern} / {','.join(rule.actions or [])}",
        "conflicts": conflicts[:5],
        "enabled": rule.enabled,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def upsert_access_rule(data):
    rule_id = data.get("id")
    rule = DBAccessRule.objects.filter(id=rule_id).first() if rule_id else None
    if rule is None:
        rule = DBAccessRule()
    for field in ["name", "group_name", "database_pattern", "table_pattern", "sql_types", "actions", "enabled"]:
        if field in data:
            setattr(rule, field, data.get(field))
    if "user_id" in data:
        rule.user_id = data.get("user_id") or None
    if "instance" in data:
        instance_value = data.get("instance")
        if isinstance(instance_value, DBInstance):
            rule.instance = instance_value
        else:
            rule.instance_id = instance_value or None
    rule.save()
    return rule


def _run_command(command, env=None):
    process = subprocess.run(command, env=env, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or "command failed")
    return process.stdout.strip()


def _build_db_cli_env(instance: DBInstance):
    env = os.environ.copy()
    password = getattr(getattr(instance, "secret", None), "get_password", lambda: "")() or ""
    if instance.db_type == "mysql":
        env["MYSQL_PWD"] = password
    if instance.db_type == "postgresql":
        env["PGPASSWORD"] = password
    return env


def _capture_txn_snapshot(instance: DBInstance, database_name: str):
    engine = DBEngineFactory.get_engine(instance)
    snapshot = {"db_type": instance.db_type}
    try:
        if instance.db_type == "mysql":
            conn = engine._connect(database_name or instance.default_database)
            try:
                with conn.cursor() as c:
                    c.execute("SHOW MASTER STATUS")
                    row = c.fetchone() or {}
                    snapshot.update({"binlog_file": row.get("File"), "binlog_position": row.get("Position")})
            finally:
                conn.close()
        elif instance.db_type == "postgresql":
            conn = engine._connect(database_name or instance.default_database)
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
                    c.execute("SELECT pg_current_wal_lsn() AS wal_lsn")
                    row = c.fetchone() or {}
                    snapshot.update({"wal_lsn": row.get("wal_lsn")})
            finally:
                conn.close()
    except Exception as exc:
        snapshot["capture_error"] = str(exc)
    return snapshot


def _extract_where_clause(sql: str):
    match = re.search(r"\bwhere\b(.+?)(?:\border\s+by\b|\blimit\b|;|$)", sql or "", re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _capture_before_image(instance: DBInstance, database_name: str, sql: str):
    sql_type = _sql_type(sql)
    if sql_type not in {"UPDATE", "DELETE"}:
        return []
    tables = _extract_tables(sql)
    if not tables:
        return []
    table_name = tables[0].split(".")[-1]
    where_clause = _extract_where_clause(sql)
    if not where_clause:
        return []
    engine = DBEngineFactory.get_engine(instance)
    try:
        result = engine.query(database_name or instance.default_database, table_name, {
            "sql": f"SELECT * FROM {table_name} WHERE {where_clause} LIMIT 200"
        })
        return result.get("rows", [])
    except Exception:
        return []


def _primary_key_field(row: dict):
    for key in row.keys():
        if key.lower() == "id" or key.lower().endswith("_id"):
            return key
    return next(iter(row.keys()), None)


def _sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _backup_file_path(plan: BackupPlan):
    ext_map = {
        ("mysql", "logical"): "sql",
        ("mysql", "physical"): "xbstream",
        ("postgresql", "logical"): "sql",
        ("postgresql", "physical"): "tar",
        ("redis", "logical"): "rdb",
        ("mongo", "logical"): "archive",
        ("rabbitmq", "logical"): "json",
    }
    base_dir = _backup_root() / plan.instance.name
    base_dir.mkdir(parents=True, exist_ok=True)
    ext = ext_map.get((plan.instance.db_type, plan.backup_type), ext_map.get((plan.instance.db_type, "logical"), "bak"))
    return base_dir / f"{plan.name}_{timezone.now().strftime('%Y%m%d%H%M%S')}.{ext}"


def _execute_backup(record_id: int):
    record = BackupRecord.objects.select_related("plan", "instance", "instance__secret").get(id=record_id)
    plan = record.plan
    instance = record.instance
    record.status = "running"
    record.started_at = timezone.now()
    record.save(update_fields=["status", "started_at"])
    plan.last_run_at = timezone.now()
    plan.save(update_fields=["last_run_at", "updated_at"])
    file_path = Path(record.file_uri)
    if str(record.file_uri).startswith("local://"):
        file_path = _backup_root() / record.file_uri.replace("local://", "").lstrip("/")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    env = _build_db_cli_env(instance)
    metadata = dict(record.metadata_json or {})
    metadata["txn_snapshot"] = {
        "before": _capture_txn_snapshot(instance, instance.default_database),
    }
    try:
        if instance.db_type == "mysql":
            cmd = [
                shutil.which("mysqldump") or "mysqldump",
                "-h", instance.host,
                "-P", str(instance.port),
                "-u", getattr(instance.secret, "username", ""),
                "--single-transaction",
                instance.default_database or "mysql",
            ]
            result = subprocess.run(cmd, env=env, capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode("utf-8", errors="ignore") or "mysqldump failed")
            file_path.write_bytes(result.stdout)
        elif instance.db_type == "postgresql":
            if plan.backup_type == "physical":
                cmd = [
                    shutil.which("pg_basebackup") or "pg_basebackup",
                    "-h", instance.host,
                    "-p", str(instance.port),
                    "-U", getattr(instance.secret, "username", ""),
                    "-D", "-",
                    "-F", "t",
                    "-X", "stream",
                ]
                result = subprocess.run(cmd, env=env, capture_output=True)
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.decode("utf-8", errors="ignore") or "pg_basebackup failed")
                file_path.write_bytes(result.stdout)
            else:
                cmd = [
                    shutil.which("pg_dump") or "pg_dump",
                    "-h", instance.host,
                    "-p", str(instance.port),
                    "-U", getattr(instance.secret, "username", ""),
                    "-d", instance.default_database or "postgres",
                    "-f", str(file_path),
                ]
                _run_command(cmd, env=env)
        elif instance.db_type == "mongo":
            cmd = [
                shutil.which("mongodump") or "mongodump",
                f"--host={instance.host}",
                f"--port={instance.port}",
                f"--username={getattr(instance.secret, 'username', '')}",
                f"--password={getattr(instance.secret, 'get_password', lambda: '')()}",
                f"--db={instance.default_database or 'admin'}",
                f"--archive={file_path}",
            ]
            _run_command(cmd, env=env)
        elif instance.db_type == "redis":
            cmd = [
                shutil.which("redis-cli") or "redis-cli",
                "-h", instance.host,
                "-p", str(instance.port),
                "--rdb", str(file_path),
            ]
            if getattr(instance.secret, "get_password", lambda: "")():
                cmd.extend(["-a", getattr(instance.secret, "get_password", lambda: "")()])
            _run_command(cmd, env=env)
        else:
            raise RuntimeError(f"{instance.db_type} 暂未支持真实备份")
        if plan.compression_enabled and file_path.exists():
            file_path = _compress_file(file_path)
        if plan.encryption_enabled and file_path.exists():
            file_path = _encrypt_file(file_path)
        checksum = _sha256_file(file_path) if file_path.exists() else ""
        metadata["checksum_sha256"] = checksum
        storage_config = plan.storage_config or {}
        if plan.storage_uri.startswith("s3://") and storage_config.get("bucket"):
            client = _storage_client(storage_config)
            if not client:
                raise RuntimeError("对象存储客户端不可用")
            object_prefix = plan.storage_uri.replace(f"s3://{storage_config.get('bucket')}", "").strip("/")
            object_key = "/".join(x for x in [object_prefix, plan.instance.name, file_path.name] if x)
            client.upload_file(str(file_path), storage_config["bucket"], object_key)
            metadata["object_key"] = object_key
        record.file_size = file_path.stat().st_size if file_path.exists() else 0
        record.file_uri = str(file_path)
        record.checksum_sha256 = metadata.get("checksum_sha256", "")
        record.status = "success"
        record.finished_at = timezone.now()
        metadata["executor"] = "real"
        metadata["txn_snapshot"]["after"] = _capture_txn_snapshot(instance, instance.default_database)
        record.metadata_json = metadata
        record.save(update_fields=["file_uri", "file_size", "checksum_sha256", "status", "finished_at", "metadata_json"])
        _cleanup_local_backups(plan)
        _cleanup_s3_backups(plan)
    except Exception as exc:
        record.status = "failed"
        record.finished_at = timezone.now()
        metadata["error"] = str(exc)
        record.metadata_json = metadata
        record.save(update_fields=["status", "finished_at", "metadata_json"])
    finally:
        with JOB_LOCK:
            BACKUP_THREADS.pop(record.id, None)


def upsert_backup_plan(data, user):
    plan_id = data.get("id")
    plan = BackupPlan.objects.filter(id=plan_id).first() if plan_id else None
    if plan is None:
        plan = BackupPlan(created_by=user)
    if "instance" in data:
        instance_value = data.get("instance")
        if isinstance(instance_value, DBInstance):
            plan.instance = instance_value
        else:
            plan.instance_id = instance_value
    for field in ["name", "backup_type", "schedule_expr", "retention_days", "storage_uri", "storage_config", "compression_enabled", "encryption_enabled", "enabled"]:
        if field in data:
            setattr(plan, field, data.get(field))
    plan.save()
    return plan


def run_backup_plan(plan: BackupPlan):
    now = timezone.now()
    file_path = _backup_file_path(plan)
    record = BackupRecord.objects.create(
        plan=plan,
        instance=plan.instance,
        backup_type=plan.backup_type,
        file_uri=str(file_path),
        file_size=0,
        snapshot_ref=f"{plan.instance.name}-{now.strftime('%Y%m%d%H%M%S')}",
        trace_id=uuid.uuid4().hex,
        status="pending",
        metadata_json={
            "schedule_expr": plan.schedule_expr,
            "retention_days": plan.retention_days,
            "instance": plan.instance.name,
            "storage_uri": plan.storage_uri,
        },
    )
    plan.last_run_at = now
    plan.next_run_at = now
    plan.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
    if _should_use_celery():
        celery_app.send_task("db_manager.run_backup_record", args=[record.id])
        return record
    with JOB_LOCK:
        if record.id not in BACKUP_THREADS:
            thread = threading.Thread(target=_execute_backup, args=(record.id,), daemon=True)
            BACKUP_THREADS[record.id] = thread
            thread.start()
    return record


def _restore_mysql_dump(instance: DBInstance, env, file_path: Path):
    cmd = [
        shutil.which("mysql") or "mysql",
        "-h", instance.host,
        "-P", str(instance.port),
        "-u", getattr(instance.secret, "username", ""),
        instance.default_database or "mysql",
    ]
    with open(file_path, "rb") as fp:
        process = subprocess.run(cmd, env=env, stdin=fp, capture_output=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode("utf-8", errors="ignore") or "mysql restore failed")


def _apply_mysql_pitr(job: RestoreJob, env, logs, file_path: Path):
    _restore_mysql_dump(job.instance, env, file_path)
    snapshot = ((job.backup_record.metadata_json or {}).get("txn_snapshot") or {}).get("after") or {}
    start_pos = snapshot.get("binlog_position")
    binlog_file = snapshot.get("binlog_file")
    binlog_dir = (job.instance.extra_config or {}).get("mysql_binlog_dir")
    if not binlog_dir or not binlog_file or not start_pos:
        raise RuntimeError("PITR 缺少 mysql_binlog_dir 或备份事务快照")
    mysqlbinlog = shutil.which("mysqlbinlog") or "mysqlbinlog"
    binlog_files = sorted(str(p) for p in Path(binlog_dir).glob("*") if p.is_file() and p.name >= str(binlog_file))
    if not binlog_files:
        raise RuntimeError("未找到可用于 PITR 的 binlog 文件")
    cmd = [mysqlbinlog, f"--start-position={start_pos}"]
    if job.restore_mode == "point_in_time":
        if not job.target_time:
            raise RuntimeError("PITR 需要目标时间点")
        target_time = job.target_time.isoformat(sep=" ", timespec="seconds")
        cmd.append(f"--stop-datetime={target_time}")
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 应用 MySQL binlog 到时间点 {target_time}"})
    else:
        if not job.target_txn_id:
            raise RuntimeError("事务级恢复需要 GTID 或 stop-position")
        if ":" in job.target_txn_id or "," in job.target_txn_id:
            cmd.append(f"--include-gtids={job.target_txn_id}")
        else:
            cmd.append(f"--stop-position={job.target_txn_id}")
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 应用 MySQL binlog 到事务目标 {job.target_txn_id}"})
    cmd.extend(binlog_files)
    mysql_cmd = [
        shutil.which("mysql") or "mysql",
        "-h", job.instance.host,
        "-P", str(job.instance.port),
        "-u", getattr(job.instance.secret, "username", ""),
        job.instance.default_database or "mysql",
    ]
    binlog_process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    mysql_process = subprocess.Popen(mysql_cmd, env=env, stdin=binlog_process.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if binlog_process.stdout:
        binlog_process.stdout.close()
    _, mysql_stderr = mysql_process.communicate()
    _, binlog_stderr = binlog_process.communicate()
    if binlog_process.returncode != 0:
        raise RuntimeError(binlog_stderr.decode("utf-8", errors="ignore") or "mysqlbinlog failed")
    if mysql_process.returncode != 0:
        raise RuntimeError(mysql_stderr.decode("utf-8", errors="ignore") or "mysql apply binlog failed")


def _apply_postgresql_pitr(job: RestoreJob, logs, file_path: Path):
    extra = job.instance.extra_config or {}
    restore_dir = Path(extra.get("pg_restore_data_dir") or _backup_root() / "pg_pitr" / job.instance.name)
    wal_archive_dir = extra.get("pg_wal_archive_dir")
    if not wal_archive_dir:
        raise RuntimeError("PITR 缺少 pg_wal_archive_dir 配置")
    if restore_dir.exists():
        shutil.rmtree(restore_dir)
    restore_dir.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(file_path):
        with tarfile.open(file_path) as tar:
            tar.extractall(restore_dir)
    elif file_path.is_dir():
        for child in file_path.iterdir():
            target = restore_dir / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            else:
                shutil.copy2(child, target)
    else:
        raise RuntimeError("PostgreSQL PITR 需要 physical base backup tar 包或目录")
    recovery_conf = restore_dir / "postgresql.auto.conf"
    with open(recovery_conf, "a", encoding="utf-8") as fp:
        fp.write(f"\nrestore_command = 'cp {wal_archive_dir}/%f %p'\n")
        fp.write("recovery_target_action = 'promote'\n")
        if job.restore_mode == "point_in_time":
            if not job.target_time:
                raise RuntimeError("PITR 需要目标时间点")
            fp.write(f"recovery_target_time = '{job.target_time.isoformat(sep=' ', timespec='seconds')}'\n")
        else:
            if not job.target_txn_id:
                raise RuntimeError("事务级恢复需要 target_txn_id")
            fp.write(f"recovery_target_xid = '{job.target_txn_id}'\n")
    (restore_dir / "recovery.signal").touch()
    logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 已生成 PostgreSQL PITR 恢复目录 {restore_dir}"})
    pg_ctl = extra.get("pg_ctl_path") or shutil.which("pg_ctl")
    if extra.get("pg_auto_start_recovery"):
        if not pg_ctl:
            raise RuntimeError("未找到 pg_ctl，无法自动启动 PITR")
        cmd = [pg_ctl, "-D", str(restore_dir), "-w", "start"]
        if extra.get("pg_pitr_port"):
            cmd.extend(["-o", f"-p {extra.get('pg_pitr_port')}"])
        _run_command(cmd)
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] PostgreSQL PITR 已自动启动"})


def _restore_postgresql_backup(job: RestoreJob, env, logs, file_path: Path):
    if (job.backup_record.backup_type or "") == "physical":
        extra = job.instance.extra_config or {}
        restore_dir = Path(extra.get("pg_restore_data_dir") or _backup_root() / "pg_restore" / job.instance.name)
        if restore_dir.exists():
            shutil.rmtree(restore_dir)
        restore_dir.mkdir(parents=True, exist_ok=True)
        if tarfile.is_tarfile(file_path):
            with tarfile.open(file_path) as tar:
                tar.extractall(restore_dir)
        else:
            raise RuntimeError("物理备份恢复需要 tar 文件")
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] PostgreSQL 物理备份已恢复到 {restore_dir}"})
        return
    cmd = [
        shutil.which("psql") or "psql",
        "-h", job.instance.host,
        "-p", str(job.instance.port),
        "-U", getattr(job.instance.secret, "username", ""),
        "-d", job.instance.default_database or "postgres",
        "-f", str(file_path),
    ]
    _run_command(cmd, env=env)


def _execute_restore(job_id: int):
    job = RestoreJob.objects.select_related("instance", "instance__secret", "backup_record", "backup_record__plan").get(id=job_id)
    job.status = "running"
    job.started_at = timezone.now()
    logs = list(job.log_json or [])
    logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 开始执行恢复任务"})
    job.log_json = logs
    job.save(update_fields=["status", "started_at", "log_json"])
    instance = job.instance
    env = _build_db_cli_env(instance)
    try:
        if not job.backup_record:
            raise RuntimeError("缺少备份记录")
        file_path = _prepare_restore_file(job.backup_record)
        if instance.db_type == "mysql":
            if job.restore_mode == "backup":
                _restore_mysql_dump(instance, env, file_path)
            else:
                _apply_mysql_pitr(job, env, logs, file_path)
        elif instance.db_type == "postgresql":
            if job.restore_mode == "backup":
                _restore_postgresql_backup(job, env, logs, file_path)
            else:
                _apply_postgresql_pitr(job, logs, file_path)
        elif instance.db_type == "mongo":
            cmd = [
                shutil.which("mongorestore") or "mongorestore",
                f"--host={instance.host}",
                f"--port={instance.port}",
                f"--username={getattr(instance.secret, 'username', '')}",
                f"--password={getattr(instance.secret, 'get_password', lambda: '')()}",
                f"--archive={file_path}",
                "--drop",
            ]
            _run_command(cmd, env=env)
        elif instance.db_type == "redis":
            raise RuntimeError("Redis 恢复需替换 RDB/AOF 文件，当前版本不支持在线恢复")
        else:
            raise RuntimeError(f"{instance.db_type} 暂未支持真实恢复")
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 恢复任务执行成功"})
        job.status = "success"
        job.finished_at = timezone.now()
        job.log_json = logs
        job.save(update_fields=["status", "finished_at", "log_json"])
    except Exception as exc:
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 恢复失败: {exc}"})
        job.status = "failed"
        job.finished_at = timezone.now()
        job.log_json = logs
        job.save(update_fields=["status", "finished_at", "log_json"])
    finally:
        with JOB_LOCK:
            RESTORE_THREADS.pop(job.id, None)


def create_restore_job(instance_id, backup_record_id=None, restore_mode="backup", target_time=None, target_txn_id="", user=None):
    parsed_target_time = parse_datetime(target_time) if isinstance(target_time, str) and target_time else target_time
    if parsed_target_time and timezone.is_naive(parsed_target_time):
        parsed_target_time = timezone.make_aware(parsed_target_time, timezone.get_current_timezone())
    job = RestoreJob.objects.create(
        instance_id=instance_id,
        backup_record_id=backup_record_id or None,
        restore_mode=restore_mode,
        target_time=parsed_target_time,
        target_txn_id=target_txn_id or "",
        trace_id=uuid.uuid4().hex,
        status="pending",
        log_json=[
            {"time": timezone.now().isoformat(), "message": "已创建恢复任务"},
            {"time": timezone.now().isoformat(), "message": "已进入恢复队列"},
        ],
        created_by=user,
    )
    if _should_use_celery():
        celery_app.send_task("db_manager.run_restore_job", args=[job.id])
        return job
    with JOB_LOCK:
        if job.id not in RESTORE_THREADS:
            thread = threading.Thread(target=_execute_restore, args=(job.id,), daemon=True)
            RESTORE_THREADS[job.id] = thread
            thread.start()
    return job


def _build_rollback_sql(audit: SQLAuditLog):
    sql_type = (audit.sql_type or "").upper()
    sql = audit.normalized_sql or audit.sql_text or ""
    tables = audit.table_names_json or []
    table_name = tables[0].split(".")[-1] if tables else "target_table"
    if sql_type == "INSERT":
        return f"-- 请补充主键条件\nDELETE FROM {table_name} WHERE <primary_key_condition>;"
    if sql_type == "UPDATE":
        rows = audit.before_image_json or []
        statements = []
        for row in rows:
            pk = _primary_key_field(row)
            if not pk:
                continue
            set_clause = ", ".join(f"{col}={_sql_literal(val)}" for col, val in row.items() if col != pk)
            where_clause = f"{pk}={_sql_literal(row.get(pk))}"
            statements.append(f"UPDATE {table_name} SET {set_clause} WHERE {where_clause};")
        return "\n".join(statements) if statements else f"-- 请根据审计记录补充回滚前字段值\nUPDATE {table_name} SET <column>=<old_value> WHERE <primary_key_condition>;"
    if sql_type == "DELETE":
        rows = audit.before_image_json or []
        statements = []
        for row in rows:
            columns = ", ".join(row.keys())
            values = ", ".join(_sql_literal(value) for value in row.values())
            statements.append(f"INSERT INTO {table_name} ({columns}) VALUES ({values});")
        return "\n".join(statements) if statements else f"-- 请根据备份或审计快照补充被删除记录\nINSERT INTO {table_name} (<columns>) VALUES (<old_values>);"
    if sql_type in {"ALTER", "DROP", "TRUNCATE", "CREATE"}:
        snapshot = audit.txn_snapshot_json or {}
        return f"-- {sql_type} 属于结构变更，建议优先使用备份恢复或 PITR\n-- 事务快照: {json.dumps(snapshot, ensure_ascii=False)}\n-- 原始 SQL:\n{sql}"
    return f"-- 未识别的回滚模板，请人工评估\n-- 原始 SQL:\n{sql}"


def serialize_rollback_job(job: RollbackJob):
    return {
        "id": job.id,
        "source_audit": job.source_audit_id,
        "source_txn_id": job.source_txn_id,
        "instance": job.instance_id,
        "instance_name": job.instance.name,
        "rollback_sql": job.rollback_sql,
        "status": job.status,
        "log_json": job.log_json,
        "created_by": job.created_by_id,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "created_at": job.created_at,
    }


def _execute_rollback(job_id: int):
    job = RollbackJob.objects.select_related("instance", "instance__secret").get(id=job_id)
    logs = list(job.log_json or [])
    logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 开始执行回滚 SQL"})
    job.status = "running"
    job.started_at = timezone.now()
    job.log_json = logs
    job.save(update_fields=["status", "started_at", "log_json"])
    try:
        if not job.rollback_sql.strip():
            raise RuntimeError("回滚 SQL 为空")
        engine = DBEngineFactory.get_engine(job.instance)
        engine.execute_sql(job.instance.default_database, job.rollback_sql)
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 回滚 SQL 执行成功"})
        job.status = "success"
        job.finished_at = timezone.now()
        job.log_json = logs
        job.save(update_fields=["status", "finished_at", "log_json"])
    except Exception as exc:
        logs.append({"time": timezone.now().isoformat(), "message": f"[trace:{job.trace_id}] 回滚失败: {exc}"})
        job.status = "failed"
        job.finished_at = timezone.now()
        job.log_json = logs
        job.save(update_fields=["status", "finished_at", "log_json"])
    finally:
        with JOB_LOCK:
            ROLLBACK_THREADS.pop(job.id, None)


def create_rollback_job(instance: DBInstance, user, audit: SQLAuditLog = None, source_txn_id: str = ""):
    rollback_sql = _build_rollback_sql(audit) if audit else "-- 请手工补充回滚 SQL"
    job = RollbackJob.objects.create(
        source_audit=audit,
        source_txn_id=source_txn_id or "",
        instance=instance,
        trace_id=uuid.uuid4().hex,
        rollback_sql=rollback_sql,
        status="generated",
        log_json=[
            {"time": timezone.now().isoformat(), "message": "已生成回滚任务"},
            {"time": timezone.now().isoformat(), "message": "请确认回滚 SQL 后执行"},
        ],
        created_by=user,
    )
    return job


def execute_rollback_job(job: RollbackJob):
    if _should_use_celery():
        celery_app.send_task("db_manager.run_rollback_job", args=[job.id])
        return
    with JOB_LOCK:
        if job.id not in ROLLBACK_THREADS:
            thread = threading.Thread(target=_execute_rollback, args=(job.id,), daemon=True)
            ROLLBACK_THREADS[job.id] = thread
            thread.start()


def export_audit_rows(queryset):
    rows = []
    for item in queryset:
        rows.append({
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
            "created_at": item.created_at.isoformat() if item.created_at else "",
            "sql_text": item.sql_text,
        })
    return rows


def approval_is_overdue(order: SQLApprovalOrder):
    pending_step = order.steps.filter(action="pending").order_by("step_no").first()
    if not pending_step:
        return False
    match = re.search(r"SLA\s+(\d+)\s*分钟", pending_step.comment or "")
    if not match:
        return False
    sla_minutes = int(match.group(1))
    return timezone.now() > order.submitted_at + timedelta(minutes=sla_minutes)


def remind_approval(order: SQLApprovalOrder, actor):
    pending_step = order.steps.filter(action="pending").order_by("step_no").first()
    if not pending_step:
        return
    append_job_log(order.job, f"[trace:{order.job.trace_id}] {actor.username} 催办审批节点 {pending_step.step_no}，目标角色 {pending_step.approver_role}", "warning")


def run_instance_diagnostics(instance: DBInstance):
    report = {
        "instance": serialize_instance(instance),
        "checks": [],
        "summary": {},
    }
    ok, message = test_instance(instance)
    report["checks"].append({"name": "连接测试", "status": "success" if ok else "failed", "message": message})
    try:
        structure = get_schema(instance)
        schema_count = len(structure.keys()) if isinstance(structure, dict) else 0
        table_count = sum(len(v) for v in structure.values()) if isinstance(structure, dict) else 0
        report["checks"].append({"name": "Schema 读取", "status": "success", "message": f"{schema_count} 个 schema / {table_count} 张表"})
        report["summary"]["schema_count"] = schema_count
        report["summary"]["table_count"] = table_count
    except Exception as exc:
        report["checks"].append({"name": "Schema 读取", "status": "failed", "message": str(exc)})
    report["summary"]["backup_plan_count"] = instance.backup_plans.count()
    report["summary"]["latest_backup_status"] = instance.backup_records.order_by("-created_at").values_list("status", flat=True).first() or "none"
    report["summary"]["sql_job_count"] = instance.sql_jobs.count()
    report["summary"]["failed_sql_jobs"] = instance.sql_jobs.filter(status="failed").count()
    report["checks"].append({
        "name": "备份状态",
        "status": "success" if report["summary"]["latest_backup_status"] in ("success", "none") else "warning",
        "message": f'计划 {report["summary"]["backup_plan_count"]} 条，最近备份状态 {report["summary"]["latest_backup_status"]}',
    })
    report["checks"].append({
        "name": "作业状态",
        "status": "success" if report["summary"]["failed_sql_jobs"] == 0 else "warning",
        "message": f'共 {report["summary"]["sql_job_count"]} 条 SQL 作业，失败 {report["summary"]["failed_sql_jobs"]} 条',
    })
    return report

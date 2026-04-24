import os
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Optional, Tuple

from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from inspection.models import InspectionConfig

from .models import TrafficDashboardConfig
from .services.aggregator import (
    aggregate_timeseries,
    geo_aggregate,
    overview_kpis,
    top_lists,
    window_bounds,
)
from .services.blackbox import fetch_blackbox_summary
from .services.geoip_lookup import enrich_records
from .services.log_sources import (
    load_raw_records,
    log_source_configured,
    redis_key_for_ingest,
    resolve_effective_traffic_source_id,
    resolve_ingest_log_format,
    sources_for_api,
)
from .services.nginx_log import records_from_lines
from .services.redis_log_buffer import is_configured as redis_buffer_configured, push_raw_lines
from .services.clickhouse_rollups import clickhouse_configured
from .services.jaeger_query import fetch_jaeger_flow, jaeger_configured
from .services.rollup_buffer import rollup_enabled, rollup_ingest_append
from .services.rollup_query import build_rollups_snapshot


def _access_log_mode(cfg: TrafficDashboardConfig) -> str:
    m = (cfg.access_log_mode or os.environ.get("TRAFFIC_ACCESS_LOG_MODE", "file") or "file").strip()
    return m if m in ("file", "redis") else "file"


def _redis_cap(cfg: TrafficDashboardConfig) -> int:
    """0 = 不 LTRIM（不限制 Redis 列表长度），与 log_sources.redis_cap 一致。"""
    try:
        n = int(getattr(cfg, "redis_max_lines", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return 0
    return max(1_000, min(n, 2_000_000))


def _dashboard_fetch_limits(cfg: TrafficDashboardConfig) -> Tuple[int, int]:
    """UI 拉取：0=不限制行数；文件尾部字节可选环境变量覆盖。"""
    try:
        rl = int(getattr(cfg, "dashboard_fetch_max_lines", 0) or 0)
    except (TypeError, ValueError):
        rl = 0
    if rl > 0:
        rl = max(1, min(rl, 100_000_000))
    try:
        tb = int(os.environ.get("TRAFFIC_DASHBOARD_MAX_TAIL_BYTES", str(4 * 1024 * 1024)))
    except ValueError:
        tb = 4 * 1024 * 1024
    tb = max(262_144, min(tb, 52_428_800))
    return rl, tb


def _full_data_fetch_limits(cfg: TrafficDashboardConfig) -> Tuple[int, int]:
    """大盘 full_data=1：Redis 读满列表保留上限（不受 dashboard_fetch_max_lines）；文件 tail 字节用独立上限。"""
    rl = _redis_cap(cfg)
    try:
        tb = int(os.environ.get("TRAFFIC_FULL_DATA_MAX_TAIL_BYTES", str(500 * 1024 * 1024)))
    except ValueError:
        tb = 500 * 1024 * 1024
    tb = max(262_144, min(tb, 2_147_483_647))
    return rl, tb


def _load_enriched(resolved_source_id: str, *, full_data: bool = False):
    """resolved_source_id: from resolve_effective_traffic_source_id (all / 具体 id)."""
    cfg = TrafficDashboardConfig.load()
    if not cfg.enabled:
        return cfg, []
    if full_data:
        rl, tb = _full_data_fetch_limits(cfg)
    else:
        rl, tb = _dashboard_fetch_limits(cfg)
    recs = load_raw_records(
        cfg, resolved_source_id, redis_line_cap=rl, max_tail_bytes_override=tb
    )
    enrich_records(recs, cfg.geoip_db_path)
    return cfg, recs


def _rollup_snapshot_has_rows(data: dict) -> bool:
    ov = data.get("overview") or {}
    try:
        return int(ov.get("rollup_rows") or 0) > 0
    except (TypeError, ValueError):
        return False


def _raw_redis_snapshot_fallback_allowed() -> bool:
    """
    无 ClickHouse 时允许从 Redis List 尾部抽样补全大盘；已配置 CH 时默认仅按时间用分钟聚合。

    调试旧行为可设：TRAFFIC_DASHBOARD_REDIS_FALLBACK=1
    """
    if not clickhouse_configured():
        return True
    v = (os.environ.get("TRAFFIC_DASHBOARD_REDIS_FALLBACK") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _time_based_rollup_enforced() -> bool:
    """与大盘展示一致：有 CH 且未开 Redis 抽样回退时，不在 UI 上要求「行数」配置。"""
    return bool(clickhouse_configured() and not _raw_redis_snapshot_fallback_allowed())


def _attach_traffic_rollup_meta(overview: dict) -> None:
    """当前 API 进程是否检测到 TRAFFIC_ROLLUP_ENABLED（与定时任务/ingest 所在进程可能不同）。"""
    overview["rollup_ingest_enabled"] = rollup_enabled()


def _snapshot_payload_from_raw_records(
    cfg: TrafficDashboardConfig,
    recs: list,
    range_key: str,
    inspection,
    *,
    full_data: bool,
    rollup_fallback: bool = False,
) -> dict:
    """从已加载的原始记录构建与 traffic_snapshot 一致的结构。"""
    ov = overview_kpis(recs, range_key)
    bb = fetch_blackbox_summary(cfg, inspection)
    ov["blackbox"] = bb
    if bb.get("availability_pct") is not None:
        ov["availability_pct"] = bb["availability_pct"]
    ov["log_configured"] = log_source_configured(cfg, redis_buffer_configured())
    ov["access_log_mode"] = _access_log_mode(cfg)
    ov["full_data"] = full_data
    ov["minute_rollup"] = False
    if rollup_fallback:
        ov["rollup_fallback"] = True
    _attach_traffic_rollup_meta(ov)
    return {
        "overview": ov,
        "timeseries": aggregate_timeseries(recs, range_key),
        "geo": geo_aggregate(recs, range_key, "country", ""),
        "top_paths": top_lists(recs, range_key, "paths", 10),
        "top_slow": top_lists(recs, range_key, "slow", 10),
        "top_status": top_lists(recs, range_key, "status", 20),
        "top_ip": top_lists(recs, range_key, "ip", 10),
    }


def _parse_full_data(request) -> bool:
    return request.GET.get("full_data", "").strip().lower() in ("1", "true", "yes", "on")


def _preset_window_datetimes(range_key: str) -> Tuple[datetime, datetime]:
    ws, we = window_bounds(range_key)
    return (
        datetime.fromtimestamp(ws, tz=dt_timezone.utc),
        datetime.fromtimestamp(we, tz=dt_timezone.utc),
    )


def _query_source(request) -> str:
    return (request.GET.get("source") or "").strip()


def _query_source_effective(request) -> str:
    """Map legacy default / single-site id to the stream_key used in rollup and Redis."""
    cfg = TrafficDashboardConfig.load()
    return resolve_effective_traffic_source_id(_query_source(request), cfg)


def _parse_custom_time_bounds(request) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Optional ?start=&end= ISO-8601 (UTC or offset). Used for historical charts from TrafficMinuteRollup.
    Max span 90 days. End must not be more than 5 minutes in the future.
    """
    start_s = (request.GET.get("start") or "").strip()
    end_s = (request.GET.get("end") or "").strip()
    if not start_s or not end_s:
        return None, None
    start = parse_datetime(start_s)
    end = parse_datetime(end_s)
    if not start or not end:
        return None, None
    from django.utils import timezone as dj_tz

    if start.tzinfo is None:
        start = start.replace(tzinfo=dt_timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt_timezone.utc)
    now = dj_tz.now()
    if end > now + timedelta(minutes=5):
        end = now + timedelta(minutes=5)
    if end <= start:
        return None, None
    if (end - start) > timedelta(days=90):
        return None, None
    return start, end


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_overview(request):
    range_key = request.GET.get("range", "24h")
    cfg, recs = _load_enriched(_query_source_effective(request), full_data=_parse_full_data(request))
    inspection = InspectionConfig.load()
    data = overview_kpis(recs, range_key)
    bb = fetch_blackbox_summary(cfg, inspection)
    data["blackbox"] = bb
    if bb.get("availability_pct") is not None:
        data["availability_pct"] = bb["availability_pct"]
    data["log_configured"] = log_source_configured(cfg, redis_buffer_configured())
    data["access_log_mode"] = _access_log_mode(cfg)
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_timeseries(request):
    range_key = request.GET.get("range", "24h")
    _, recs = _load_enriched(_query_source_effective(request), full_data=_parse_full_data(request))
    return Response(aggregate_timeseries(recs, range_key))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_geo(request):
    range_key = request.GET.get("range", "24h")
    granularity = request.GET.get("granularity", "country")
    country = request.GET.get("country", "")
    _, recs = _load_enriched(_query_source_effective(request), full_data=_parse_full_data(request))
    return Response(geo_aggregate(recs, range_key, granularity, country))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_top(request):
    range_key = request.GET.get("range", "24h")
    top_type = request.GET.get("type", "paths")
    limit = int(request.GET.get("limit", "10"))
    _, recs = _load_enriched(_query_source_effective(request), full_data=_parse_full_data(request))
    return Response(top_lists(recs, range_key, top_type, limit))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_snapshot(request):
    """
    一次返回大盘所需数据，只解析 / GeoIP 一遍，避免 7 路并行把 Redis 与 CPU 打满导致 503/超时。
    可选 ?start=&end= ISO8601：从持久化分钟聚合表读取任意区间（需开启 TRAFFIC_ROLLUP_ENABLED 并完成 ingest + traffic_rollup_flush）。
    """
    cfg = TrafficDashboardConfig.load()
    source = resolve_effective_traffic_source_id(_query_source(request), cfg)
    start, end = _parse_custom_time_bounds(request)
    if start is not None and end is not None:
        inspection = InspectionConfig.load()
        data = build_rollups_snapshot(start, end, source, cfg, inspection)
        data.setdefault("overview", {})
        data["overview"]["full_data"] = False
        data["overview"]["minute_rollup"] = True
        if not _rollup_snapshot_has_rows(data):
            data["overview"]["rollup_empty"] = True
            if rollup_enabled():
                data["overview"]["rollup_empty_hint"] = (
                    "所选区间内分钟聚合表无行。请核对：ingest 与大盘是否同一 Redis、"
                    "traffic_rollup_flush 是否写入当前 Django 使用的数据库，以及数据源与 rollup 的 source_id 是否一致。"
                )
            else:
                data["overview"]["rollup_empty_hint"] = (
                    "所选区间内分钟聚合无数据。当前大盘 API 进程未检测到环境变量 TRAFFIC_ROLLUP_ENABLED；"
                    "请在写入 rollup 缓冲的 ingest 进程同样开启，并执行 traffic_rollup_flush。"
                )
        _attach_traffic_rollup_meta(data["overview"])
        return Response(data)

    range_key = request.GET.get("range", "24h")
    full_data = _parse_full_data(request)
    inspection = InspectionConfig.load()

    # 默认：预设时间走分钟聚合（PG+ClickHouse）。已配 ClickHouse 时不再用 Redis 行数尾读抽样，真实口径按时间 range。
    if not full_data:
        start_dt, end_dt = _preset_window_datetimes(range_key)
        data = build_rollups_snapshot(
            start_dt, end_dt, source, cfg, inspection, preset_range=range_key
        )
        data.setdefault("overview", {})
        if not _rollup_snapshot_has_rows(data):
            if _raw_redis_snapshot_fallback_allowed():
                _, recs = _load_enriched(source, full_data=False)
                return Response(
                    _snapshot_payload_from_raw_records(
                        cfg, recs, range_key, inspection, full_data=False, rollup_fallback=True
                    )
                )
            # 已配 ClickHouse 时默认不抽样 Redis，但若该时间窗在分钟表真无行（短窗+flush 延迟/尚未写入），
            # 而 Redis 列表里仍有近期日志，则只在这一种「rollup 全空」情况下用尾部补一帧，避免流量趋势全零。
            if (
                not full_data
                and cfg.enabled
                and redis_buffer_configured()
            ):
                _, recs = _load_enriched(source, full_data=False)
                if recs:
                    return Response(
                        _snapshot_payload_from_raw_records(
                            cfg, recs, range_key, inspection, full_data=False, rollup_fallback=True
                        )
                    )
            data["overview"]["full_data"] = False
            data["overview"]["minute_rollup"] = True
            data["overview"]["rollup_empty"] = True
            if clickhouse_configured():
                data["overview"]["rollup_empty_hint"] = (
                    "已配置 ClickHouse：大盘仅按所选时间范围从分钟聚合（PostgreSQL + ClickHouse）读取，"
                    "不再按行数从 Redis 抽样。请确认 ingest 已写入、TRAFFIC_ROLLUP_ENABLED 与 traffic_rollup_flush；"
                    "调试可设环境变量 TRAFFIC_DASHBOARD_REDIS_FALLBACK=1 临时恢复 Redis 抽样回退。"
                )
            else:
                data["overview"]["rollup_empty_hint"] = (
                    "所选区间内分钟聚合无数据。请核对 ingest 与 traffic_rollup_flush、"
                    "以及数据源与 rollup 的 source_id 是否一致。"
                )
            _attach_traffic_rollup_meta(data["overview"])
            return Response(data)
        data["overview"]["full_data"] = False
        data["overview"]["minute_rollup"] = True
        _attach_traffic_rollup_meta(data["overview"])
        return Response(data)

    cfg, recs = _load_enriched(source, full_data=True)
    return Response(
        _snapshot_payload_from_raw_records(
            cfg, recs, range_key, inspection, full_data=True, rollup_fallback=False
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_sources(request):
    cfg = TrafficDashboardConfig.load()
    return Response({"items": sources_for_api(cfg)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_blackbox(request):
    cfg = TrafficDashboardConfig.load()
    inspection = InspectionConfig.load()
    return Response(fetch_blackbox_summary(cfg, inspection))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_jaeger_traces(request):
    return Response(fetch_jaeger_flow(request))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def traffic_jaeger_trace_detail(request, trace_id: str):
    """单条 trace：含 span 级 nodes+links，以及时间线瀑布图 waterfall 数据（前端主视图）。"""
    from .services.jaeger_query import get_trace_by_id, jaeger_configured
    from .services.jaeger_trace_graph import build_trace_graph_payload, sanitize_trace_id

    if not jaeger_configured():
        return Response(
            {"ok": False, "error": "未配置 JAEGER_QUERY_BASE_URL", "graph": None},
            status=400,
        )
    tid = sanitize_trace_id(trace_id)
    if not tid:
        return Response({"ok": False, "error": "trace_id 无效", "graph": None}, status=400)
    raw, err = get_trace_by_id(tid)
    if raw is None:
        return Response(
            {"ok": False, "error": err or "拉取失败", "graph": None, "trace_id": tid},
            status=404,
        )
    graph = build_trace_graph_payload(raw)
    return Response(
        {
            "ok": True,
            "error": None,
            "trace_id": tid,
            "graph": graph,
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def traffic_dashboard_config(request):
    cfg = TrafficDashboardConfig.load()
    if request.method == "GET":
        return Response(
            {
                "enabled": cfg.enabled,
                "access_log_mode": cfg.access_log_mode or TrafficDashboardConfig.ACCESS_LOG_MODE_FILE,
                "access_log_path": cfg.access_log_path,
                "error_log_path": cfg.error_log_path,
                "log_format": cfg.log_format,
                "max_tail_bytes": cfg.max_tail_bytes,
                "redis_log_key": cfg.redis_log_key or "traffic:access:lines",
                "redis_max_lines": cfg.redis_max_lines,
                "dashboard_fetch_max_lines": cfg.dashboard_fetch_max_lines,
                "log_sources": cfg.log_sources if isinstance(cfg.log_sources, list) else [],
                "geoip_db_path": cfg.geoip_db_path,
                "use_inspection_prometheus": cfg.use_inspection_prometheus,
                "prometheus_url_override": cfg.prometheus_url_override,
                "blackbox_promql": cfg.blackbox_promql,
                "redis_env_configured": redis_buffer_configured(),
                "clickhouse_configured": clickhouse_configured(),
                "time_based_rollup_enforced": _time_based_rollup_enforced(),
                "jaeger_query_configured": jaeger_configured(),
                "ingest_path": "/api/traffic/ingest",
                "edge_ingest_path": "/api/edge/logs",
                "edge_token_env": "SHARK_EDGE_TOKEN",
            }
        )
    data = request.data
    cfg.enabled = bool(data.get("enabled", cfg.enabled))
    mode = data.get("access_log_mode", cfg.access_log_mode) or "file"
    cfg.access_log_mode = mode if mode in ("file", "redis") else "file"
    cfg.access_log_path = data.get("access_log_path", cfg.access_log_path) or ""
    cfg.error_log_path = data.get("error_log_path", cfg.error_log_path) or ""
    cfg.log_format = data.get("log_format", cfg.log_format) or "json"
    cfg.max_tail_bytes = int(data.get("max_tail_bytes", cfg.max_tail_bytes))
    cfg.redis_log_key = (data.get("redis_log_key", cfg.redis_log_key) or "traffic:access:lines").strip()[
        :256
    ]
    try:
        rml = int(data.get("redis_max_lines", cfg.redis_max_lines))
        if rml <= 0:
            cfg.redis_max_lines = 0
        else:
            cfg.redis_max_lines = max(1000, min(rml, 50_000_000))
    except (TypeError, ValueError):
        pass
    try:
        dml = int(data.get("dashboard_fetch_max_lines", cfg.dashboard_fetch_max_lines))
        if dml <= 0:
            cfg.dashboard_fetch_max_lines = 0
        else:
            cfg.dashboard_fetch_max_lines = max(1, min(dml, 100_000_000))
    except (TypeError, ValueError):
        pass
    raw_ls = data.get("log_sources", cfg.log_sources)
    if raw_ls is None:
        cfg.log_sources = []
    elif isinstance(raw_ls, list):
        cfg.log_sources = raw_ls
    else:
        cfg.log_sources = []
    cfg.geoip_db_path = data.get("geoip_db_path", cfg.geoip_db_path) or ""
    cfg.use_inspection_prometheus = bool(
        data.get("use_inspection_prometheus", cfg.use_inspection_prometheus)
    )
    cfg.prometheus_url_override = (
        data.get("prometheus_url_override", cfg.prometheus_url_override) or ""
    )
    cfg.blackbox_promql = data.get("blackbox_promql", cfg.blackbox_promql) or ""
    cfg.save()
    return Response({"msg": "saved"})


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def traffic_ingest(request):
    """
    Push NDJSON lines (or JSON {"lines": [...]}) into Redis buffer.
    Auth: Authorization: Bearer <TRAFFIC_INGEST_TOKEN>
    (CSRF-exempt: machine clients do not use browser session cookies.)
    """
    token = os.environ.get("TRAFFIC_INGEST_TOKEN", "").strip()
    if not token:
        return Response({"error": "TRAFFIC_INGEST_TOKEN is not set"}, status=503)
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {token}":
        return Response({"error": "unauthorized"}, status=403)

    try:
        max_batch = int(os.environ.get("TRAFFIC_INGEST_MAX_BODY_LINES", "20000"))
    except ValueError:
        max_batch = 20_000
    max_batch = max(100, min(max_batch, 100_000))

    lines = []
    ct = (request.content_type or "").lower()
    if "application/json" in ct:
        body = request.data
        if isinstance(body, dict):
            raw = body.get("lines")
            if isinstance(raw, list):
                lines = [str(x) for x in raw if x is not None]
            elif isinstance(raw, str):
                lines = [ln for ln in raw.splitlines() if ln.strip()]
        elif isinstance(body, list):
            lines = [str(x) for x in body]
    else:
        raw = request.body.decode("utf-8", errors="replace")
        lines = [ln for ln in raw.splitlines() if ln.strip()]

    truncated = False
    if len(lines) > max_batch:
        lines = lines[:max_batch]
        truncated = True

    if not redis_buffer_configured():
        return Response({"error": "TRAFFIC_REDIS_URL not configured"}, status=503)

    cfg = TrafficDashboardConfig.load()
    ingest_source = (
        (request.GET.get("source") or "").strip()
        or (request.headers.get("X-Traffic-Source") or "").strip()
    )
    key = redis_key_for_ingest(cfg, ingest_source)
    n = push_raw_lines(lines, key, _redis_cap(cfg))
    if rollup_enabled() and n > 0:
        try:
            lf = resolve_ingest_log_format(cfg, ingest_source, "")
            recs = records_from_lines(lines, lf)
            enrich_records(recs, cfg.geoip_db_path)
            rollup_ingest_append(recs, ingest_source or "")
        except Exception:
            pass
    return Response({"accepted": n, "truncated": truncated})


def _edge_ingest_token() -> str:
    return (os.environ.get("SHARK_EDGE_TOKEN") or os.environ.get("TRAFFIC_INGEST_TOKEN") or "").strip()


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def edge_logs_ingest(request):
    """
    go-log-collector: POST JSON with source, lines, stream_key, log_format (optional), source_file (optional).
    Auth: X-Shark-Edge-Token matches SHARK_EDGE_TOKEN (or TRAFFIC_INGEST_TOKEN if SHARK_EDGE_TOKEN unset).
    (CSRF-exempt: go-log-collector has no session cookie; token header provides authentication.)
    """
    token = _edge_ingest_token()
    if not token:
        return Response(
            {"error": "SHARK_EDGE_TOKEN or TRAFFIC_INGEST_TOKEN must be set"},
            status=503,
        )
    if (request.headers.get("X-Shark-Edge-Token") or "").strip() != token:
        return Response({"error": "unauthorized"}, status=403)

    try:
        max_batch = int(os.environ.get("TRAFFIC_INGEST_MAX_BODY_LINES", "20000"))
    except ValueError:
        max_batch = 20_000
    max_batch = max(100, min(max_batch, 100_000))

    body = request.data if isinstance(request.data, dict) else {}
    raw = body.get("lines")
    if not isinstance(raw, list):
        return Response({"error": "lines must be a JSON array"}, status=400)
    lines = [str(x) for x in raw if x is not None]
    truncated = False
    if len(lines) > max_batch:
        lines = lines[:max_batch]
        truncated = True

    if not redis_buffer_configured():
        return Response({"error": "TRAFFIC_REDIS_URL not configured"}, status=503)

    cfg = TrafficDashboardConfig.load()
    stream_key = (body.get("stream_key") or "default").strip() or "default"
    batch_lf = (body.get("log_format") or "").strip()
    lf = resolve_ingest_log_format(cfg, stream_key, batch_lf)

    key = redis_key_for_ingest(cfg, stream_key)
    n = push_raw_lines(lines, key, _redis_cap(cfg))
    if rollup_enabled() and n > 0:
        try:
            recs = records_from_lines(lines, lf)
            enrich_records(recs, cfg.geoip_db_path)
            rollup_ingest_append(recs, stream_key)
        except Exception:
            pass
    return Response({"accepted": n, "truncated": truncated, "stream_key": stream_key})

"""
可插拔洞察检测器（类 Datadog / Grafana Alerting 的简化版）。
新增场景：在此文件注册函数，或实现 observability.plugins 包动态加载（后续）。
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional

from django.conf import settings

from .aggregate import StreamSummary, compare_windows

DetectorFn = Callable[[StreamSummary, dict], Optional[dict]]


def _threshold(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def detect_high_latency(summary: StreamSummary, extra: dict) -> Optional[dict]:
    """延迟过高：p99 请求时间超过阈值（秒）。"""
    p99 = summary.p99_rt
    if p99 is None:
        return None
    lim = _threshold("OBS_LATENCY_P99_WARN_SEC", 1.5)
    if p99 < lim:
        return None
    top = summary.top_paths_slow[:3]
    return {
        "insight_type": "latency_high",
        "severity": "warning" if p99 < lim * 2 else "critical",
        "title": f"p99 延迟 {p99 * 1000:.0f} ms 超过阈值 {lim * 1000:.0f} ms",
        "body": "请求尾部延迟升高，可能与上游超时、数据库或外部依赖有关。建议结合慢路径 Top 与上游耗时排查。",
        "evidence": {
            "p99_rt_sec": p99,
            "threshold_sec": lim,
            "top_slow_paths": top,
        },
    }


def detect_error_spike(summary: StreamSummary, extra: dict) -> Optional[dict]:
    """错误率过高：4xx/5xx 占比与最小样本量。"""
    if summary.total < _threshold("OBS_ERROR_MIN_SAMPLES", 80):
        return None
    rate = summary.error_rate
    lim = _threshold("OBS_ERROR_RATE_WARN", 0.05)
    if rate < lim:
        return None
    return {
        "insight_type": "error_rate_high",
        "severity": "critical" if rate > 0.15 else "warning",
        "title": f"错误率 {rate * 100:.1f}%（{summary.errors}/{summary.total}）",
        "body": "HTTP 错误比例偏高，请检查 5xx 集中路径、发布变更与下游可用性。",
        "evidence": {
            "error_rate": rate,
            "errors": summary.errors,
            "total": summary.total,
            "top_5xx_paths": summary.top_paths_5xx[:5],
        },
    }


def detect_traffic_drop(summary: StreamSummary, extra: dict) -> Optional[dict]:
    """流量突降：相对上一时段请求量明显下降。"""
    cmp = extra.get("compare") or {}
    ratio = cmp.get("ratio")
    base = cmp.get("baseline_count") or 0
    if ratio is None or base < _threshold("OBS_TRAFFIC_DROP_MIN_BASELINE", 50):
        return None
    lim = _threshold("OBS_TRAFFIC_DROP_RATIO", 0.35)
    if ratio >= lim:
        return None
    return {
        "insight_type": "traffic_drop",
        "severity": "warning",
        "title": f"流量较上一时段下降约 {(1 - ratio) * 100:.0f}%",
        "body": "可能是发布回滚、DNS、限流或采集链路异常；请核对网关与业务指标。",
        "evidence": cmp,
    }


def detect_502_burst(summary: StreamSummary, extra: dict) -> Optional[dict]:
    """502/503 集中：网关与上游连不通的典型信号。"""
    paths = summary.top_paths_5xx
    if not paths:
        return None
    bad = [p for p in paths if p.get("count", 0) >= 5]
    if not bad:
        return None
    # 若只有 4xx 而无 5xx，top_paths_5xx 可能为空 — 本 detector 依赖 5xx 路径聚合
    return {
        "insight_type": "bad_gateway_cluster",
        "severity": "critical",
        "title": "5xx 路径集中，疑似网关或上游故障",
        "body": "多条路径出现较多 5xx，优先查 Nginx/upstream、Pod 就绪与依赖超时。",
        "evidence": {"paths": bad[:6]},
    }


_DETECTOR_REGISTRY: List[DetectorFn] = [
    detect_high_latency,
    detect_error_spike,
    detect_traffic_drop,
    detect_502_burst,
]


def register_detector(fn: DetectorFn) -> DetectorFn:
    """扩展点：在启动代码中 register_detector(my_fn)。"""
    _DETECTOR_REGISTRY.append(fn)
    return fn


def run_detectors(summary: StreamSummary) -> List[dict]:
    if getattr(settings, "OBSERVABILITY_DISABLE_DETECTORS", False):
        return []
    cmp = compare_windows(summary.stream_key, recent_m=15, baseline_m=15)
    extra = {"compare": cmp}
    out: List[dict] = []
    for det in _DETECTOR_REGISTRY:
        row = det(summary, extra)
        if row:
            out.append(row)
    return out

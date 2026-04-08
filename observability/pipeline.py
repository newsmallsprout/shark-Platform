"""同步执行：规则检测 + LLM 摘要 → LogInsight。"""

from __future__ import annotations

import logging

from .aggregate import summarize_stream
from .insights import run_detectors
from .llm_summary import summarize_with_llm
from .models import LogInsight

logger = logging.getLogger(__name__)


def run_observability_pipeline_impl(stream_key: str, window_minutes: int = 60) -> dict:
    sk = (stream_key or "").strip()[:128]
    if not sk:
        return {"ok": False, "error": "empty stream_key"}

    summary = summarize_stream(sk, window_minutes=window_minutes)
    hits = run_detectors(summary)
    window_start = summary.window_start
    window_end = summary.window_end

    created = 0
    for h in hits:
        LogInsight.objects.create(
            stream_key=sk,
            insight_type=h["insight_type"],
            severity=h.get("severity") or LogInsight.SEVERITY_WARN,
            title=h["title"][:500],
            body=h.get("body") or "",
            evidence=h.get("evidence") or {},
            window_start=window_start,
            window_end=window_end,
            source="detector",
        )
        created += 1

    llm_payload = summarize_with_llm(summary, hits)
    if llm_payload:
        sev = str(llm_payload.get("severity") or "info").lower()
        if sev not in ("info", "warning", "critical"):
            sev = "info"
        one = (llm_payload.get("one_liner") or "AI 摘要")[:500]
        body = "\n".join(
            [
                "【可能原因】" + "; ".join(llm_payload.get("likely_causes") or []),
                "【建议排查】" + "; ".join(llm_payload.get("checks") or []),
            ]
        )[:8000]
        LogInsight.objects.create(
            stream_key=sk,
            insight_type="ai_summary",
            severity=sev,
            title=one,
            body=body,
            evidence={
                "observations": llm_payload.get("observations"),
                "raw": llm_payload,
                "detector_count": len(hits),
            },
            window_start=window_start,
            window_end=window_end,
            source="llm",
        )
        created += 1

    logger.info("observability pipeline stream=%s insights=%s", sk, created)
    return {"ok": True, "stream_key": sk, "detector_hits": len(hits), "insights_created": created}

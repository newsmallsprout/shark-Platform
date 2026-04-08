"""
基于 AIConfig 的 OpenAI 兼容 Chat Completions，对聚合指标做根因假设与排查清单（无 tool 调用）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import requests
from django.conf import settings

from ai_ops.models import AIConfig

from .aggregate import StreamSummary

logger = logging.getLogger(__name__)


def summarize_with_llm(summary: StreamSummary, detector_hits: list[dict]) -> Optional[dict]:
    ai = AIConfig.get_active_config()
    if not ai.enable_ai_analysis or not (ai.api_key or "").strip():
        return None

    payload = {
        "summary": summary.to_dict(),
        "detector_hits": detector_hits[:12],
    }
    system = (
        "你是资深 SRE，根据 HTTP 访问日志聚合指标与规则告警，输出简短可执行结论。"
        " 使用中文。必须输出严格 JSON，字段："
        "observations(字符串数组), likely_causes(字符串数组), "
        "checks(字符串数组，具体排查步骤), severity(one of info|warning|critical), "
        "one_liner(一句话摘要)。不要 markdown。"
    )
    user = json.dumps(payload, ensure_ascii=False)[:12000]

    url = f"{ai.api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {ai.api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": ai.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": min(float(ai.temperature), 0.5),
        "max_tokens": min(int(ai.max_tokens), 2500),
    }
    timeout = int(getattr(settings, "OBSERVABILITY_LLM_TIMEOUT_SEC", 90))

    try:
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            i, j = text.find("{"), text.rfind("}")
            if i >= 0 and j > i:
                parsed = json.loads(text[i : j + 1])
            else:
                raise
        return parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("observability llm summary failed: %s", e)
        return None

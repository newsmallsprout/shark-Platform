# ============================================================
# security/agents/auto_scan/prompts.py — 提示词模板 (pentest 原样)
# ============================================================

from __future__ import annotations

ANALYZE_PROMPT = """你是一名世界级的渗透测试专家（OSCP/OSCE 认证级别）。

请分析以下安全扫描工具的原始输出，提取其中发现的所有安全漏洞。

## 工具输出
{tool_output}

## 要求
1. 只报告真实存在的漏洞，忽略误报
2. 每个漏洞需要包含以下字段：
   - title: 漏洞名称（中文，简洁）
   - severity: 严重等级（critical/high/medium/low/info）
   - type: 漏洞类型（如 sql_injection/xss/csrf/idor/rce/ssrf/info_disclosure）
   - endpoint: 漏洞所在 URL 或端点
   - method: HTTP 方法（GET/POST/PUT/DELETE，非 HTTP 则为空）
   - description: 漏洞详细描述
   - impact: 潜在影响
   - recommendation: 修复建议
   - cve: CVE 编号（如果有）
3. 以 JSON 数组格式输出，每项是一个漏洞对象
4. 如果没有发现漏洞，返回空数组 []

## 输出格式
```json
[
  {{
    "title": "...",
    "severity": "...",
    "type": "...",
    "endpoint": "...",
    "method": "...",
    "description": "...",
    "impact": "...",
    "recommendation": "...",
    "cve": null
  }}
]
```
"""

VERIFY_PROMPT = """你是一名渗透测试验证专家。

请验证以下疑似漏洞的真实性。如果无法确认，标记为需要人工审核。

## 漏洞信息
{vulnerability}

## 已知资产信息
{assets}

## 要求
1. 判断该漏洞是否为真实漏洞（true_positive / false_positive / needs_review）
2. 说明判断依据
3. 如果确认，提供复现步骤

## 输出格式
```json
{{
  "verdict": "true_positive|false_positive|needs_review",
  "confidence": 0.0-1.0,
  "reasoning": "...",
  "reproduction_steps": ["步骤1", "步骤2"]
}}
```
"""

#!/usr/bin/env python3
"""
独立 FastAPI SSE 服务：订阅 Redis ``agent:run:{run_id}``，将 JSON 事件推送给浏览器。

启动示例（默认端口 8010）::
    export CELERY_BROKER_URL=redis://localhost:6379/0
    uvicorn sse_server:app --host 0.0.0.0 --port 8010

与 Django 进程解耦；生产环境请在网关为该端口配置 CORS / 鉴权（本文件仅骨架）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sse_server")

REDIS_URL = os.environ.get("AGENT_EVENT_REDIS_URL") or os.environ.get(
    "CELERY_BROKER_URL", "redis://localhost:6379/0"
)
CORS_ORIGINS = os.environ.get("SSE_CORS_ORIGINS", "*").split(",")

app = FastAPI(title="Shark Agent SSE", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _channel(run_id: str) -> str:
    return f"agent:run:{run_id}"


async def _redis_event_stream(run_id: str) -> AsyncIterator[dict]:
    """阻塞监听 Pub/Sub，yield SSE 帧（data 为 JSON 字符串）。"""
    if not run_id or len(run_id) > 128:
        raise HTTPException(status_code=400, detail="invalid run_id")

    client = aioredis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5.0,
        socket_timeout=None,
    )
    pubsub = client.pubsub(ignore_subscribe_messages=False)
    ch = _channel(run_id)
    await pubsub.subscribe(ch)
    logger.info("SSE subscribed %s", ch)

    try:
        yield {"event": "ready", "data": json.dumps({"channel": ch}, ensure_ascii=False)}
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=3600.0)
            if msg is None:
                yield {
                    "event": "heartbeat",
                    "data": json.dumps({"ts": time.time()}, ensure_ascii=False),
                }
                continue
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if not isinstance(data, str):
                continue
            try:
                json.loads(data)
            except json.JSONDecodeError:
                data = json.dumps({"raw": data[:2000]}, ensure_ascii=False)
            yield {"event": "agent", "data": data}
    except asyncio.CancelledError:
        logger.info("SSE client disconnected run_id=%s", run_id)
        raise
    finally:
        try:
            await pubsub.unsubscribe(ch)
            await pubsub.close()
            await client.close()
        except Exception:
            logger.exception("redis cleanup failed")


@app.get("/api/agent/stream/{run_id}")
async def stream_agent_events(run_id: str):
    """浏览器 EventSource 指向此 URL；每条 agent 事件为一条 SSE message。"""
    return EventSourceResponse(_redis_event_stream(run_id))


@app.get("/healthz")
async def healthz():
    return {"ok": True, "redis_configured": bool(REDIS_URL)}

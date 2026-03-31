"""WebSocket endpoint for extraction pipeline progress per PRD Section 7.8.

Events: step_started, step_completed, step_failed, pipeline_paused, completed.
Uses in-memory event bus (asyncio.Queue) with event history replay for late
joiners. Redis Pub/Sub is Phase 6.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()

_run_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
_run_event_history: dict[str, list[dict[str, Any]]] = {}


def _get_subscribers(run_id: str) -> list[asyncio.Queue[dict[str, Any]]]:
    return _run_subscribers.setdefault(run_id, [])


async def publish_event(
    *,
    run_id: str,
    event_type: str,
    step: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Publish an event to all WebSocket subscribers for a run.

    Also stores in event history so late-connecting clients can replay.
    """
    event = {
        "type": event_type,
        "event": event_type,
        "step": step,
        "data": data or {},
        "timestamp": time.time(),
        "run_id": run_id,
    }

    _run_event_history.setdefault(run_id, []).append(event)

    subscribers = _get_subscribers(run_id)
    for queue in subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning(
                "WebSocket queue full, dropping event",
                extra={"run_id": run_id, "event": event_type},
            )


def cleanup_run(run_id: str) -> None:
    """Remove all subscribers and event history for a completed run."""
    _run_subscribers.pop(run_id, None)
    _run_event_history.pop(run_id, None)


@router.websocket("/ws/extraction/{run_id}")
async def ws_extraction(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time extraction pipeline updates.

    Replays any missed events on connect, then streams live updates.
    """
    await websocket.accept()
    log.info("WebSocket connected", extra={"run_id": run_id})

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    subscribers = _get_subscribers(run_id)
    subscribers.append(queue)

    try:
        await websocket.send_json({
            "type": "connected",
            "event": "connected",
            "step": "websocket",
            "data": {"run_id": run_id},
            "timestamp": time.time(),
        })

        # Replay missed events
        history = _run_event_history.get(run_id, [])
        for past_event in history:
            await websocket.send_json(past_event)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)

                if event.get("event") in ("completed", "failed"):
                    break
            except TimeoutError:
                await websocket.send_json({
                    "type": "heartbeat",
                    "event": "heartbeat",
                    "step": "websocket",
                    "data": {},
                    "timestamp": time.time(),
                })

    except WebSocketDisconnect:
        log.info("WebSocket disconnected", extra={"run_id": run_id})
    except Exception:
        log.exception("WebSocket error", extra={"run_id": run_id})
    finally:
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            cleanup_run(run_id)

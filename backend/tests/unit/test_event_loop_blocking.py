"""Guard the API against handlers that block the asyncio event loop.

Background
----------
Almost every route in this service does blocking python-arango I/O
against a remote cluster (~520ms per round trip). FastAPI runs an
``async def`` handler *on the event loop* and a plain ``def`` handler in
a worker thread, so an ``async def`` that blocks stalls every other
request in the process -- including the health probe.

Measured before the fix: one heavy request added 1.3s to ``/health``,
six concurrent ones added 5.7s, and an extraction dispatched as a
coroutine ``BackgroundTask`` held the loop for the whole run, which is
what made the server "listen but answer nothing".

The rule these tests encode: an ``async def`` handler must actually
``await`` something. If it does not, it gains nothing from being async
and can only block -- so it must be a plain ``def``.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import threading

import pytest

API_ROOT = pathlib.Path(__file__).resolve().parents[2] / "app" / "api"

# ``/health`` is deliberately async with no I/O: it answers off the loop
# so it can never queue behind the worker threads. See app/api/health.py.
_ALLOWED_AWAITLESS_ASYNC = {"health"}


def _is_router_decorator(node: ast.expr) -> bool:
    func = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "router"
    )


def _route_handlers() -> list[tuple[pathlib.Path, ast.AST]]:
    found: list[tuple[pathlib.Path, ast.AST]] = []
    for path in sorted(API_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                _is_router_decorator(d) for d in node.decorator_list
            ):
                found.append((path, node))
    return found


def test_no_async_route_handler_is_awaitless() -> None:
    """An ``async def`` route that awaits nothing must be a plain ``def``."""
    offenders = [
        f"{path.relative_to(API_ROOT.parent.parent)}:{node.lineno} {node.name}"
        for path, node in _route_handlers()
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name not in _ALLOWED_AWAITLESS_ASYNC
        and not any(isinstance(x, ast.Await) for x in ast.walk(node))
    ]
    assert not offenders, (
        "These async handlers await nothing, so they run blocking work on the "
        "event loop and stall every other request. Make them plain `def` -- "
        "FastAPI will then run them in the worker threadpool:\n  " + "\n  ".join(offenders)
    )


def test_route_handlers_are_predominantly_sync() -> None:
    """Sanity check that the conversion did not get reverted wholesale."""
    handlers = _route_handlers()
    sync = [n for _, n in handlers if isinstance(n, ast.FunctionDef)]
    assert len(handlers) > 100, "route discovery looks broken"
    assert len(sync) / len(handlers) > 0.8, (
        f"only {len(sync)}/{len(handlers)} handlers are sync; blocking DB "
        "handlers belong in the threadpool, not on the event loop"
    )


def test_coroutine_background_tasks_are_dispatched_through_the_thread_helper() -> None:
    """A coroutine handed to ``add_task`` runs on the loop -- wrap it.

    Starlette inspects the callable: a coroutine function is awaited on
    the event loop, a plain function is sent to the threadpool. The
    extraction pipeline is a coroutine that runs for minutes, so it must
    be dispatched via ``run_coroutine_in_thread``.
    """
    async_names: set[str] = set()
    for path in (API_ROOT.parent).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.AsyncFunctionDef):
                async_names.add(node.name)

    offenders: list[str] = []
    for path in sorted(API_ROOT.rglob("*.py")):
        src = path.read_text()
        for node in ast.walk(ast.parse(src)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_task"
                and node.args
            ):
                continue
            first = node.args[0]
            name = first.attr if isinstance(first, ast.Attribute) else getattr(first, "id", "")
            if name in async_names:
                offenders.append(f"{path.name}:{node.lineno} add_task({name})")

    assert not offenders, (
        "Coroutine background tasks run on the event loop and stall the "
        "server for their whole duration. Dispatch them as "
        "`add_task(run_coroutine_in_thread, the_coroutine_fn, ...)`:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.asyncio
async def test_run_coroutine_in_thread_executes_off_the_calling_loop() -> None:
    """The helper runs the coroutine to completion in its own loop."""
    from app.services.background import run_coroutine_in_thread

    caller_thread = threading.get_ident()
    seen: dict[str, object] = {}

    async def work(value: int) -> int:
        seen["thread"] = threading.get_ident()
        seen["loop"] = asyncio.get_running_loop()
        return value * 2

    calling_loop = asyncio.get_running_loop()
    result = await asyncio.to_thread(run_coroutine_in_thread, work, 21)

    assert result == 42
    assert seen["thread"] != caller_thread, "coroutine ran on the calling thread"
    assert seen["loop"] is not calling_loop, "coroutine ran on the request event loop"

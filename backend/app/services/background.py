"""Dispatch coroutine background work off the request event loop.

Starlette runs a ``BackgroundTasks`` entry *on the event loop* when the
callable is a coroutine function, and in a worker thread when it is a
plain ``def``.  The extraction pipeline is a coroutine that spends
minutes inside blocking python-arango calls, so adding it directly
starves every other request for the life of the run -- the server keeps
listening and answers nothing, ``/health`` included.

Wrapping it in a plain function makes Starlette choose the worker-thread
path; the coroutine then gets its own event loop inside that thread.
That is safe here because nothing in the pipeline shares a loop-bound
resource across calls (``embedding._get_client`` builds a fresh
``AsyncOpenAI`` per call rather than caching a module-level one).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


def run_coroutine_in_thread(
    coro_fn: Callable[..., Coroutine[Any, Any, Any]],
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run ``coro_fn(*args, **kwargs)`` to completion in the calling thread."""
    return asyncio.run(coro_fn(*args, **kwargs))

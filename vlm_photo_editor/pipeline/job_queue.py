"""Lightweight async job runner for blocking VLM and image processing calls.

Uses anyio.to_thread.run_sync() so blocking work runs in a worker thread,
keeping the async event loop responsive. Designed for P11 concurrency: multiple
jobs can be submitted inside an anyio task group without restructuring callers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio


async def _run_in_thread(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    on_progress: Callable[[float], None] | None,
) -> Any:
    result = await anyio.to_thread.run_sync(lambda: fn(*args))
    if on_progress is not None:
        on_progress(1.0)
    return result


def run_job(
    fn: Callable[..., Any],
    *args: Any,
    on_progress: Callable[[float], None] | None = None,
) -> Any:
    """Run *fn(*args)* in a worker thread via anyio. Blocks the caller until done.

    on_progress is called with 1.0 on completion. Extend for incremental updates
    by passing a progress queue from the worker thread.
    """
    return anyio.run(_run_in_thread, fn, args, on_progress)

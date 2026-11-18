"""Pytest configuration and pure in-memory coroutine event loop for offline test execution."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import heapq
import inspect
import queue
import time
import weakref
from typing import Any, Callable

import pytest


class InMemoryEventLoop(asyncio.AbstractEventLoop):
    """Pure-Python AbstractEventLoop backed by queue.Queue + heapq (requires zero OS sockets)."""

    def __init__(self) -> None:
        self._ready: queue.Queue[asyncio.Handle | None] = queue.Queue()
        self._scheduled: list[tuple[float, int, asyncio.TimerHandle]] = []
        self._seq = 0
        self._running = False
        self._closed = False
        self._debug = False
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._asyncgens: weakref.WeakSet[Any] = weakref.WeakSet()
        self._exception_handler: Callable[[asyncio.AbstractEventLoop, dict[str, Any]], None] | None = None
        self._task_factory: Callable[..., asyncio.Future[Any]] | None = None
        self._current_handle: asyncio.Handle | None = None

    def get_debug(self) -> bool:
        return self._debug

    def set_debug(self, enabled: bool) -> None:
        self._debug = bool(enabled)

    def is_running(self) -> bool:
        return self._running

    def is_closed(self) -> bool:
        return self._closed

    def time(self) -> float:
        return time.monotonic()

    def create_future(self) -> asyncio.Future[Any]:
        return asyncio.Future(loop=self)

    def create_task(self, coro: Any, *, name: str | None = None, context: Any = None) -> asyncio.Task[Any]:
        if self._task_factory is not None:
            if context is not None:
                task = self._task_factory(self, coro, context=context)
            else:
                task = self._task_factory(self, coro)
            if name is not None:
                try:
                    task.set_name(name)
                except AttributeError:
                    pass
            return task  # type: ignore[return-value]
        if context is not None:
            return asyncio.Task(coro, loop=self, name=name, context=context)
        return asyncio.Task(coro, loop=self, name=name)

    def get_task_factory(self) -> Any:
        return self._task_factory

    def set_task_factory(self, factory: Any) -> None:
        self._task_factory = factory

    def call_soon(
        self,
        callback: Callable[..., Any],
        *args: Any,
        context: contextvars.Context | None = None,
    ) -> asyncio.Handle:
        handle = asyncio.Handle(callback, args, self, context)
        self._ready.put(handle)
        return handle

    def call_soon_threadsafe(
        self,
        callback: Callable[..., Any],
        *args: Any,
        context: contextvars.Context | None = None,
    ) -> asyncio.Handle:
        handle = asyncio.Handle(callback, args, self, context)
        self._ready.put(handle)
        return handle

    def call_at(
        self,
        when: float,
        callback: Callable[..., Any],
        *args: Any,
        context: contextvars.Context | None = None,
    ) -> asyncio.TimerHandle:
        timer = asyncio.TimerHandle(when, callback, args, self, context)
        self._seq += 1
        heapq.heappush(self._scheduled, (when, self._seq, timer))
        self._ready.put(None)
        return timer

    def call_later(
        self,
        delay: float,
        callback: Callable[..., Any],
        *args: Any,
        context: contextvars.Context | None = None,
    ) -> asyncio.TimerHandle:
        return self.call_at(self.time() + max(0.0, float(delay)), callback, *args, context=context)

    def _timer_handle_cancelled(self, handle: asyncio.TimerHandle) -> None:
        pass

    def run_in_executor(
        self,
        executor: concurrent.futures.Executor | None,
        func: Callable[..., Any],
        *args: Any,
    ) -> asyncio.Future[Any]:
        if executor is None:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
            executor = self._executor
        return asyncio.wrap_future(executor.submit(func, *args), loop=self)

    def set_default_executor(self, executor: Any) -> None:
        self._executor = executor

    def get_exception_handler(self) -> Any:
        return self._exception_handler

    def set_exception_handler(self, handler: Any) -> None:
        self._exception_handler = handler

    def default_exception_handler(self, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if exc is not None:
            raise exc

    def call_exception_handler(self, context: dict[str, Any]) -> None:
        if self._exception_handler is not None:
            self._exception_handler(self, context)
        else:
            self.default_exception_handler(context)

    def _asyncgen_firstiter_hook(self, agen: Any) -> None:
        self._asyncgens.add(agen)

    def _asyncgen_finalizer_hook(self, agen: Any) -> None:
        self._asyncgens.discard(agen)
        self.create_task(agen.aclose())

    async def shutdown_asyncgens(self) -> None:
        closing = list(self._asyncgens)
        self._asyncgens.clear()
        if closing:
            await asyncio.gather(*(ag.aclose() for ag in closing), return_exceptions=True)

    async def shutdown_default_executor(self, timeout: float | None = None) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None

    def run_until_complete(self, future: Any) -> Any:
        fut = asyncio.ensure_future(future, loop=self)
        self._running = True
        asyncio.events._set_running_loop(self)
        try:
            while not fut.done():
                now = self.time()
                while self._scheduled and self._scheduled[0][0] <= now:
                    _, _, timer = heapq.heappop(self._scheduled)
                    if not timer._cancelled:
                        self._ready.put(timer)

                timeout: float | None = None
                if self._scheduled:
                    timeout = max(0.0, self._scheduled[0][0] - self.time())
                else:
                    timeout = 0.05

                try:
                    item = self._ready.get(timeout=timeout)
                except queue.Empty:
                    continue

                batch = [item]
                while True:
                    try:
                        batch.append(self._ready.get_nowait())
                    except queue.Empty:
                        break

                for handle in batch:
                    if handle is not None and not handle._cancelled:
                        self._current_handle = handle
                        handle._run()
                        self._current_handle = None
            return fut.result()
        finally:
            self._running = False
            asyncio.events._set_running_loop(None)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._closed = True


def run_in_memory(coro: Any) -> Any:
    loop = InMemoryEventLoop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(coro)
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        return res
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        funcargs = pyfuncitem.funcargs
        testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
        run_in_memory(pyfuncitem.obj(**testargs))
        return True
    return None

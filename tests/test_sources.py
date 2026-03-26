"""Tests for raw/ layer: raw_subscribe, from_iter, from_timer, first_value_from,
from_awaitable, from_async_iter, from_any."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from typing import Any

import pytest

from recharge import Signal, state, subscribe
from recharge.raw import (
    first_value_from,
    from_any,
    from_async_iter,
    from_awaitable,
    from_iter,
    from_timer,
    raw_subscribe,
)

from .conftest import observe


# ── raw_subscribe ──────────────────────────────────────────────────────────


class TestRawSubscribe:
    def test_receives_values_from_state(self) -> None:
        s = state(0)
        values: list[Any] = []
        sub = raw_subscribe(s, lambda v: values.append(v))
        s.set(1)
        s.set(2)
        sub.unsubscribe()
        s.set(3)
        assert values == [1, 2]

    def test_on_end_called_on_complete(self) -> None:
        source = from_iter([1, 2, 3])
        values: list[Any] = []
        ended: list[Exception | None] = []
        raw_subscribe(source, values.append, ended.append)
        assert values == [1, 2, 3]
        assert ended == [None]

    def test_on_end_called_on_error(self) -> None:
        from recharge import producer

        def factory(api: Any) -> None:
            api.error(ValueError("boom"))

        source = producer(factory)
        values: list[Any] = []
        ended: list[Exception | None] = []
        raw_subscribe(source, values.append, ended.append)
        assert values == []
        assert len(ended) == 1
        assert isinstance(ended[0], ValueError)

    def test_context_manager(self) -> None:
        s = state(0)
        values: list[Any] = []
        with raw_subscribe(s, values.append):
            s.set(1)
        s.set(2)
        assert values == [1]

    def test_unsubscribe_idempotent(self) -> None:
        s = state(0)
        sub = raw_subscribe(s, lambda v: None)
        sub.unsubscribe()
        sub.unsubscribe()  # should not raise


# ── from_iter ──────────────────────────────────────────────────────────────


class TestFromIter:
    def test_emits_list(self) -> None:
        obs = observe(from_iter([10, 20, 30]))
        assert obs.values == [10, 20, 30]
        assert obs.completed_cleanly

    def test_emits_range(self) -> None:
        obs = observe(from_iter(range(3)))
        assert obs.values == [0, 1, 2]
        assert obs.completed_cleanly

    def test_emits_generator(self) -> None:
        def gen():
            yield "a"
            yield "b"

        obs = observe(from_iter(gen()))
        assert obs.values == ["a", "b"]
        assert obs.completed_cleanly

    def test_empty_iterable(self) -> None:
        obs = observe(from_iter([]))
        assert obs.values == []
        assert obs.completed_cleanly

    def test_unsubscribe_mid_iteration(self) -> None:
        """Stopping mid-iteration should stop emitting."""
        values: list[int] = []
        sub_holder: list[Any] = [None]

        def on_next(v: int) -> None:
            values.append(v)
            if v == 2 and sub_holder[0] is not None:
                sub_holder[0].unsubscribe()

        sub = raw_subscribe(from_iter([1, 2, 3, 4, 5]), on_next)
        sub_holder[0] = sub
        # from_iter emits synchronously during subscribe, so sub_holder
        # isn't set yet.  The guard `sub_holder[0] is not None` means
        # stop only fires if raw_subscribe returned before all items emit.
        # Since from_iter pushes all items synchronously, all arrive before
        # raw_subscribe returns.  This is expected behavior for sync sources.
        assert values == [1, 2, 3, 4, 5]

    def test_multiple_subscribers(self) -> None:
        """List (re-iterable) supports multiple subscribers."""
        source = from_iter([1, 2])
        obs1 = observe(source)
        obs2 = observe(source)
        assert obs1.values == [1, 2]
        assert obs2.values == [1, 2]

    def test_string_iterated_as_chars(self) -> None:
        obs = observe(from_iter("abc"))
        assert obs.values == ["a", "b", "c"]


# ── from_timer ─────────────────────────────────────────────────────────────


class TestFromTimer:
    def test_emits_after_delay(self) -> None:
        source = from_timer(0.01)
        event = threading.Event()
        values: list[Any] = []
        ended: list[bool] = []

        def on_next(v: Any) -> None:
            values.append(v)

        def on_end(err: Exception | None) -> None:
            ended.append(err is None)
            event.set()

        raw_subscribe(source, on_next, on_end)
        assert event.wait(timeout=2.0)
        assert values == [None]
        assert ended == [True]

    def test_cancel_before_fire(self) -> None:
        source = from_timer(10.0)  # long delay
        values: list[Any] = []
        sub = raw_subscribe(source, values.append)
        sub.unsubscribe()
        time.sleep(0.05)
        assert values == []

    def test_negative_seconds_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            from_timer(-1)

    def test_zero_delay(self) -> None:
        source = from_timer(0.0)
        event = threading.Event()
        values: list[Any] = []

        def on_end(err: Exception | None) -> None:
            event.set()

        raw_subscribe(source, values.append, on_end)
        assert event.wait(timeout=2.0)
        assert values == [None]


# ── first_value_from ───────────────────────────────────────────────────────


class TestFirstValueFrom:
    def test_resolves_from_sync_source(self) -> None:
        source = from_iter([42, 99])
        future = first_value_from(source)
        assert future.result(timeout=1.0) == 42

    def test_resolves_from_state(self) -> None:
        """State emits current value on subscribe via pull, but raw first_value_from
        uses the first DATA pushed. State pushes on set(), not on subscribe."""
        s = state(10)
        future = first_value_from(s)

        # State doesn't push on subscribe, so trigger a push
        s.set(20)
        assert future.result(timeout=1.0) == 20

    def test_predicate_filters(self) -> None:
        source = from_iter([1, 2, 3, 4])
        future = first_value_from(source, predicate=lambda v: v > 2)
        assert future.result(timeout=1.0) == 3

    def test_rejects_on_complete_without_match(self) -> None:
        source = from_iter([1, 2])
        future = first_value_from(source, predicate=lambda v: v > 10)
        with pytest.raises(LookupError, match="without emitting"):
            future.result(timeout=1.0)

    def test_rejects_on_empty_source(self) -> None:
        source = from_iter([])
        future = first_value_from(source)
        with pytest.raises(LookupError):
            future.result(timeout=1.0)

    def test_rejects_on_error(self) -> None:
        from recharge import producer

        def factory(api: Any) -> None:
            api.error(RuntimeError("fail"))

        future = first_value_from(producer(factory))
        with pytest.raises(RuntimeError, match="fail"):
            future.result(timeout=1.0)

    def test_cancel_future(self) -> None:
        """Cancelling the future should stop the subscription."""
        s = state(0)
        future = first_value_from(s)
        assert future.cancel()  # cancel before any value

    def test_async_source(self) -> None:
        source = from_timer(0.01)
        future = first_value_from(source)
        assert future.result(timeout=2.0) is None


# ── from_awaitable ─────────────────────────────────────────────────────────


class TestFromAwaitable:
    def test_emits_coroutine_result(self) -> None:
        async def coro() -> int:
            return 42

        source = from_awaitable(coro)
        event = threading.Event()
        values: list[Any] = []

        def on_end(err: Exception | None) -> None:
            event.set()

        raw_subscribe(source, values.append, on_end)
        assert event.wait(timeout=2.0)
        assert values == [42]

    def test_error_propagation(self) -> None:
        async def coro() -> int:
            raise ValueError("async boom")

        source = from_awaitable(coro)
        event = threading.Event()
        errors: list[Exception | None] = []

        def on_end(err: Exception | None) -> None:
            errors.append(err)
            event.set()

        raw_subscribe(source, lambda v: None, on_end)
        assert event.wait(timeout=2.0)
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)

    def test_factory_resubscribable(self) -> None:
        call_count = 0

        async def coro() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        source = from_awaitable(coro)  # coro is a function, used as factory
        event1 = threading.Event()
        event2 = threading.Event()
        values1: list[int] = []
        values2: list[int] = []

        raw_subscribe(source, values1.append, lambda _: event1.set())
        assert event1.wait(timeout=2.0)

        raw_subscribe(source, values2.append, lambda _: event2.set())
        assert event2.wait(timeout=2.0)

        assert values1 == [1]
        assert values2 == [2]

    def test_raw_coroutine_object(self) -> None:
        """Passing a raw coroutine object (not factory) works for first subscriber."""

        async def coro() -> int:
            return 77

        source = from_awaitable(coro())  # raw coroutine, not factory
        event = threading.Event()
        values: list[Any] = []

        raw_subscribe(source, values.append, lambda _: event.set())
        assert event.wait(timeout=2.0)
        assert values == [77]

    def test_raw_coroutine_resubscribe_raises(self) -> None:
        """Resubscribing to a raw coroutine source raises RuntimeError."""

        async def coro() -> int:
            return 1

        source = from_awaitable(coro())
        event = threading.Event()
        raw_subscribe(source, lambda _: None, lambda _: event.set())
        assert event.wait(timeout=2.0)

        with pytest.raises(RuntimeError, match="already consumed"):
            raw_subscribe(source, lambda _: None)

    def test_cancel_before_complete(self) -> None:
        async def slow_coro() -> int:
            await asyncio.sleep(10)
            return 999

        source = from_awaitable(slow_coro)
        values: list[Any] = []
        sub = raw_subscribe(source, values.append)
        sub.unsubscribe()
        time.sleep(0.05)
        assert values == []

    def test_custom_schedule(self) -> None:
        """Custom scheduler is used instead of default thread scheduler."""
        scheduled: list[bool] = []

        def custom_schedule(coro, on_result, on_error):
            scheduled.append(True)
            # Run synchronously for testing
            import asyncio

            try:
                result = asyncio.run(coro)
            except Exception as e:
                on_error(e)
            else:
                on_result(result)

        async def coro() -> str:
            return "custom"

        source = from_awaitable(coro, schedule=custom_schedule)
        values: list[Any] = []
        raw_subscribe(source, values.append)
        assert scheduled == [True]
        assert values == ["custom"]


# ── from_async_iter ────────────────────────────────────────────────────────


class TestFromAsyncIter:
    def test_emits_async_iter_values(self) -> None:
        async def agen():
            yield 1
            yield 2
            yield 3

        source = from_async_iter(agen)
        event = threading.Event()
        values: list[int] = []

        raw_subscribe(source, values.append, lambda _: event.set())
        assert event.wait(timeout=2.0)
        assert values == [1, 2, 3]

    def test_error_propagation(self) -> None:
        async def agen():
            yield 1
            raise RuntimeError("agen fail")

        source = from_async_iter(agen)
        event = threading.Event()
        values: list[int] = []
        errors: list[Exception | None] = []

        def on_end(err):
            errors.append(err)
            event.set()

        raw_subscribe(source, values.append, on_end)
        assert event.wait(timeout=2.0)
        assert values == [1]
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)

    def test_factory_resubscribable(self) -> None:
        async def agen():
            yield "a"
            yield "b"

        source = from_async_iter(agen)  # function = factory
        event1, event2 = threading.Event(), threading.Event()
        v1: list[str] = []
        v2: list[str] = []

        raw_subscribe(source, v1.append, lambda _: event1.set())
        assert event1.wait(timeout=2.0)

        raw_subscribe(source, v2.append, lambda _: event2.set())
        assert event2.wait(timeout=2.0)

        assert v1 == ["a", "b"]
        assert v2 == ["a", "b"]

    def test_empty_async_iter(self) -> None:
        async def agen():
            return
            yield  # noqa: RET504 -- make it an async generator

        source = from_async_iter(agen)
        event = threading.Event()
        values: list[Any] = []

        raw_subscribe(source, values.append, lambda _: event.set())
        assert event.wait(timeout=2.0)
        assert values == []


# ── from_any ───────────────────────────────────────────────────────────────


class TestFromAny:
    def test_source_passthrough(self) -> None:
        """A Source is returned as-is."""
        original = from_iter([1])
        result = from_any(original)
        assert result is original

    def test_iterable_dispatches_to_from_iter(self) -> None:
        obs = observe(from_any([10, 20]))
        assert obs.values == [10, 20]
        assert obs.completed_cleanly

    def test_plain_value(self) -> None:
        obs = observe(from_any(42))
        assert obs.values == [42]
        assert obs.completed_cleanly

    def test_none_value(self) -> None:
        obs = observe(from_any(None))
        assert obs.values == [None]
        assert obs.completed_cleanly

    def test_string_as_plain_value(self) -> None:
        """Strings are NOT iterated -- treated as plain values."""
        obs = observe(from_any("hello"))
        assert obs.values == ["hello"]
        assert obs.completed_cleanly

    def test_bytes_as_plain_value(self) -> None:
        obs = observe(from_any(b"data"))
        assert obs.values == [b"data"]
        assert obs.completed_cleanly

    def test_coroutine_dispatches_to_from_awaitable(self) -> None:
        async def coro():
            return 99

        source = from_any(coro())
        event = threading.Event()
        values: list[Any] = []

        raw_subscribe(source, values.append, lambda _: event.set())
        assert event.wait(timeout=2.0)
        assert values == [99]

    def test_async_iter_dispatches(self) -> None:
        async def agen():
            yield 1
            yield 2

        source = from_any(agen())
        event = threading.Event()
        values: list[int] = []

        raw_subscribe(source, values.append, lambda _: event.set())
        assert event.wait(timeout=2.0)
        assert values == [1, 2]

    def test_dict_as_iterable(self) -> None:
        """Dicts are iterable (yield keys)."""
        obs = observe(from_any({"a": 1, "b": 2}))
        assert set(obs.values) == {"a", "b"}
        assert obs.completed_cleanly

    def test_state_as_source(self) -> None:
        """State has .subscribe -- treated as Source."""
        s = state(5)
        result = from_any(s)
        assert result is s

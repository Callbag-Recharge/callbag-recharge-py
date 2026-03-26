"""Concurrency tests: lock-free get() safety under concurrent access."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from recharge import derived, effect, state


def _runtime_mode() -> str:
    """Return interpreter threading mode for test diagnostics."""
    is_gil_enabled: Callable[[], bool] | None = getattr(sys, "_is_gil_enabled", None)
    if is_gil_enabled is None:
        return "gil"
    return "gil" if is_gil_enabled() else "free-threaded"


def test_concurrent_derived_get_under_writes() -> None:
    """Derived get() stays lock-free and value-consistent under write pressure."""
    s = state(0)
    doubled = derived([s], lambda: s.get() * 2)
    dispose = effect([doubled], lambda: None)  # Keep derived push-connected.

    errors: list[BaseException] = []
    error_lock = threading.Lock()
    done = threading.Event()

    def record_error(err: BaseException) -> None:
        with error_lock:
            errors.append(err)
        done.set()

    def reader() -> None:
        try:
            for _ in range(25_000):
                if done.is_set():
                    return
                value = doubled.get()
                # Invariant: f(x) = x * 2, so every observed value must be even.
                if value % 2 != 0:
                    raise AssertionError(f"expected even derived value, got {value}")
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    def writer() -> None:
        try:
            for i in range(5_000):
                if done.is_set():
                    return
                s.set(i)
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    readers = [threading.Thread(target=reader) for _ in range(6)]
    writers = [threading.Thread(target=writer) for _ in range(2)]
    all_threads = readers + writers
    try:
        for thread in all_threads:
            thread.start()
        for thread in all_threads:
            thread.join(timeout=5.0)
        stuck = [thread.name for thread in all_threads if thread.is_alive()]
        if stuck:
            done.set()
            raise AssertionError(f"worker threads did not finish: {stuck}")
    finally:
        done.set()
        dispose()
    assert not errors, f"concurrency invariant failed in {_runtime_mode()} mode: {errors!r}"


def test_concurrent_state_get_under_writes() -> None:
    """State get() is safe and lock-free while other threads write."""
    s = state(0)
    errors: list[BaseException] = []
    error_lock = threading.Lock()
    done = threading.Event()

    def record_error(err: BaseException) -> None:
        with error_lock:
            errors.append(err)
        done.set()

    max_written = 9_999

    def reader() -> None:
        try:
            for _ in range(40_000):
                if done.is_set():
                    return
                value = s.get()
                if not isinstance(value, int):
                    raise AssertionError(f"expected int state value, got {type(value)!r}")
                if value < 0 or value > max_written:
                    raise AssertionError(f"state value out of expected range: {value}")
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    def writer() -> None:
        try:
            for i in range(10_000):
                if done.is_set():
                    return
                s.set(i)
        except BaseException as err:  # pragma: no cover - only for stress failures
            record_error(err)

    readers = [threading.Thread(target=reader) for _ in range(8)]
    writer_thread = threading.Thread(target=writer)
    all_threads = readers + [writer_thread]
    for thread in readers:
        thread.start()
    writer_thread.start()
    for thread in all_threads:
        thread.join(timeout=5.0)
    stuck = [thread.name for thread in all_threads if thread.is_alive()]
    if stuck:
        done.set()
        raise AssertionError(f"worker threads did not finish: {stuck}")

    final_value = s.get()
    if final_value < 0 or final_value > max_written:
        raise AssertionError(f"final state value out of expected range: {final_value}")
    assert not errors, f"lock-free state.get() failed in {_runtime_mode()} mode: {errors!r}"

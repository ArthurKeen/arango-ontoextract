"""The snapshot cache is shared across worker threads -- prove it holds.

Route handlers are plain ``def``, so FastAPI serves them from a worker
threadpool (100 wide). Several requests can therefore touch the module-level
snapshot cache at the same instant, which was impossible when every handler
ran on the single event loop.

Single-key dict operations are atomic under the GIL, but
``invalidate_snapshot_cache`` iterates the dict, and a concurrent
``_snapshot_cache_put`` during that iteration raises
``RuntimeError: dictionary changed size during iteration``. Invalidation
runs on *every* ontology write while any read repopulates the cache, so
this is an ordinary two-user collision, not an exotic one.
"""

from __future__ import annotations

import threading

from app.services import temporal


def test_invalidate_survives_concurrent_writes() -> None:
    """Hammer put() while invalidate() iterates; neither may raise.

    The cache is pre-filled and the writers store a *different*
    ontology_id, so entries accumulate and the iteration inside
    ``invalidate_snapshot_cache`` is long enough to be preempted --
    which is what makes the collision reachable. (A test where
    invalidation empties the dict every pass iterates something almost
    empty, finishes inside a single GIL slice, and never trips.)
    """
    temporal._snapshot_cache.clear()
    for i in range(2000):
        temporal._snapshot_cache_put(f"seed-{i}", {"ontology_id": "onto-1"})

    errors: list[BaseException] = []
    stop = threading.Event()

    def writer(worker: int) -> None:
        try:
            i = 0
            while not stop.is_set():
                # a different ontology_id, so invalidation never reaps these
                temporal._snapshot_cache_put(f"w{worker}-{i}", {"ontology_id": "onto-2"})
                i += 1
        except BaseException as exc:
            errors.append(exc)

    def invalidator() -> None:
        try:
            for _ in range(200):
                temporal.invalidate_snapshot_cache("onto-1")
                # re-seed so there is always something to iterate over
                for i in range(200):
                    temporal._snapshot_cache_put(f"seed-{i}", {"ontology_id": "onto-1"})
        except BaseException as exc:
            errors.append(exc)

    writers = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
    for t in writers:
        t.start()
    inv = threading.Thread(target=invalidator)
    inv.start()
    inv.join(timeout=60)
    stop.set()
    for t in writers:
        t.join(timeout=60)

    temporal._snapshot_cache.clear()
    assert not errors, f"concurrent cache access raised: {errors[0]!r}"


def test_invalidate_removes_only_the_named_ontology() -> None:
    """The lock must not change what invalidation actually does."""
    temporal._snapshot_cache.clear()
    temporal._snapshot_cache_put("a", {"ontology_id": "keep"})
    temporal._snapshot_cache_put("b", {"ontology_id": "drop"})
    temporal._snapshot_cache_put("c", {"ontology_id": "drop"})

    assert temporal.invalidate_snapshot_cache("drop") == 2
    assert temporal._snapshot_cache_get("a") == {"ontology_id": "keep"}
    assert temporal._snapshot_cache_get("b") is None
    assert temporal._snapshot_cache_get("c") is None


def test_concurrent_readers_and_writers_do_not_corrupt_entries() -> None:
    """A value read back must be exactly what some writer stored."""
    temporal._snapshot_cache.clear()
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        try:
            i = 0
            while not stop.is_set():
                temporal._snapshot_cache_put("shared", {"ontology_id": "o", "n": i})
                i += 1
        except BaseException as exc:
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(2000):
                got = temporal._snapshot_cache_get("shared")
                if got is not None:
                    assert set(got) == {"ontology_id", "n"}
        except BaseException as exc:
            errors.append(exc)

    w = threading.Thread(target=writer)
    w.start()
    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()
    for t in readers:
        t.join(timeout=30)
    stop.set()
    w.join(timeout=30)

    assert not errors, f"concurrent read/write raised: {errors[0]!r}"

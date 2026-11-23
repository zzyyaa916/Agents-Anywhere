from __future__ import annotations

import asyncio
import time

import pytest

from agent_server.infra.fs_downloads import (
    TRANSFER_QUEUE_CHUNKS,
    FsDownloadRelayManager,
)


async def _transfer(manager):
    return await manager.create(
        connector_id="conn_1",
        root="/repo",
        path="/repo/file.txt",
        name="file.txt",
        size=12,
        sha256="abc",
        media_type="text/plain",
    )


@pytest.mark.parametrize("ending", ["download_closed", "expired", "deadline"])
def test_local_upload_exits_when_full_queue_transfer_ends(ending):
    async def exercise():
        now = [0.0]
        manager = FsDownloadRelayManager(
            ttl_seconds=0.05 if ending == "deadline" else 300,
            clock=time.monotonic if ending == "deadline" else lambda: now[0],
        )
        transfer = await _transfer(manager)
        stream = manager.stream(transfer_id=transfer.transfer_id, token=transfer.token)
        await transfer.queue.put(b"a")
        assert await anext(stream) == b"a"
        blocked = asyncio.Event()

        async def chunks():
            for index in range(TRANSFER_QUEUE_CHUNKS + 1):
                if index == TRANSFER_QUEUE_CHUNKS:
                    blocked.set()
                yield b"b"

        task = asyncio.create_task(
            manager.upload(
                transfer_id=transfer.transfer_id,
                token=transfer.token,
                chunks=chunks(),
            )
        )
        try:
            await asyncio.wait_for(blocked.wait(), timeout=1)
            assert transfer.queue.full()
            assert not task.done()
            if ending == "download_closed":
                await stream.aclose()
            elif ending == "expired":
                now[0] = 301
                manager.expire()
            assert await asyncio.wait_for(task, timeout=1) is False
            if ending != "deadline":
                assert await manager.get(transfer.transfer_id, transfer.token) is None
        finally:
            await stream.aclose()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_local_upload_keeps_backpressure_and_completes_without_data_loss():
    async def exercise():
        manager = FsDownloadRelayManager()
        transfer = await _transfer(manager)
        blocked = asyncio.Event()
        expected = [bytes([index]) for index in range(12)]

        async def chunks():
            for index, chunk in enumerate(expected):
                if index == TRANSFER_QUEUE_CHUNKS:
                    blocked.set()
                yield chunk

        task = asyncio.create_task(
            manager.upload(
                transfer_id=transfer.transfer_id,
                token=transfer.token,
                chunks=chunks(),
            )
        )
        try:
            await asyncio.wait_for(blocked.wait(), timeout=1)
            assert transfer.queue.qsize() == TRANSFER_QUEUE_CHUNKS
            assert not task.done()
            received = [
                chunk
                async for chunk in manager.stream(
                    transfer_id=transfer.transfer_id,
                    token=transfer.token,
                )
            ]
            assert await asyncio.wait_for(task, timeout=1) is True
            assert received == expected
            assert await manager.get(transfer.transfer_id, transfer.token) is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_local_upload_error_does_not_hang_after_consumer_closes():
    async def exercise():
        manager = FsDownloadRelayManager()
        transfer = await _transfer(manager)
        stream = manager.stream(transfer_id=transfer.transfer_id, token=transfer.token)
        await transfer.queue.put(b"a")
        assert await anext(stream) == b"a"
        failed = asyncio.Event()

        async def chunks():
            for _ in range(TRANSFER_QUEUE_CHUNKS):
                yield b"b"
            failed.set()
            raise ValueError("upload failed")

        task = asyncio.create_task(
            manager.upload(
                transfer_id=transfer.transfer_id,
                token=transfer.token,
                chunks=chunks(),
            )
        )
        try:
            await asyncio.wait_for(failed.wait(), timeout=1)
            assert transfer.queue.full()
            await stream.aclose()
            with pytest.raises(ValueError, match="upload failed"):
                await asyncio.wait_for(task, timeout=1)
        finally:
            await stream.aclose()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_cancelling_local_upload_leaves_no_queue_waiters():
    async def exercise():
        manager = FsDownloadRelayManager()
        transfer = await _transfer(manager)
        for _ in range(TRANSFER_QUEUE_CHUNKS):
            transfer.queue.put_nowait(b"a")
        started = asyncio.Event()

        async def chunks():
            started.set()
            yield b"b"

        task = asyncio.create_task(
            manager.upload(
                transfer_id=transfer.transfer_id,
                token=transfer.token,
                chunks=chunks(),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not [
            task for task in asyncio.all_tasks() if task is not asyncio.current_task()
        ]

    asyncio.run(exercise())


class _FlakyBlpopRedis:
    """FakeRedis whose BLPOP first fails like a socket read timeout, then returns empty."""

    def __init__(self, client, *, timeouts: int, empty: int = 0) -> None:
        self._client = client
        self.timeouts_left = timeouts
        self.empty_left = empty
        self.blpop_timeouts: list[float] = []
        self.misses = asyncio.Event()

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def blpop(self, key, timeout=0):
        from redis.exceptions import TimeoutError as RedisTimeoutError

        self.blpop_timeouts.append(timeout)
        if self.timeouts_left:
            self.timeouts_left -= 1
            if not self.timeouts_left and not self.empty_left:
                self.misses.set()
            raise RedisTimeoutError("Timeout reading from redis:6379")
        if self.empty_left:
            self.empty_left -= 1
            if not self.empty_left:
                self.misses.set()
            return None
        return await self._client.blpop(key, timeout=timeout)


@pytest.mark.parametrize(("timeouts", "empty"), [(2, 0), (2, 1)])
def test_distributed_stream_waits_through_redis_read_timeouts(timeouts, empty):
    """Regression: a Redis read timeout must not end the stream or drop the transfer.

    Before the fix the first TimeoutError escaped stream() after the response had
    started, and its cleanup deleted the transfer so the late upload was rejected.
    """
    from fakeredis import FakeServer
    from fakeredis.aioredis import FakeRedis

    from agent_server.infra.redis_coordinator import RedisCoordinator

    async def exercise():
        server = FakeServer()
        flaky = _FlakyBlpopRedis(
            FakeRedis(server=server, decode_responses=True),
            timeouts=timeouts,
            empty=empty,
        )
        consumer = FsDownloadRelayManager(
            RedisCoordinator(prefix="test-fs", client=flaky)
        )
        uploader = FsDownloadRelayManager(
            RedisCoordinator(
                prefix="test-fs",
                client=FakeRedis(server=server, decode_responses=True),
            )
        )
        transfer = await _transfer(consumer)
        received: list[bytes] = []

        async def consume():
            async for chunk in consumer.stream(
                transfer_id=transfer.transfer_id, token=transfer.token
            ):
                received.append(chunk)

        stream_task = asyncio.create_task(consume())
        # The upload arrives only after the stream has already hit the timeouts.
        await asyncio.wait_for(flaky.misses.wait(), timeout=5)
        assert not stream_task.done()

        async def chunks():
            yield b"hello "
            yield b"world!"

        uploaded = await uploader.upload(
            transfer_id=transfer.transfer_id, token=transfer.token, chunks=chunks()
        )
        await asyncio.wait_for(stream_task, timeout=5)

        assert uploaded is True  # the late upload is accepted (the API's 404 path)
        assert b"".join(received) == b"hello world!"
        assert all(0 < wait <= 5 for wait in flaky.blpop_timeouts)
        # Normal completion still cleans the transfer up.
        assert await consumer.get(transfer.transfer_id, transfer.token) is None
        assert not await flaky.exists(
            consumer._metadata_key(transfer.transfer_id),
            consumer._queue_key(transfer.transfer_id),
        )

    asyncio.run(exercise())


def test_distributed_stream_still_ends_and_cleans_up_at_ttl():
    from fakeredis import FakeServer
    from fakeredis.aioredis import FakeRedis

    from agent_server.infra.redis_coordinator import RedisCoordinator

    async def exercise():
        now = [0.0]
        flaky = _FlakyBlpopRedis(
            FakeRedis(server=FakeServer(), decode_responses=True), timeouts=0
        )
        manager = FsDownloadRelayManager(
            RedisCoordinator(prefix="test-fs", client=flaky),
            ttl_seconds=30,
            clock=lambda: now[0],
        )
        transfer = await _transfer(manager)
        real_blpop = flaky.blpop

        async def advancing_blpop(key, timeout=0):
            now[0] += timeout  # each empty poll consumes its wait
            return await real_blpop(key, timeout=0.01)

        flaky.blpop = advancing_blpop
        received = [
            chunk
            async for chunk in manager.stream(
                transfer_id=transfer.transfer_id, token=transfer.token
            )
        ]
        assert received == []
        assert flaky.blpop_timeouts  # polled several times rather than once for the TTL
        assert len(flaky.blpop_timeouts) >= 6
        assert not await flaky.exists(manager._metadata_key(transfer.transfer_id))

    asyncio.run(exercise())

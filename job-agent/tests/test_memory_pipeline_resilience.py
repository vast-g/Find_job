"""Pipeline request isolation and recovery, without Redis, SQL, or model calls."""
import asyncio
import unittest
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.pipeline import AgentPipeline
from app.memory.errors import SessionBusyError
from app.memory.memory_store import InMemoryMessageStore


class TracerStub:
    def __init__(self, *args):
        pass

    @asynccontextmanager
    async def step(self, *args, **kwargs):
        yield


class MemoryPipelineResilienceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = InMemoryMessageStore(max_turns=30)
        self.settings = SimpleNamespace(memory_request_timeout=180, summary_interval=5)
        self.profiles = AsyncMock()
        self.profiles.get.return_value = None
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch("app.core.pipeline.get_memory_store", return_value=self.store))
        self.patches.enter_context(patch("app.core.pipeline.get_settings", return_value=self.settings))
        self.patches.enter_context(patch("app.core.pipeline.ProfileRepository", return_value=self.profiles))
        self.patches.enter_context(patch("app.core.pipeline.Tracer", TracerStub))
        self.patches.enter_context(patch("app.core.pipeline.recognize_intent", new=AsyncMock(return_value={"intent": "qa"})))
        self.summarize = self.patches.enter_context(patch("app.core.pipeline.maybe_summarize", new=AsyncMock(return_value=None)))

    def pipeline(self):
        pipeline = AgentPipeline(AsyncMock())
        pipeline._run_react = AsyncMock(return_value="generated answer")
        return pipeline

    async def pending(self, coroutine):
        task = asyncio.create_task(coroutine)

        async def cancel():
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.addAsyncCleanup(cancel)
        return task

    async def reached(self, event):
        await asyncio.wait_for(event.wait(), timeout=2)

    async def seed_due_summary(self):
        for turn in range(1, 5):
            await self.store.add_turn("7:same", 7, f"question {turn}", f"answer {turn}")

    async def test_same_identity_busy_before_history_read_and_next_turn_sees_pair(self):
        reading = asyncio.Event()
        resume_read = asyncio.Event()
        original_recent = self.store.recent

        async def recent(*args, **kwargs):
            reading.set()
            await resume_read.wait()
            return await original_recent(*args, **kwargs)

        first = self.pipeline()
        second = self.pipeline()
        with patch.object(self.store, "recent", new=AsyncMock(side_effect=recent)) as reads:
            running = await self.pending(first.handle(7, "first", "same"))
            await self.reached(reading)
            with self.assertRaises(SessionBusyError):
                await asyncio.wait_for(second.handle(7, "overlap", "same"), timeout=2)
            self.assertEqual(reads.await_count, 1)
            second._run_react.assert_not_awaited()
            resume_read.set()
            await running

        await second.handle(7, "next", "same")
        history = second._run_react.await_args.args[2]
        self.assertEqual([message.content for message in history], ["first", "generated answer"])
        self.assertEqual(await self.store.count_turns("7:same"), 2)

    async def test_different_users_and_sessions_progress_while_first_is_blocked(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_answer(*args):
            entered.set()
            await release.wait()
            return "first answer"

        first = self.pipeline()
        first._run_react.side_effect = blocked_answer
        running = await self.pending(first.handle(7, "first", "same"))
        await self.reached(entered)
        for user_id, session_id in [(8, "same"), (7, "other")]:
            independent = self.pipeline()
            result = await asyncio.wait_for(independent.handle(user_id, "independent", session_id), timeout=2)
            self.assertEqual(result["reply"], "generated answer")
            self.assertEqual(independent._run_react.await_args.args[2], [])
        release.set()
        await running
        self.assertEqual(await self.store.count_turns("7:same"), 1)
        self.assertEqual(await self.store.count_turns("8:same"), 1)
        self.assertEqual(await self.store.count_turns("7:other"), 1)

    async def test_model_exception_releases_guard_without_writing_partial_turn(self):
        failed = self.pipeline()
        failed._run_react.side_effect = RuntimeError("model unavailable")
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            await failed.handle(7, "failed", "same")
        self.assertEqual(await self.store.recent("7:same"), [])
        result = await self.pipeline().handle(7, "retry", "same")
        self.assertEqual(result["reply"], "generated answer")
        self.assertEqual(await self.store.count_turns("7:same"), 1)

    async def test_timeout_cancels_work_and_releases_guard(self):
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        never = asyncio.Event()

        async def blocked_answer(*args):
            entered.set()
            try:
                await never.wait()
            finally:
                cancelled.set()

        self.settings.memory_request_timeout = 0.05
        failed = self.pipeline()
        failed._run_react.side_effect = blocked_answer
        running = await self.pending(failed.handle(7, "timeout", "same"))
        await self.reached(entered)
        outcomes = await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), timeout=2)
        self.assertIsInstance(outcomes[0], TimeoutError)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(await self.store.count_turns("7:same"), 0)
        self.settings.memory_request_timeout = 180
        await self.pipeline().handle(7, "retry", "same")
        self.assertEqual(await self.store.count_turns("7:same"), 1)

    async def test_guard_covers_commit_and_checkpoint_in_that_order(self):
        await self.seed_due_summary()
        committing = asyncio.Event()
        allow_commit = asyncio.Event()
        checkpointing = asyncio.Event()
        allow_checkpoint = asyncio.Event()
        pipeline = self.pipeline()
        original_mark = self.store.mark_summarized

        async def commit():
            self.assertEqual(await self.store.summary_progress("7:same"), 0)
            committing.set()
            await allow_commit.wait()

        async def mark(sid, turn):
            checkpointing.set()
            await allow_checkpoint.wait()
            await original_mark(sid, turn)

        pipeline.session.commit.side_effect = commit
        with patch.object(self.store, "mark_summarized", new=AsyncMock(side_effect=mark)):
            running = await self.pending(pipeline.handle(7, "fifth", "same"))
            await self.reached(committing)
            self.assertFalse(checkpointing.is_set())
            with self.assertRaises(SessionBusyError):
                await self.pipeline().handle(7, "during commit", "same")
            allow_commit.set()
            await self.reached(checkpointing)
            with self.assertRaises(SessionBusyError):
                await self.pipeline().handle(7, "during checkpoint", "same")
            allow_checkpoint.set()
            result = await running
        self.assertEqual(result["reply"], "generated answer")
        self.assertEqual(await self.store.summary_progress("7:same"), 5)
        self.assertTrue(self.summarize.await_args.kwargs["defer_checkpoint"])
        await self.pipeline().handle(7, "after checkpoint", "same")

    async def test_summary_failure_returns_answer_rolls_back_and_retries_next_turn(self):
        await self.seed_due_summary()
        pipeline = self.pipeline()
        self.summarize.side_effect = RuntimeError("summary unavailable")
        with self.assertLogs("app.core.pipeline", level="WARNING"):
            result = await pipeline.handle(7, "fifth", "same")
        self.assertEqual(result["reply"], "generated answer")
        pipeline.session.rollback.assert_awaited_once()
        self.assertEqual(await self.store.summary_progress("7:same"), 0)
        self.assertEqual(await self.store.count_turns("7:same"), 5)
        self.summarize.side_effect = None
        await self.pipeline().handle(7, "retry summary", "same")
        self.assertEqual(await self.store.summary_progress("7:same"), 6)

    async def test_commit_failure_returns_answer_without_checkpoint_then_retries(self):
        await self.seed_due_summary()
        pipeline = self.pipeline()
        pipeline.session.commit.side_effect = RuntimeError("SQL unavailable")
        with self.assertLogs("app.core.pipeline", level="WARNING"):
            result = await pipeline.handle(7, "fifth", "same")
        self.assertEqual(result["reply"], "generated answer")
        pipeline.session.rollback.assert_awaited_once()
        self.assertEqual(await self.store.summary_progress("7:same"), 0)
        await self.pipeline().handle(7, "retry summary", "same")
        self.assertEqual(await self.store.summary_progress("7:same"), 6)

    async def test_one_request_writes_exactly_one_atomic_turn(self):
        pipeline = self.pipeline()
        with patch.object(self.store, "add_turn", wraps=self.store.add_turn) as add_turn:
            await pipeline.handle(7, "question", "same")
        add_turn.assert_awaited_once_with("7:same", 7, "question", "generated answer")
        self.assertEqual([(m.role, m.content) for m in await self.store.recent("7:same")],
                         [("user", "question"), ("assistant", "generated answer")])
        self.assertEqual(await self.store.count_turns("7:same"), 1)


if __name__ == "__main__":
    unittest.main()

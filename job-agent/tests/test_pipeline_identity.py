"""Regression: identical browser session IDs cannot mix Agent identities."""
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from app.core.pipeline import AgentPipeline
from app.memory.memory_store import InMemoryMessageStore


class PipelineIdentityTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_session_isolated_by_role_and_account(self):
        store = InMemoryMessageStore(max_turns=10)
        session = AsyncMock()
        profiles = AsyncMock()
        profiles.get.return_value = None
        seen = []

        class TracerStub:
            def __init__(self, *args):
                pass

            @asynccontextmanager
            async def step(self, *args, **kwargs):
                yield

        async def answer(intent, message, history, sid, uid, *args):
            seen.append((uid, [str(m.content) for m in history]))
            return f"answer:{uid}"

        with patch("app.core.pipeline.get_memory_store", return_value=store), \
             patch("app.core.pipeline.ProfileRepository", return_value=profiles), \
             patch("app.core.pipeline.Tracer", TracerStub), \
             patch("app.core.pipeline.recognize_intent", new=AsyncMock(return_value={"intent": "qa"})), \
             patch("app.core.pipeline.maybe_summarize", new=AsyncMock()) as summarize:
            pipeline = AgentPipeline(session)
            pipeline._run_react = answer
            first = await pipeline.handle(-1, "admin secret", "same")
            second = await pipeline.handle(1, "candidate secret", "same")
            await pipeline.handle(-2, "another admin", "same")
            await pipeline.handle(-1, "follow up", "same")

        self.assertEqual(first["session_id"], "same")
        self.assertEqual(second["session_id"], "same")
        self.assertEqual(seen[:3], [(-1, []), (1, []), (-2, [])])
        self.assertEqual(seen[3], (-1, ["admin secret", "answer:-1"]))
        self.assertEqual([call.args[0] for call in summarize.await_args_list],
                         ["-1:same", "1:same", "-2:same", "-1:same"])
        self.assertEqual(len(await store.recent("1:same")), 2)
        self.assertEqual(await store.recent("same"), [])


if __name__ == "__main__":
    unittest.main()

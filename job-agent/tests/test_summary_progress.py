"""Summary checkpoints track cumulative turns beyond the retained chat window."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.memory.memory_store import InMemoryMessageStore
from app.memory.summarizer import ProfileExtraction, maybe_summarize


class SummaryProgressTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = InMemoryMessageStore(max_turns=30)
        self.profiles = AsyncMock()
        self.structured = SimpleNamespace(ainvoke=AsyncMock(return_value=ProfileExtraction(summary="Useful career summary")))
        self.model = MagicMock()
        self.model.with_structured_output.return_value = self.structured
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch("app.memory.summarizer.get_settings", return_value=SimpleNamespace(summary_interval=5, short_term_turns=30)))
        self.keep = self.patches.enter_context(patch("app.memory.summarizer.should_keep", new=AsyncMock(return_value=True)))
        self.model_factory = self.patches.enter_context(patch("app.memory.summarizer.get_structured_model", return_value=self.model))

    async def add_turns(self, first, last):
        for turn in range(first, last + 1):
            await self.store.add_turn("7:same", 7, f"question {turn}", f"answer {turn}")

    async def summarize(self, **kwargs):
        return await maybe_summarize("7:same", 7, self.store, self.profiles, **kwargs)

    def dialogue(self):
        return self.structured.ainvoke.await_args.args[0][-1].content

    async def test_summary_runs_only_every_five_turns_after_window_is_trimmed(self):
        summarized_at = []
        for turn in range(1, 36):
            await self.add_turns(turn, turn)
            result = await self.summarize()
            if result is not None:
                summarized_at.append(turn)
        self.assertEqual(summarized_at, [5, 10, 15, 20, 25, 30, 35])
        self.assertEqual(self.structured.ainvoke.await_count, 7)
        self.assertEqual(self.profiles.upsert_profile.await_count, 7)
        self.assertEqual(await self.store.count_turns("7:same"), 35)
        self.assertEqual(await self.store.summary_progress("7:same"), 35)
        retained = await self.store.recent("7:same")
        self.assertEqual(len(retained), 60)
        self.assertEqual(retained[0].content, "question 6")
        self.assertEqual(self.dialogue().splitlines(), [
            line for turn in range(31, 36)
            for line in (f"user: question {turn}", f"assistant: answer {turn}")
        ])
        self.assertIsNone(await self.summarize())
        self.assertEqual(self.structured.ainvoke.await_count, 7)

    async def test_no_summary_before_interval_and_no_model_on_empty_session(self):
        self.assertIsNone(await self.summarize())
        await self.add_turns(1, 4)
        self.assertIsNone(await self.summarize())
        self.keep.assert_not_awaited()
        self.model_factory.assert_not_called()
        self.assertEqual(await self.store.summary_progress("7:same"), 0)

    async def test_due_is_based_on_progress_delta_not_modulo(self):
        await self.add_turns(1, 7)
        await self.store.mark_summarized("7:same", 2)
        self.assertEqual(await self.summarize(), "Useful career summary")
        self.assertEqual(self.dialogue().splitlines(), [
            line for turn in range(3, 8)
            for line in (f"user: question {turn}", f"assistant: answer {turn}")
        ])
        self.assertEqual(await self.store.summary_progress("7:same"), 7)
        await self.add_turns(8, 10)
        self.assertIsNone(await self.summarize())
        self.assertEqual(self.structured.ainvoke.await_count, 1)
        self.assertEqual(await self.store.summary_progress("7:same"), 7)

    async def test_backlog_uses_all_unprocessed_turns_available_in_window(self):
        await self.add_turns(1, 12)
        await self.store.mark_summarized("7:same", 5)
        await self.summarize()
        self.assertEqual(self.dialogue().splitlines(), [
            line for turn in range(6, 13)
            for line in (f"user: question {turn}", f"assistant: answer {turn}")
        ])
        self.assertEqual(await self.store.summary_progress("7:same"), 12)

    async def test_backlog_is_bounded_by_retained_window(self):
        await self.add_turns(1, 40)
        await self.summarize()
        self.assertEqual(self.dialogue().splitlines(), [
            line for turn in range(11, 41)
            for line in (f"user: question {turn}", f"assistant: answer {turn}")
        ])
        self.assertEqual(await self.store.summary_progress("7:same"), 40)

    async def test_filter_skip_checkpoints_once_without_calling_model(self):
        await self.add_turns(1, 5)
        self.keep.return_value = False
        self.assertIsNone(await self.summarize())
        self.assertEqual(await self.store.summary_progress("7:same"), 5)
        self.assertIsNone(await self.summarize())
        self.keep.assert_awaited_once()
        self.model_factory.assert_not_called()
        self.profiles.upsert_profile.assert_not_awaited()
        await self.add_turns(6, 9)
        self.assertIsNone(await self.summarize())
        self.assertEqual(self.keep.await_count, 1)
        await self.add_turns(10, 10)
        await self.summarize()
        self.assertEqual(self.keep.await_count, 2)
        self.assertEqual(await self.store.summary_progress("7:same"), 10)

    async def test_invalid_and_empty_extractions_checkpoint_without_profile_write(self):
        await self.add_turns(1, 5)
        for invalid in [None, {"summary": "not validated"}, ProfileExtraction(summary="  ")]:
            with self.subTest(extraction=invalid):
                store = InMemoryMessageStore(max_turns=30)
                for turn in range(5):
                    await store.add_turn("7:same", 7, f"question {turn}", f"answer {turn}")
                self.structured.ainvoke.return_value = invalid
                self.assertIsNone(await maybe_summarize("7:same", 7, store, self.profiles))
                self.assertEqual(await store.summary_progress("7:same"), 5)
                await maybe_summarize("7:same", 7, store, self.profiles)
        self.assertEqual(self.structured.ainvoke.await_count, 3)
        self.profiles.upsert_profile.assert_not_awaited()

    async def test_filter_model_and_profile_errors_do_not_checkpoint_and_retry(self):
        await self.add_turns(1, 5)
        for operation in [self.keep, self.structured.ainvoke, self.profiles.upsert_profile]:
            with self.subTest(operation=operation):
                operation.side_effect = RuntimeError("temporary summary failure")
                with self.assertRaisesRegex(RuntimeError, "temporary summary failure"):
                    await self.summarize()
                self.assertEqual(await self.store.summary_progress("7:same"), 0)
                operation.side_effect = None
        self.assertEqual(await self.summarize(), "Useful career summary")
        self.assertEqual(await self.store.summary_progress("7:same"), 5)

    async def test_deferred_success_and_skip_leave_checkpoint_to_caller(self):
        await self.add_turns(1, 5)
        self.assertEqual(await self.summarize(defer_checkpoint=True), "Useful career summary")
        self.profiles.upsert_profile.assert_awaited_once()
        self.assertEqual(await self.store.summary_progress("7:same"), 0)
        self.keep.return_value = False
        self.assertIsNone(await self.summarize(defer_checkpoint=True))
        self.assertEqual(await self.store.summary_progress("7:same"), 0)
        self.keep.return_value = True
        self.structured.ainvoke.return_value = None
        self.assertIsNone(await self.summarize(defer_checkpoint=True))
        self.assertEqual(await self.store.summary_progress("7:same"), 0)
        await self.store.mark_summarized("7:same", 5)
        self.assertIsNone(await self.summarize())

    async def test_profiles_receive_structured_fields_and_trimmed_summary(self):
        await self.add_turns(1, 5)
        self.structured.ainvoke.return_value = ProfileExtraction(
            summary="  Career summary  ", goals="Backend role", preferences={"city": "Beijing"},
            skills=["Python"], resume_summary="Three years of experience",
        )
        await self.summarize()
        self.profiles.upsert_profile.assert_awaited_once_with(
            7, summary="Career summary", goals="Backend role", preferences={"city": "Beijing"},
            skills=["Python"], resume_summary="Three years of experience",
        )
        self.assertEqual(await self.store.summary_progress("7:same"), 5)


if __name__ == "__main__":
    unittest.main()

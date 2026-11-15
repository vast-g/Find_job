"""Storage contract tests: no Redis server, LLM, or network required."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.memory.errors import SessionBusyError, SessionLeaseLostError
from app.memory.memory_store import InMemoryMessageStore
from app.memory.redis_store import RedisMessageStore, StoredMessage, _Lease, _APPEND, _METADATA, _RELEASE, _RENEW


SETTINGS = SimpleNamespace(short_term_turns=30, redis_ttl=60, memory_lock_ttl=30)


class MemoryStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch('app.memory.memory_store.get_settings', return_value=SETTINGS):
            self.store = InMemoryMessageStore()

    async def test_retention_preserves_pairs_and_cumulative_turn_count(self):
        for turn in range(35):
            self.assertEqual(await self.store.add_turn('7:s', 7, f'问题{turn}', f'回答{turn}'), turn + 1)
        messages = await self.store.recent('7:s')
        self.assertEqual(len(messages), 60)
        self.assertEqual([m.role for m in messages], ['user', 'assistant'] * 30)
        self.assertEqual(messages[0].content, '问题5')
        self.assertEqual(messages[-1].content, '回答34')
        self.assertEqual(await self.store.count_turns('7:s'), 35)
        self.assertEqual(await self.store.count_turns('8:s'), 0)

    async def test_checkpoint_is_monotonic_clamped_and_cleared_with_history(self):
        for _ in range(5):
            await self.store.add_turn('s', 1, 'u', 'a')
        self.assertEqual(await self.store.summary_progress('s'), 0)
        await self.store.mark_summarized('s', 4)
        await self.store.mark_summarized('s', 2)
        self.assertEqual(await self.store.summary_progress('s'), 4)
        await self.store.mark_summarized('s', 100)
        self.assertEqual(await self.store.summary_progress('s'), 5)
        await self.store.delete_by_session('s')
        await self.store.mark_summarized('s', 100)
        self.assertEqual(await self.store.recent('s'), [])
        self.assertEqual(await self.store.count_turns('s'), 0)
        self.assertEqual(await self.store.summary_progress('s'), 0)
        self.assertEqual(await self.store.add_turn('s', 1, 'new', 'new'), 1)

    async def test_legacy_add_counts_only_assistant_writes(self):
        for index in range(35):
            await self.store.add('s', 1, 'user', 'u')
            self.assertEqual(await self.store.count_turns('s'), index)
            await self.store.add('s', 1, 'assistant', 'a')
            self.assertEqual(await self.store.count_turns('s'), index + 1)
        self.assertEqual(await self.store.add_turn('s', 1, 'u', 'a'), 36)

    async def test_list_only_history_migrates_count(self):
        self.store._data['chat:s'] = [StoredMessage('user', 'u'), StoredMessage('assistant', 'a')] * 3
        self.assertEqual(await self.store.count_turns('s'), 3)
        self.assertEqual(await self.store.add_turn('s', 1, 'u', 'a'), 4)

    async def test_expiry_does_not_resurrect_checkpoint(self):
        await self.store.add_turn('s', 1, 'u', 'a')
        await self.store.mark_summarized('s', 1)
        self.store._expires['chat:s'] = 0
        await self.store.mark_summarized('s', 1)
        self.assertEqual(await self.store.count_turns('s'), 0)
        self.assertEqual(await self.store.summary_progress('s'), 0)
        self.assertNotIn('chat:s', self.store._progress)

    async def test_busy_per_session_and_release_on_exception(self):
        with self.assertRaisesRegex(ValueError, 'body'):
            async with self.store.session_guard('s'):
                with self.assertRaises(SessionBusyError):
                    async with self.store.session_guard('s'):
                        self.fail('busy guard entered')
                async with self.store.session_guard('other'):
                    await self.store.add_turn('other', 1, 'u', 'a')
                raise ValueError('body')
        async with self.store.session_guard('s'):
            await self.store.add_turn('s', 1, 'u', 'a')

    async def test_guard_propagates_cancellation_and_releases(self):
        with self.assertRaises(asyncio.CancelledError):
            async with self.store.session_guard('s'):
                raise asyncio.CancelledError()
        async with self.store.session_guard('s'):
            pass

    async def test_stale_memory_writer_cannot_append_or_release_new_owner(self):
        async with self.store.session_guard('s'):
            self.store._locks['s'] = 'replacement'
            with self.assertRaises(SessionLeaseLostError):
                await self.store.add_turn('s', 1, 'u', 'a')
            # Raise to leave the guard without its successful-exit check.
            with self.assertRaises(SessionLeaseLostError):
                self.store._check_lease('s')
            self.store._locks['s'] = self.store._lease.get()[1]
        self.assertEqual(await self.store.count_turns('s'), 0)


class RedisStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis = SimpleNamespace(set=AsyncMock(return_value=True),
                                     eval=AsyncMock(return_value=1),
                                     lrange=AsyncMock(return_value=[]), delete=AsyncMock())
        with patch('app.memory.redis_store.get_settings', return_value=SETTINGS):
            self.store = RedisMessageStore(self.redis)
        self.settings_patch = patch('app.memory.redis_store.get_settings', return_value=SETTINGS)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    async def test_pair_is_one_script_call_with_utf8_and_legacy_keys(self):
        self.redis.eval.return_value = 35
        self.assertEqual(await self.store.add_turn('9:s', 9, '问题', '回答'), 35)
        self.redis.eval.assert_awaited_once()
        args = self.redis.eval.await_args.args
        self.assertEqual(args[:5], (_APPEND, 3, 'chat:9:s', 'chat:9:s:meta', 'chat:9:s:lock'))
        self.assertEqual(args[5:8], ('', 60, 60))
        self.assertEqual(json.loads(args[8]), {'role': 'user', 'content': '问题'})
        self.assertEqual(json.loads(args[9]), {'role': 'assistant', 'content': '回答'})
        self.assertIn('问题', args[8])
        self.assertEqual(args[10], 1)

    async def test_legacy_assistant_counts_once(self):
        await self.store.add('s', 1, 'user', 'u')
        self.assertEqual(self.redis.eval.await_args.args[-2:], ('', 0))
        await self.store.add('s', 1, 'assistant', 'a')
        self.assertEqual(self.redis.eval.await_args.args[-2:], ('', 1))

    async def test_metadata_and_delete_commands(self):
        self.redis.eval.return_value = 35
        self.assertEqual(await self.store.count_turns('s'), 35)
        self.redis.eval.assert_awaited_with(_METADATA, 3, 'chat:s', 'chat:s:meta', 'chat:s:lock', 'count', 0, '')
        self.redis.eval.return_value = 30
        self.assertEqual(await self.store.summary_progress('s'), 30)
        await self.store.mark_summarized('s', 30)
        self.redis.eval.assert_awaited_with(_METADATA, 3, 'chat:s', 'chat:s:meta', 'chat:s:lock', 'mark', 30, '')
        await self.store.delete_by_session('s')
        self.redis.delete.assert_awaited_once_with('chat:s', 'chat:s:meta')

    async def test_busy_acquisition(self):
        self.redis.set.return_value = False
        with self.assertRaises(SessionBusyError):
            async with self.store.session_guard('s'):
                self.fail('busy guard entered')
        self.redis.eval.assert_not_awaited()

    async def test_guard_fences_write_and_compares_token_on_release(self):
        async with self.store.session_guard('s'):
            token = self.redis.set.await_args.args[1]
            self.assertTrue(token)
            self.assertEqual(self.redis.set.await_args.kwargs, {'nx': True, 'ex': 30})
            await self.store.add_turn('s', 1, 'u', 'a')
            self.assertEqual(self.redis.eval.await_args.args[5], token)
        self.redis.eval.assert_awaited_with(_RELEASE, 1, 'chat:s:lock', token)

    async def test_ownership_loss_rejects_current_and_future_writes(self):
        with self.assertRaises(SessionLeaseLostError):
            async with self.store.session_guard('s'):
                self.redis.eval.return_value = -1
                with self.assertRaises(SessionLeaseLostError):
                    await self.store.add_turn('s', 1, 'u', 'a')
                calls = self.redis.eval.await_count
                with self.assertRaises(SessionLeaseLostError):
                    await self.store.add_turn('s', 1, 'u', 'a')
                self.assertEqual(self.redis.eval.await_count, calls)
                self.redis.eval.return_value = 0

    async def test_renewal_error_flags_lease_and_blocks_append(self):
        lease = _Lease('s', 'token')
        self.redis.eval.side_effect = ConnectionError('Redis unavailable')
        with patch('app.memory.redis_store.asyncio.sleep', new=AsyncMock()):
            await self.store._heartbeat(lease, 30)
        self.assertTrue(lease.lost)
        self.redis.eval.assert_awaited_with(_RENEW, 1, 'chat:s:lock', 'token', 30)
        context = self.store._lease.set(lease)
        try:
            with self.assertRaises(SessionLeaseLostError):
                await self.store.add_turn('s', 1, 'u', 'a')
        finally:
            self.store._lease.reset(context)

    async def test_cancellation_is_not_swallowed_and_lock_is_released(self):
        with self.assertRaises(asyncio.CancelledError):
            async with self.store.session_guard('s'):
                raise asyncio.CancelledError()
        self.assertEqual(self.redis.eval.await_args.args[0], _RELEASE)
        self.assertIsNone(self.store._lease.get())


if __name__ == '__main__':
    unittest.main()

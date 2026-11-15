import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from langchain_core.messages import HumanMessage, AIMessage
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.routes.agent import chat
from app.api.schemas import ChatRequest
from app.memory.errors import SessionBusyError, SessionLeaseLostError
from app.memory.memory_store import InMemoryMessageStore
from app.memory.short_term import RedisChatMessageHistory


class ChatMemoryErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_errors_have_explicit_http_status_and_safe_message(self):
        for failure, status, text in [
            (SessionBusyError('busy'), 409, '上一条回复'),
            (SessionLeaseLostError('lost'), 503, '会话状态'),
            (TimeoutError(), 504, '超时'),
            (RedisConnectionError('private connection detail'), 503, '会话记忆'),
        ]:
            with self.subTest(status=status, error=type(failure).__name__):
                with patch('app.api.routes.agent.AgentPipeline') as pipeline:
                    pipeline.return_value.handle = AsyncMock(side_effect=failure)
                    with self.assertRaises(HTTPException) as raised:
                        await chat(ChatRequest(user_id=1, session_id='s', message='hi'), AsyncMock())
                    self.assertEqual(raised.exception.status_code, status)
                    self.assertIn(text, raised.exception.detail)
                    self.assertNotIn('private', raised.exception.detail)

    async def test_history_validates_entire_batch_before_any_append(self):
        store = InMemoryMessageStore()
        history = RedisChatMessageHistory('1:s', 1, store)
        with self.assertRaises(ValueError):
            await history.aadd_messages([HumanMessage(content='first'), AIMessage(content='answer'),
                                         AIMessage(content='wrong order'), HumanMessage(content='wrong')])
        self.assertEqual(await store.recent('1:s'), [])
        self.assertEqual(await store.count_turns('1:s'), 0)
        await history.aadd_messages([HumanMessage(content='first'), AIMessage(content='answer')])
        self.assertEqual(await store.count_turns('1:s'), 1)


if __name__ == '__main__':
    unittest.main()

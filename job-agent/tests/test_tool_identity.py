"""Identity isolation tests for user scoped tools."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.context import reset_current_user, set_current_user
from app.tools.application_tools import get_user_applications
from app.tools.resume_tools import get_user_resume


class _MappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, calls, rows=None):
        self.calls = calls
        self.rows = rows or []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _MappingsResult(self.rows)


class _SessionMaker:
    def __init__(self, calls, rows=None):
        self.calls = calls
        self.rows = rows
        self.opened = 0

    def __call__(self):
        self.opened += 1
        session = _Session(self.calls, self.rows)

        class _Context:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Context()


class ToolIdentityTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        # Each test restores the ContextVar token it creates; this is a guard for
        # failures before the normal reset path.
        token = getattr(self, "_token", None)
        if token is not None:
            reset_current_user(token)

    async def test_request_identity_wins_over_conflicting_model_ids(self):
        calls = []
        maker = _SessionMaker(calls, [{"name": "Logged-in candidate"}])
        self._token = set_current_user(7)
        with patch("app.tools.resume_tools.get_sessionmaker", return_value=maker):
            result = await get_user_resume.ainvoke({"user_id": 99})

        self.assertEqual(result, {"name": "Logged-in candidate"})
        self.assertEqual(calls[0][1], {"uid": 7})
        self.assertIn("WHERE user_id = :uid", calls[0][0])

        calls.clear()
        maker = _SessionMaker(calls, [{
            "status": 1,
            "create_time": "2026-01-01",
            "job_title": "Engineer",
            "company_name": "Example",
        }])
        with patch("app.tools.application_tools.get_sessionmaker", return_value=maker):
            result = await get_user_applications.ainvoke({"user_id": 99})

        self.assertEqual(result[0]["job"], "Engineer")
        self.assertEqual(calls[0][1], {"uid": 7})

    async def test_negative_admin_identity_returns_without_touching_db(self):
        self._token = set_current_user(-12)
        resume_maker = unittest.mock.Mock()
        with patch("app.tools.resume_tools.get_sessionmaker", resume_maker):
            self.assertEqual(await get_user_resume.ainvoke({"user_id": 4}), {})
        resume_maker.assert_not_called()

        application_maker = unittest.mock.Mock()
        with patch("app.tools.application_tools.get_sessionmaker", application_maker):
            self.assertEqual(await get_user_applications.ainvoke({"user_id": 4}), [])
        application_maker.assert_not_called()

    async def test_absent_resume_does_not_fallback_to_another_user(self):
        calls = []
        maker = _SessionMaker(calls, [])
        self._token = set_current_user(7)
        with patch("app.tools.resume_tools.get_sessionmaker", return_value=maker):
            result = await get_user_resume.ainvoke({"user_id": 99})

        self.assertEqual(result, {})
        self.assertEqual(maker.opened, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {"uid": 7})
        self.assertIn("WHERE user_id = :uid", calls[0][0])
        self.assertNotIn("ORDER BY is_default DESC, create_time DESC LIMIT 1", calls[0][0].split("WHERE")[0])

    async def test_missing_identity_returns_empty_without_db(self):
        resume_maker = unittest.mock.Mock()
        with patch("app.tools.resume_tools.get_sessionmaker", resume_maker):
            self.assertEqual(await get_user_resume.ainvoke({}), {})
        resume_maker.assert_not_called()

        application_maker = unittest.mock.Mock()
        with patch("app.tools.application_tools.get_sessionmaker", application_maker):
            self.assertEqual(await get_user_applications.ainvoke({}), [])
        application_maker.assert_not_called()


if __name__ == "__main__":
    unittest.main()

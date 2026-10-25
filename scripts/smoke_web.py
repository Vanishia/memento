"""Web API regression checks, using an isolated temporary database.

Run with: python scripts/smoke_web.py
"""

import gc
import hashlib
import hmac
import os
import time
from tempfile import TemporaryDirectory
import unittest
import warnings
from unittest.mock import patch

from fastapi.testclient import TestClient

from memento import repository, service
from memento.db import init_db
from memento.db import get_conn
from memento.web.app import app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "MEMENTO_DB_PATH": os.path.join(self.tmp.name, "web.db"),
            "MEMENTO_PASSWORD": "",
        })
        self.env.start()
        init_db()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()
        # Existing repository connections close on collection; force that before
        # removing SQLite files on Windows.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
        self.tmp.cleanup()

    def test_pin_is_idempotent_and_preserves_dates(self):
        mid = repository.create("old memory", "2020-01-01 00:00:00")
        for pinned in (True, True, False, False):
            response = self.client.put(f"/api/memories/{mid}/pin", json={"pinned": pinned})
            self.assertEqual(response.status_code, 200)
            row = dict(repository.get(mid))
            self.assertEqual(bool(row["pinned"]), pinned)
            self.assertEqual(row["created_at"], "2020-01-01 00:00:00")
            self.assertEqual(row["updated_at"], row["created_at"])
        self.assertEqual(self.client.put("/api/memories/missing/pin", json={"pinned": True}).status_code, 404)

    def test_pin_limit_and_auth(self):
        ids = [service.write_memory(str(i)) for i in range(service.PIN_LIMIT + 1)]
        for mid in ids[:-1]:
            self.assertEqual(self.client.put(f"/api/memories/{mid}/pin", json={"pinned": True}).status_code, 200)
        self.assertEqual(self.client.put(f"/api/memories/{ids[-1]}/pin", json={"pinned": True}).status_code, 400)
        self.assertEqual(repository.get(ids[-1])["pinned"], 0)
        self.assertEqual(self.client.put(f"/api/memories/{ids[0]}/pin", json={"pinned": True}).status_code, 200)
        with patch.dict(os.environ, {"MEMENTO_PASSWORD": "test-password"}):
            self.assertEqual(self.client.put(f"/api/memories/{ids[0]}/pin", json={"pinned": False}).status_code, 401)

    def test_search_dates_order_limit_and_validation(self):
        old = repository.create("needle appears first", "2020-01-01 00:00:00")
        repository.update(old, "needle appears first", "2026-10-21 00:00:00")
        repository.set_pinned(old, True)
        repository.create("later needle", "2026-10-20 00:00:00")
        response = self.client.get("/api/memories/search", params={"keyword": "needle"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["id"], old)
        self.assertEqual(response.json()["items"][0]["pinned"], 1)
        dated = self.client.get("/api/memories/search", params={"since": "2020-01-01", "until": "2020-01-01"})
        self.assertEqual([m["id"] for m in dated.json()["items"]], [old])
        for params in ({}, {"keyword": " "}, {"since": "invalid"}, {"since": "2026-02-30"}):
            self.assertEqual(self.client.get("/api/memories/search", params=params).status_code, 400)
        reversed_range = self.client.get("/api/memories/search", params={"since": "2026-10-21", "until": "2020-01-01"})
        self.assertEqual(reversed_range.json()["items"], [])
        self.assertEqual(self.client.get("/api/memories/search", params={"keyword": "no match"}).json()["items"], [])
        for i in range(service.SEARCH_LIMIT + 1):
            service.write_memory(f"many results {i}")
        limited = self.client.get("/api/memories/search", params={"keyword": "many"}).json()
        self.assertEqual(len(limited["items"]), service.SEARCH_LIMIT)
        self.assertTrue(limited["may_have_more"])
        with patch.dict(os.environ, {"MEMENTO_PASSWORD": "test-password"}):
            self.assertEqual(self.client.get("/api/memories/search", params={"keyword": "needle"}).status_code, 401)

    def test_new_sessions_are_per_client_and_old_cookie_is_rejected(self):
        with patch.dict(os.environ, {"MEMENTO_PASSWORD": "test-password"}):
            old_cookie = hmac.new(b"test-password", b"memento-session", hashlib.sha256).hexdigest()
            self.client.cookies.set("memento_session", old_cookie)
            self.assertEqual(self.client.get("/api/memories").status_code, 401)

            first = TestClient(app)
            second = TestClient(app)
            try:
                self.assertEqual(first.post("/api/login", json={"password": "test-password"}).status_code, 200)
                self.assertEqual(second.post("/api/login", json={"password": "test-password"}).status_code, 200)
                first_cookie = first.cookies.get("memento_session")
                second_cookie = second.cookies.get("memento_session")
                self.assertTrue(first_cookie and second_cookie and first_cookie != second_cookie)
                self.assertEqual(first.get("/api/memories").status_code, 200)
                self.assertEqual(second.get("/api/memories").status_code, 200)
            finally:
                first.close()
                second.close()

    def test_sessions_expire_after_idle_or_absolute_deadline(self):
        with patch.dict(os.environ, {"MEMENTO_PASSWORD": "test-password"}):
            self.assertEqual(self.client.post("/api/login", json={"password": "test-password"}).status_code, 200)
            token = self.client.cookies.get("memento_session")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            with get_conn() as conn:
                conn.execute(
                    "UPDATE web_sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                    (int(time.time()) - 8 * 24 * 3600, int(time.time()) + 3600, token_hash),
                )
            self.assertEqual(self.client.get("/api/memories").status_code, 401)

            self.client.cookies.clear()
            self.assertEqual(self.client.post("/api/login", json={"password": "test-password"}).status_code, 200)
            token = self.client.cookies.get("memento_session")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            with get_conn() as conn:
                conn.execute(
                    "UPDATE web_sessions SET expires_at = ? WHERE token_hash = ?",
                    (int(time.time()) - 1, token_hash),
                )
            self.assertEqual(self.client.get("/api/memories").status_code, 401)


if __name__ == "__main__":
    unittest.main()

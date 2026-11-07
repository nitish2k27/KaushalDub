"""Tiny table store with two backends that behave the same:

* SupabaseStore: Supabase Postgres through PostgREST (HTTPS, service key; RLS is bypassed by the
  service role, so every route checks ownership itself).
* SqliteStore: local file, one JSON document per row. Used for local development and tests.

Only the operations the app needs: insert, upsert, get, select (equality / IN filters, order, limit),
update, delete. Free-text search and array filters are done in Python by the callers."""
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

import httpx

from .config import get_settings

TABLES = ["users", "videos", "steps", "translations", "outputs", "quizzes", "quiz_attempts", "watch_history",
          "tickets", "annotation_requests", "correction_memory", "model_versions", "user_plans", "user_api_keys",
          "annotations", "jobs", "tts_clips"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def insert(self, table, row): ...
    def upsert(self, table, row, on): ...
    def get(self, table, id): ...
    def select(self, table, where=None, in_=None, order=None, desc=False, limit=None): ...
    def update(self, table, where, values): ...
    def delete(self, table, where): ...

    def first(self, table, **where):
        rows = self.select(table, where, limit=1)
        return rows[0] if rows else None


def _prep(row):
    row = dict(row)
    row.setdefault("id", new_id())
    row.setdefault("created_at", now_iso())
    return row


class SqliteStore(Store):
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            for t in TABLES:
                c.execute(f'CREATE TABLE IF NOT EXISTS "{t}" (id TEXT PRIMARY KEY, data TEXT NOT NULL)')

    def _conn(self):
        return sqlite3.connect(self.path, timeout=30)

    def _all(self, c, table):
        return [json.loads(d) for (d,) in c.execute(f'SELECT data FROM "{table}"')]

    @staticmethod
    def _match(row, where, in_):
        for k, v in (where or {}).items():
            if row.get(k) != v:
                return False
        for k, vs in (in_ or {}).items():
            if row.get(k) not in vs:
                return False
        return True

    def insert(self, table, row):
        row = _prep(row)
        with self._lock, self._conn() as c:
            c.execute(f'INSERT INTO "{table}" (id, data) VALUES (?, ?)', (row["id"], json.dumps(row, default=str)))
        return row

    def upsert(self, table, row, on):
        with self._lock:
            existing = self.select(table, {k: row[k] for k in on}, limit=1)
            if existing:
                return self.update(table, {"id": existing[0]["id"]}, {k: v for k, v in row.items() if k != "id"})[0]
            return self.insert(table, row)

    def get(self, table, id):
        with self._conn() as c:
            r = c.execute(f'SELECT data FROM "{table}" WHERE id = ?', (id,)).fetchone()
        return json.loads(r[0]) if r else None

    def select(self, table, where=None, in_=None, order=None, desc=False, limit=None):
        with self._conn() as c:
            rows = [r for r in self._all(c, table) if self._match(r, where, in_)]
        if order:
            rows.sort(key=lambda r: (r.get(order) is None, r.get(order)), reverse=desc)
        return rows[:limit] if limit else rows

    def update(self, table, where, values):
        out = []
        with self._lock, self._conn() as c:
            for r in self._all(c, table):
                if self._match(r, where, None):
                    r.update(values)
                    c.execute(f'UPDATE "{table}" SET data = ? WHERE id = ?', (json.dumps(r, default=str), r["id"]))
                    out.append(r)
        return out

    def delete(self, table, where):
        n = 0
        with self._lock, self._conn() as c:
            for r in self._all(c, table):
                if self._match(r, where, None):
                    c.execute(f'DELETE FROM "{table}" WHERE id = ?', (r["id"],))
                    n += 1
        return n


def service_headers(key):
    """Legacy service_role keys are JWTs and also go in Authorization; new sb_secret_ keys go only in apikey."""
    return {"apikey": key} if key.startswith("sb_") else {"apikey": key, "Authorization": f"Bearer {key}"}


class SupabaseStore(Store):
    def __init__(self, url, service_key):
        self.base = url.rstrip("/") + "/rest/v1"
        self.h = {**service_headers(service_key), "Content-Type": "application/json"}
        self.http = httpx.Client(timeout=30)

    @staticmethod
    def _lit(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "null"
        return str(v)

    def _params(self, where=None, in_=None, order=None, desc=False, limit=None):
        p = {"select": "*"}
        for k, v in (where or {}).items():
            p[k] = ("is." if v is None else "eq.") + self._lit(v)
        for k, vs in (in_ or {}).items():
            p[k] = "in.(" + ",".join('"%s"' % self._lit(v).replace('"', '\\"') for v in vs) + ")"
        if order:
            p["order"] = f"{order}.{'desc' if desc else 'asc'}"
        if limit:
            p["limit"] = str(limit)
        return p

    def _check(self, r):
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else []

    def insert(self, table, row):
        r = self.http.post(f"{self.base}/{table}", headers={**self.h, "Prefer": "return=representation"},
                           content=json.dumps(_prep(row), default=str))
        return self._check(r)[0]

    def upsert(self, table, row, on):
        row = dict(row)
        row.setdefault("created_at", now_iso())
        r = self.http.post(f"{self.base}/{table}", params={"on_conflict": ",".join(on)},
                           headers={**self.h, "Prefer": "return=representation,resolution=merge-duplicates"},
                           content=json.dumps(row, default=str))
        return self._check(r)[0]

    def get(self, table, id):
        rows = self.select(table, {"id": id}, limit=1)
        return rows[0] if rows else None

    def select(self, table, where=None, in_=None, order=None, desc=False, limit=None):
        if in_ and any(len(v) == 0 for v in in_.values()):
            return []
        r = self.http.get(f"{self.base}/{table}", headers=self.h, params=self._params(where, in_, order, desc, limit))
        return self._check(r)

    def update(self, table, where, values):
        p = self._params(where)
        r = self.http.patch(f"{self.base}/{table}", params=p, headers={**self.h, "Prefer": "return=representation"},
                            content=json.dumps(values, default=str))
        return self._check(r)

    def delete(self, table, where):
        p = self._params(where)
        r = self.http.delete(f"{self.base}/{table}", params=p, headers={**self.h, "Prefer": "return=representation"})
        return len(self._check(r))


_store = None


def get_store() -> Store:
    global _store
    if _store is None:
        s = get_settings()
        _store = (SupabaseStore(s.supabase_url, s.supabase_service_key) if s.use_supabase
                  else SqliteStore(os.path.join(s.data_dir, "kaushaldub.sqlite")))
    return _store


def set_store(store):
    global _store
    _store = store

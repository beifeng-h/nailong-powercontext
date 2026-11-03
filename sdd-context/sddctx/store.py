"""上下文存储。

默认实现是 **嵌入式 SQLite**（标准库自带，文件落在 `.sddctx/context.db`），
因此整套系统不需要任何外部数据库实例即可运行、测试、交付。

`ContextStore` 是一个 Protocol：如果你确实要接 OceanBase / MySQL 实例，
实现同样的方法即可替换，resolver / drift / assistant 都不用改
（见 `sddctx/sqlstore.py`）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from .models import (
    CodeRef,
    Decision,
    DecisionStatus,
    Requirement,
    Spec,
    SpecStatus,
    Symbol,
    TestCase,
    TestRef,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS specs (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL,
    scope         TEXT NOT NULL DEFAULT '[]',
    tags          TEXT NOT NULL DEFAULT '[]',
    supersedes    TEXT NOT NULL DEFAULT '[]',
    superseded_by TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL DEFAULT '',
    path          TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS requirements (
    spec_id     TEXT NOT NULL,
    id          TEXT NOT NULL,
    key         TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL DEFAULT '',
    verified_by TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (spec_id, id)
);
CREATE TABLE IF NOT EXISTS code_refs (
    spec_id TEXT NOT NULL,
    idx     INTEGER NOT NULL,
    file    TEXT NOT NULL,
    symbol  TEXT NOT NULL DEFAULT '',
    note    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (spec_id, idx)
);
CREATE TABLE IF NOT EXISTS test_refs (
    spec_id TEXT NOT NULL,
    idx     INTEGER NOT NULL,
    file    TEXT NOT NULL,
    test_id TEXT NOT NULL DEFAULT '',
    covers  TEXT NOT NULL DEFAULT '[]',
    note    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (spec_id, idx)
);
CREATE TABLE IF NOT EXISTS decisions (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL,
    decided_at    TEXT NOT NULL DEFAULT '',
    scope         TEXT NOT NULL DEFAULT '[]',
    tags          TEXT NOT NULL DEFAULT '[]',
    superseded_by TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL DEFAULT '',
    path          TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS symbols (
    path     TEXT NOT NULL,
    qualname TEXT NOT NULL,
    kind     TEXT NOT NULL DEFAULT 'function',
    line     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (path, qualname)
);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS tests (
    test_id TEXT PRIMARY KEY,
    path    TEXT NOT NULL,
    covers  TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS reviews (
    spec_id      TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    reviewed_at  TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""


class ContextStore(Protocol):
    """存储协议——换实现即可接外部实例。"""

    def list_specs(self) -> list[Spec]: ...

    def get_spec(self, spec_id: str) -> Spec | None: ...

    def list_decisions(self) -> list[Decision]: ...

    def list_symbols(self) -> list[Symbol]: ...

    def list_tests(self) -> list[TestCase]: ...


def _loads(value: str) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [str(item) for item in data]
    return []


@dataclass
class Review:
    """一次"评审/验证"记录：某份规格在某个内容哈希上被确认过。"""

    spec_id: str
    content_hash: str
    reviewed_at: str = ""
    note: str = ""


class SqliteStore:
    """默认存储：嵌入式 SQLite。"""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # HTTP 服务会在另一个线程里访问同一个库，所以放开线程校验并加锁
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._commit()

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, tuple(params))

    def _executemany(self, sql: str, params: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.executemany(sql, [tuple(item) for item in params])

    def _commit(self) -> None:
        with self._lock:
            self.conn.commit()

    # ---------- 生命周期 ----------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def clear(self) -> None:
        for table in (
            "specs",
            "requirements",
            "code_refs",
            "test_refs",
            "decisions",
            "symbols",
            "tests",
            "reviews",
        ):
            self._execute(f"DELETE FROM {table}")
        self._commit()

    # ---------- 规格 ----------
    def upsert_spec(self, spec: Spec, updated_at: str = "") -> None:
        self._execute(
            """
            INSERT INTO specs (id, title, status, scope, tags, supersedes, superseded_by,
                               body, content_hash, path, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, status=excluded.status, scope=excluded.scope,
                tags=excluded.tags, supersedes=excluded.supersedes,
                superseded_by=excluded.superseded_by, body=excluded.body,
                content_hash=excluded.content_hash, path=excluded.path,
                updated_at=excluded.updated_at
            """,
            (
                spec.id,
                spec.title,
                spec.status.value,
                json.dumps(list(spec.scope), ensure_ascii=False),
                json.dumps(list(spec.tags), ensure_ascii=False),
                json.dumps(list(spec.supersedes), ensure_ascii=False),
                spec.superseded_by,
                spec.body,
                spec.content_hash,
                spec.path,
                updated_at,
            ),
        )
        self._execute("DELETE FROM requirements WHERE spec_id=?", (spec.id,))
        self._execute("DELETE FROM code_refs WHERE spec_id=?", (spec.id,))
        self._execute("DELETE FROM test_refs WHERE spec_id=?", (spec.id,))
        for req in spec.requirements:
            self._execute(
                "INSERT INTO requirements (spec_id, id, key, text, verified_by) VALUES (?,?,?,?,?)",
                (
                    spec.id,
                    req.id,
                    req.key,
                    req.text,
                    json.dumps(list(req.verified_by), ensure_ascii=False),
                ),
            )
        for idx, ref in enumerate(spec.code_refs):
            self._execute(
                "INSERT INTO code_refs (spec_id, idx, file, symbol, note) VALUES (?,?,?,?,?)",
                (spec.id, idx, ref.file, ref.symbol, ref.note),
            )
        for idx, ref in enumerate(spec.test_refs):
            self._execute(
                "INSERT INTO test_refs (spec_id, idx, file, test_id, covers, note) VALUES (?,?,?,?,?,?)",
                (
                    spec.id,
                    idx,
                    ref.file,
                    ref.test_id,
                    json.dumps(list(ref.covers), ensure_ascii=False),
                    ref.note,
                ),
            )
        self._commit()

    def _row_to_spec(self, row: sqlite3.Row) -> Spec:
        spec_id = row["id"]
        requirements = [
            Requirement(
                id=r["id"],
                text=r["text"],
                key=r["key"],
                verified_by=tuple(_loads(r["verified_by"])),
            )
            for r in self._execute(
                "SELECT * FROM requirements WHERE spec_id=? ORDER BY id", (spec_id,)
            )
        ]
        code_refs = [
            CodeRef(file=r["file"], symbol=r["symbol"], note=r["note"])
            for r in self._execute(
                "SELECT * FROM code_refs WHERE spec_id=? ORDER BY idx", (spec_id,)
            )
        ]
        test_refs = [
            TestRef(
                file=r["file"],
                test_id=r["test_id"],
                covers=tuple(_loads(r["covers"])),
                note=r["note"],
            )
            for r in self._execute(
                "SELECT * FROM test_refs WHERE spec_id=? ORDER BY idx", (spec_id,)
            )
        ]
        return Spec(
            id=spec_id,
            title=row["title"],
            status=SpecStatus(row["status"]),
            scope=tuple(_loads(row["scope"])),
            tags=tuple(_loads(row["tags"])),
            supersedes=tuple(_loads(row["supersedes"])),
            superseded_by=row["superseded_by"],
            requirements=tuple(requirements),
            code_refs=tuple(code_refs),
            test_refs=tuple(test_refs),
            body=row["body"],
            path=row["path"],
        )

    def list_specs(self, status: SpecStatus | None = None) -> list[Spec]:
        if status is None:
            rows = self._execute("SELECT * FROM specs ORDER BY id").fetchall()
        else:
            rows = self._execute(
                "SELECT * FROM specs WHERE status=? ORDER BY id", (status.value,)
            ).fetchall()
        return [self._row_to_spec(row) for row in rows]

    def get_spec(self, spec_id: str) -> Spec | None:
        row = self._execute("SELECT * FROM specs WHERE id=?", (spec_id,)).fetchone()
        return self._row_to_spec(row) if row else None

    def delete_spec(self, spec_id: str) -> None:
        self._execute("DELETE FROM specs WHERE id=?", (spec_id,))
        self._execute("DELETE FROM requirements WHERE spec_id=?", (spec_id,))
        self._execute("DELETE FROM code_refs WHERE spec_id=?", (spec_id,))
        self._execute("DELETE FROM test_refs WHERE spec_id=?", (spec_id,))
        self._commit()

    # ---------- 决策 ----------
    def upsert_decision(self, decision: Decision, updated_at: str = "") -> None:
        self._execute(
            """
            INSERT INTO decisions (id, title, status, decided_at, scope, tags, superseded_by,
                                   body, content_hash, path, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, status=excluded.status, decided_at=excluded.decided_at,
                scope=excluded.scope, tags=excluded.tags,
                superseded_by=excluded.superseded_by, body=excluded.body,
                content_hash=excluded.content_hash, path=excluded.path,
                updated_at=excluded.updated_at
            """,
            (
                decision.id,
                decision.title,
                decision.status.value,
                decision.decided_at,
                json.dumps(list(decision.scope), ensure_ascii=False),
                json.dumps(list(decision.tags), ensure_ascii=False),
                decision.superseded_by,
                decision.body,
                decision.content_hash,
                decision.path,
                updated_at,
            ),
        )
        self._commit()

    def list_decisions(self) -> list[Decision]:
        rows = self._execute("SELECT * FROM decisions ORDER BY id").fetchall()
        return [
            Decision(
                id=row["id"],
                title=row["title"],
                status=DecisionStatus(row["status"]),
                decided_at=row["decided_at"],
                scope=tuple(_loads(row["scope"])),
                tags=tuple(_loads(row["tags"])),
                superseded_by=row["superseded_by"],
                body=row["body"],
                path=row["path"],
            )
            for row in rows
        ]

    # ---------- 代码索引 ----------
    def replace_symbols(self, symbols: Iterable[Symbol]) -> None:
        self._execute("DELETE FROM symbols")
        self._executemany(
            "INSERT INTO symbols (path, qualname, kind, line) VALUES (?,?,?,?)",
            [(s.path, s.qualname, s.kind, s.line) for s in symbols],
        )
        self._commit()

    def list_symbols(self) -> list[Symbol]:
        rows = self._execute("SELECT * FROM symbols ORDER BY path, qualname").fetchall()
        return [
            Symbol(path=r["path"], qualname=r["qualname"], kind=r["kind"], line=r["line"])
            for r in rows
        ]

    def replace_files(self, paths: Iterable[str]) -> None:
        self._execute("DELETE FROM files")
        self._executemany(
            "INSERT OR REPLACE INTO files (path) VALUES (?)", [(p,) for p in paths]
        )
        self._commit()

    def list_files(self) -> list[str]:
        rows = self._execute("SELECT path FROM files ORDER BY path").fetchall()
        return [r["path"] for r in rows]

    def replace_tests(self, tests: Iterable[TestCase]) -> None:
        self._execute("DELETE FROM tests")
        self._executemany(
            "INSERT INTO tests (test_id, path, covers) VALUES (?,?,?)",
            [
                (t.test_id, t.path, json.dumps(list(t.covers), ensure_ascii=False))
                for t in tests
            ],
        )
        self._commit()

    def list_tests(self) -> list[TestCase]:
        rows = self._execute("SELECT * FROM tests ORDER BY test_id").fetchall()
        return [
            TestCase(path=r["path"], test_id=r["test_id"], covers=tuple(_loads(r["covers"])))
            for r in rows
        ]

    # ---------- 评审记录 ----------
    def set_review(self, review: Review) -> None:
        self._execute(
            """
            INSERT INTO reviews (spec_id, content_hash, reviewed_at, note) VALUES (?,?,?,?)
            ON CONFLICT(spec_id) DO UPDATE SET
                content_hash=excluded.content_hash,
                reviewed_at=excluded.reviewed_at,
                note=excluded.note
            """,
            (review.spec_id, review.content_hash, review.reviewed_at, review.note),
        )
        self._commit()

    def get_review(self, spec_id: str) -> Review | None:
        row = self._execute("SELECT * FROM reviews WHERE spec_id=?", (spec_id,)).fetchone()
        if not row:
            return None
        return Review(
            spec_id=row["spec_id"],
            content_hash=row["content_hash"],
            reviewed_at=row["reviewed_at"],
            note=row["note"],
        )

    def list_reviews(self) -> list[Review]:
        rows = self._execute("SELECT * FROM reviews ORDER BY spec_id").fetchall()
        return [
            Review(
                spec_id=r["spec_id"],
                content_hash=r["content_hash"],
                reviewed_at=r["reviewed_at"],
                note=r["note"],
            )
            for r in rows
        ]

    # ---------- 元信息 ----------
    def set_meta(self, key: str, value: str) -> None:
        self._execute(
            "INSERT INTO meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self._execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def stats(self) -> dict[str, Any]:
        def count(table: str) -> int:
            row = self._execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            return int(row["n"])

        return {
            "specs": count("specs"),
            "decisions": count("decisions"),
            "symbols": count("symbols"),
            "files": count("files"),
            "tests": count("tests"),
            "reviews": count("reviews"),
        }


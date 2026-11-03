"""可插拔的外部实例存储（可选）。

**默认路径用不到这个文件**——`SqliteStore` 走嵌入式 SQLite，零外部依赖。
如果你确实希望把上下文存到 OceanBase / MySQL 等实例上，用这个适配器：

    import pymysql
    from sddctx.sqlstore import SqlStore

    conn = pymysql.connect(host=..., port=2881, user=..., database=...)
    store = SqlStore(conn)
    store.create_schema()

实现遵循 PEP 249（DB-API 2.0），并自动适配 `qmark` / `format` / `pyformat`
三种占位符风格，所以 sqlite3、pymysql、mysql-connector 都能直接用。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

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
from .store import Review

MYSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sdd_specs (
    id            VARCHAR(64)  NOT NULL PRIMARY KEY,
    title         VARCHAR(512) NOT NULL,
    status        VARCHAR(32)  NOT NULL,
    scope         TEXT,
    tags          TEXT,
    supersedes    TEXT,
    superseded_by VARCHAR(64),
    body          MEDIUMTEXT,
    content_hash  VARCHAR(64),
    path          VARCHAR(512),
    updated_at    VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS sdd_requirements (
    spec_id     VARCHAR(64) NOT NULL,
    id          VARCHAR(64) NOT NULL,
    `key`       VARCHAR(128),
    text        TEXT,
    verified_by TEXT,
    PRIMARY KEY (spec_id, id)
);
CREATE TABLE IF NOT EXISTS sdd_code_refs (
    spec_id VARCHAR(64) NOT NULL,
    idx     INT NOT NULL,
    file    VARCHAR(512),
    symbol  VARCHAR(256),
    note    VARCHAR(512),
    PRIMARY KEY (spec_id, idx)
);
CREATE TABLE IF NOT EXISTS sdd_test_refs (
    spec_id VARCHAR(64) NOT NULL,
    idx     INT NOT NULL,
    file    VARCHAR(512),
    test_id VARCHAR(512),
    covers  TEXT,
    note    VARCHAR(512),
    PRIMARY KEY (spec_id, idx)
);
CREATE TABLE IF NOT EXISTS sdd_decisions (
    id            VARCHAR(64)  NOT NULL PRIMARY KEY,
    title         VARCHAR(512) NOT NULL,
    status        VARCHAR(32)  NOT NULL,
    decided_at    VARCHAR(64),
    scope         TEXT,
    tags          TEXT,
    superseded_by VARCHAR(64),
    body          MEDIUMTEXT,
    content_hash  VARCHAR(64),
    path          VARCHAR(512),
    updated_at    VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS sdd_symbols (
    path     VARCHAR(512) NOT NULL,
    qualname VARCHAR(256) NOT NULL,
    kind     VARCHAR(32),
    line     INT,
    PRIMARY KEY (path, qualname)
);
CREATE TABLE IF NOT EXISTS sdd_files (
    path VARCHAR(512) NOT NULL PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS sdd_tests (
    test_id VARCHAR(512) NOT NULL PRIMARY KEY,
    path    VARCHAR(512),
    covers  TEXT
);
CREATE TABLE IF NOT EXISTS sdd_reviews (
    spec_id      VARCHAR(64) NOT NULL PRIMARY KEY,
    content_hash VARCHAR(64),
    reviewed_at  VARCHAR(64),
    note         VARCHAR(512)
);
"""


def _loads(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [str(item) for item in data]
    return []


class SqlStore:
    """DB-API 适配器：把上下文存到任意支持 SQL 的实例里。"""

    def __init__(self, connection: Any, schema: str = MYSQL_SCHEMA) -> None:
        self.conn = connection
        self.schema = schema
        paramstyle = getattr(connection, "paramstyle", "qmark")
        self._ph = "?" if paramstyle == "qmark" else "%s"

    # ---------- 基础 ----------
    def _sql(self, statement: str) -> str:
        return statement.replace("?", self._ph) if self._ph != "?" else statement

    def _execute(self, statement: str, args: Sequence[Any] = ()) -> None:
        cursor = self.conn.cursor()
        try:
            cursor.execute(self._sql(statement), tuple(args))
        finally:
            close = getattr(cursor, "close", None)
            if close:
                close()

    def _query(self, statement: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        try:
            cursor.execute(self._sql(statement), tuple(args))
            rows = cursor.fetchall() or []
            description = cursor.description or []
            names = [col[0] for col in description]
            return [dict(zip(names, row)) for row in rows]
        finally:
            close = getattr(cursor, "close", None)
            if close:
                close()

    def _commit(self) -> None:
        commit = getattr(self.conn, "commit", None)
        if commit:
            commit()

    def create_schema(self) -> None:
        """建表（幂等）。"""
        for statement in self.schema.split(";"):
            if statement.strip():
                self._execute(statement)
        self._commit()

    def close(self) -> None:
        close = getattr(self.conn, "close", None)
        if close:
            close()

    # ---------- 规格 ----------
    def upsert_spec(self, spec: Spec, updated_at: str = "") -> None:
        self._execute("DELETE FROM sdd_requirements WHERE spec_id=?", (spec.id,))
        self._execute("DELETE FROM sdd_code_refs WHERE spec_id=?", (spec.id,))
        self._execute("DELETE FROM sdd_test_refs WHERE spec_id=?", (spec.id,))
        self._execute(
            "REPLACE INTO sdd_specs (id,title,status,scope,tags,supersedes,superseded_by,"
            "body,content_hash,path,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
        for req in spec.requirements:
            self._execute(
                "REPLACE INTO sdd_requirements (spec_id,id,`key`,text,verified_by) "
                "VALUES (?,?,?,?,?)",
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
                "REPLACE INTO sdd_code_refs (spec_id,idx,file,symbol,note) VALUES (?,?,?,?,?)",
                (spec.id, idx, ref.file, ref.symbol, ref.note),
            )
        for idx, ref in enumerate(spec.test_refs):
            self._execute(
                "REPLACE INTO sdd_test_refs (spec_id,idx,file,test_id,covers,note) "
                "VALUES (?,?,?,?,?,?)",
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

    def list_specs(self, status: SpecStatus | None = None) -> list[Spec]:
        if status is None:
            rows = self._query("SELECT * FROM sdd_specs ORDER BY id")
        else:
            rows = self._query("SELECT * FROM sdd_specs WHERE status=? ORDER BY id", (status.value,))
        return [self._row_to_spec(row) for row in rows]

    def get_spec(self, spec_id: str) -> Spec | None:
        rows = self._query("SELECT * FROM sdd_specs WHERE id=?", (spec_id,))
        return self._row_to_spec(rows[0]) if rows else None

    def _row_to_spec(self, row: dict[str, Any]) -> Spec:
        spec_id = row["id"]
        requirements = [
            Requirement(
                id=r["id"],
                text=r.get("text") or "",
                key=r.get("key") or "",
                verified_by=tuple(_loads(r.get("verified_by"))),
            )
            for r in self._query(
                "SELECT * FROM sdd_requirements WHERE spec_id=? ORDER BY id", (spec_id,)
            )
        ]
        code_refs = [
            CodeRef(file=r.get("file") or "", symbol=r.get("symbol") or "", note=r.get("note") or "")
            for r in self._query(
                "SELECT * FROM sdd_code_refs WHERE spec_id=? ORDER BY idx", (spec_id,)
            )
        ]
        test_refs = [
            TestRef(
                file=r.get("file") or "",
                test_id=r.get("test_id") or "",
                covers=tuple(_loads(r.get("covers"))),
                note=r.get("note") or "",
            )
            for r in self._query(
                "SELECT * FROM sdd_test_refs WHERE spec_id=? ORDER BY idx", (spec_id,)
            )
        ]
        return Spec(
            id=spec_id,
            title=row.get("title") or "",
            status=SpecStatus(row["status"]),
            scope=tuple(_loads(row.get("scope"))),
            tags=tuple(_loads(row.get("tags"))),
            supersedes=tuple(_loads(row.get("supersedes"))),
            superseded_by=row.get("superseded_by") or "",
            requirements=tuple(requirements),
            code_refs=tuple(code_refs),
            test_refs=tuple(test_refs),
            body=row.get("body") or "",
            path=row.get("path") or "",
        )

    # ---------- 决策 ----------
    def upsert_decision(self, decision: Decision, updated_at: str = "") -> None:
        self._execute(
            "REPLACE INTO sdd_decisions (id,title,status,decided_at,scope,tags,superseded_by,"
            "body,content_hash,path,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
        rows = self._query("SELECT * FROM sdd_decisions ORDER BY id")
        return [
            Decision(
                id=row["id"],
                title=row.get("title") or "",
                status=DecisionStatus(row["status"]),
                decided_at=row.get("decided_at") or "",
                scope=tuple(_loads(row.get("scope"))),
                tags=tuple(_loads(row.get("tags"))),
                superseded_by=row.get("superseded_by") or "",
                body=row.get("body") or "",
                path=row.get("path") or "",
            )
            for row in rows
        ]

    # ---------- 代码索引 ----------
    def replace_symbols(self, symbols: Iterable[Symbol]) -> None:
        self._execute("DELETE FROM sdd_symbols")
        for symbol in symbols:
            self._execute(
                "REPLACE INTO sdd_symbols (path,qualname,kind,line) VALUES (?,?,?,?)",
                (symbol.path, symbol.qualname, symbol.kind, symbol.line),
            )
        self._commit()

    def list_symbols(self) -> list[Symbol]:
        rows = self._query("SELECT * FROM sdd_symbols ORDER BY path, qualname")
        return [
            Symbol(path=r["path"], qualname=r["qualname"], kind=r.get("kind") or "", line=r.get("line") or 0)
            for r in rows
        ]

    def replace_files(self, paths: Iterable[str]) -> None:
        self._execute("DELETE FROM sdd_files")
        for path in paths:
            self._execute("REPLACE INTO sdd_files (path) VALUES (?)", (path,))
        self._commit()

    def list_files(self) -> list[str]:
        return [r["path"] for r in self._query("SELECT path FROM sdd_files ORDER BY path")]

    def replace_tests(self, tests: Iterable[TestCase]) -> None:
        self._execute("DELETE FROM sdd_tests")
        for test in tests:
            self._execute(
                "REPLACE INTO sdd_tests (test_id,path,covers) VALUES (?,?,?)",
                (
                    test.test_id,
                    test.path,
                    json.dumps(list(test.covers), ensure_ascii=False),
                ),
            )
        self._commit()

    def list_tests(self) -> list[TestCase]:
        rows = self._query("SELECT * FROM sdd_tests ORDER BY test_id")
        return [
            TestCase(path=r.get("path") or "", test_id=r["test_id"], covers=tuple(_loads(r.get("covers"))))
            for r in rows
        ]

    # ---------- 评审 ----------
    def set_review(self, review: Review) -> None:
        self._execute(
            "REPLACE INTO sdd_reviews (spec_id,content_hash,reviewed_at,note) VALUES (?,?,?,?)",
            (review.spec_id, review.content_hash, review.reviewed_at, review.note),
        )
        self._commit()

    def get_review(self, spec_id: str) -> Review | None:
        rows = self._query("SELECT * FROM sdd_reviews WHERE spec_id=?", (spec_id,))
        if not rows:
            return None
        row = rows[0]
        return Review(
            spec_id=row["spec_id"],
            content_hash=row.get("content_hash") or "",
            reviewed_at=row.get("reviewed_at") or "",
            note=row.get("note") or "",
        )

    def list_reviews(self) -> list[Review]:
        return [
            Review(
                spec_id=r["spec_id"],
                content_hash=r.get("content_hash") or "",
                reviewed_at=r.get("reviewed_at") or "",
                note=r.get("note") or "",
            )
            for r in self._query("SELECT * FROM sdd_reviews ORDER BY spec_id")
        ]

    def stats(self) -> dict[str, Any]:
        def count(table: str) -> int:
            rows = self._query(f"SELECT COUNT(*) AS n FROM {table}")
            return int(rows[0]["n"]) if rows else 0

        return {
            "specs": count("sdd_specs"),
            "decisions": count("sdd_decisions"),
            "symbols": count("sdd_symbols"),
            "files": count("sdd_files"),
            "tests": count("sdd_tests"),
            "reviews": count("sdd_reviews"),
        }


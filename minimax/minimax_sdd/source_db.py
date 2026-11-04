"""Minimal SourceDB proposal. No connection or environment reads at import time.

SQL compatibility and real integration remain unverified. Only seekdb/OceanBase
may serve as SourceDB; the PowerContext SQLite state store is a separate role.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping


TABLE = "minimax_sdd_sources"
KINDS = frozenset({"spec", "code", "test"})
COLUMNS = "logical_key, kind, source_path, revision, content_sha256, content"
CREATE_SQL = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    project_id VARCHAR(64) NOT NULL,
    logical_key VARCHAR(128) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    source_path VARCHAR(1024) NOT NULL,
    revision VARCHAR(64) NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    content LONGTEXT NOT NULL,
    PRIMARY KEY (project_id, logical_key)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"""
UPSERT_SQL = f"""INSERT INTO {TABLE}
    (project_id, logical_key, kind, source_path, revision, content_sha256, content)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE kind=%s, source_path=%s, revision=%s,
    content_sha256=%s, content=%s"""


class SourceError(Exception):
    """An intentionally safe diagnostic, never the raw driver exception."""


def require_text(value, label, maximum=None):
    if not isinstance(value, str) or not value.strip() or (maximum and len(value) > maximum):
        raise SourceError(f"Invalid or missing {label}.")
    return value


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    user: str
    database: str
    password: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None):
        env = os.environ if environ is None else environ
        try:
            port = int(env.get("MINIMAX_DB_PORT", "2881"))
        except (ValueError, TypeError):
            raise SourceError("MINIMAX_DB_PORT must be an integer.") from None
        if not 1 <= port <= 65535:
            raise SourceError("MINIMAX_DB_PORT must be between 1 and 65535.")
        return cls(
            host=require_text(env.get("MINIMAX_DB_HOST", "127.0.0.1"), "MINIMAX_DB_HOST"),
            port=port,
            user=require_text(env.get("MINIMAX_DB_USER"), "MINIMAX_DB_USER"),
            database=require_text(env.get("MINIMAX_DB_DATABASE"), "MINIMAX_DB_DATABASE"),
            password=env.get("MINIMAX_DB_PASSWORD", ""),
        )


def safe_driver_error(operation, exc):
    # Only a numeric server/driver error code is retained. Never stringify exc.
    code = exc.args[0] if exc.args and type(exc.args[0]) is int else None
    suffix = f" (code {code})" if code is not None else ""
    return SourceError(f"SourceDB {operation} failed{suffix}; check the reviewed setup.")


@dataclass(frozen=True)
class SourceDocument:
    logical_key: str
    kind: str
    source_path: str
    revision: str
    content_sha256: str
    content: str

    def __post_init__(self):
        require_text(self.logical_key, "logical_key", 128)
        require_text(self.source_path, "source_path", 1024)
        require_text(self.revision, "revision", 64)
        if self.kind not in KINDS:
            raise SourceError("Document kind must be spec, code or test.")
        if not isinstance(self.content, str):
            raise SourceError("Document content must be text.")
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 != digest:
            raise SourceError("Source document content SHA256 mismatch.")

    @classmethod
    def from_row(cls, row):
        try:
            return cls(**{key: row[key] for key in cls.__dataclass_fields__})
        except (KeyError, TypeError):
            raise SourceError("SourceDB returned an invalid document row.") from None

    def upsert_params(self, project_id):
        values = (self.kind, self.source_path, self.revision, self.content_sha256, self.content)
        return (project_id, self.logical_key, *values, *values)


def like_pattern(term):
    require_text(term, "query term")
    # '=' avoids dependence on the backslash escape mode of the SQL session.
    escaped = term.replace("=", "==").replace("%", "=%").replace("_", "=_")
    return "%" + escaped + "%"


def search_statement(project_id, terms):
    require_text(project_id, "project_id", 64)
    if not isinstance(terms, (list, tuple)) or not terms:
        raise SourceError("At least one query term is required.")
    clauses = []
    params = [project_id]
    for term in terms:
        pattern = like_pattern(term)
        clauses.append("(content LIKE %s ESCAPE '=' OR source_path LIKE %s ESCAPE '=' OR logical_key LIKE %s ESCAPE '=')")
        params.extend((pattern, pattern, pattern))
    sql = f"SELECT {COLUMNS} FROM {TABLE} WHERE project_id=%s AND (" + " OR ".join(clauses) + ") ORDER BY logical_key"
    return sql, tuple(params)


@dataclass(frozen=True)
class SearchResult:
    documents: tuple[SourceDocument, ...]
    sql: str
    params: tuple


class SourceDB:
    def __init__(self, config: DBConfig):
        self.config = config

    def _connect(self):
        try:
            import pymysql  # Lazy; no driver imported by offline pure checks.
        except ImportError:
            raise SourceError("PyMySQL is unavailable; use the reviewed dependency version.") from None
        try:
            return pymysql.connect(
                host=self.config.host, port=self.config.port, user=self.config.user,
                password=self.config.password, database=self.config.database,
                charset="utf8mb4", use_unicode=True,
                cursorclass=pymysql.cursors.DictCursor, autocommit=False,
                connect_timeout=5, read_timeout=15, write_timeout=15,
                local_infile=False, read_default_file=None, read_default_group=None,
            )
        except Exception as exc:
            raise safe_driver_error("connection", exc) from None

    @contextmanager
    def _session(self, operation, write=False):
        connection = self._connect()
        try:
            yield connection
            if write:
                connection.commit()
        except Exception as exc:
            if write:
                try:
                    connection.rollback()
                except Exception:
                    pass
            if isinstance(exc, SourceError):
                raise
            raise safe_driver_error(operation, exc) from None
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def init_schema(self):
        with self._session("schema initialization", write=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(CREATE_SQL)

    def upsert(self, project_id, documents):
        require_text(project_id, "project_id", 64)
        documents = tuple(documents)
        if not documents or len({doc.logical_key for doc in documents}) != len(documents):
            raise SourceError("Import must contain unique logical keys and at least one document.")
        affected = 0
        with self._session("import", write=True) as connection:
            with connection.cursor() as cursor:
                for document in documents:
                    # execute, not executemany: all 12 placeholders are bound,
                    # including the UPDATE clause; no driver fast-path ambiguity.
                    cursor.execute(UPSERT_SQL, document.upsert_params(project_id))
                    affected += cursor.rowcount
        return {"documents_submitted": len(documents), "rows_affected": affected}

    def search(self, project_id, terms):
        sql, params = search_statement(project_id, terms)
        with self._session("query") as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                documents = tuple(SourceDocument.from_row(row) for row in cursor.fetchall())
        return SearchResult(documents, sql, params)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise SourceError("Cannot read the requested UTF-8 JSON input.") from None


def load_manifest(path, source_root):
    payload = read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("documents"), list):
        raise SourceError("Import manifest must contain a documents list.")
    try:
        root = Path(source_root).resolve(strict=True)
        if not root.is_dir():
            raise SourceError("Source root must be a directory.")
        documents = []
        for item in payload["documents"]:
            relative = Path(require_text(item.get("path"), "manifest path"))
            if relative.is_absolute():
                raise SourceError("Source paths must be relative to the source root.")
            source = (root / relative).resolve(strict=True)
            actual_relative = source.relative_to(root)
            if not source.is_file():
                raise SourceError("Each source must be an existing file.")
            raw = source.read_bytes()
            content = raw.decode("utf-8")
            documents.append(SourceDocument(
                logical_key=item.get("logical_key"), kind=item.get("kind"),
                source_path=actual_relative.as_posix(), revision=item.get("revision"),
                content_sha256=hashlib.sha256(raw).hexdigest(), content=content,
            ))
        return tuple(documents)
    except SourceError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        raise SourceError("Invalid manifest or source outside the selected root.") from None


def assemble_context(task, result: SearchResult):
    # No filesystem access here: every source body came from result.documents.
    if not isinstance(task, dict):
        raise SourceError("Task input must be an object.")
    task_id = require_text(task.get("task_id"), "task_id")
    request = require_text(task.get("request"), "request")
    required = task.get("required_sources")
    if not isinstance(required, list) or not required:
        raise SourceError("Task must declare its required sources.")
    by_key = {doc.logical_key: doc for doc in result.documents}
    if len(by_key) != len(result.documents):
        raise SourceError("SourceDB returned duplicate logical keys.")
    required_kinds = set()
    for item in required:
        if not isinstance(item, dict):
            raise SourceError("Each required source must be an object.")
        key = require_text(item.get("logical_key"), "required logical_key")
        kind = item.get("kind")
        if kind not in KINDS:
            raise SourceError("Required source kind must be spec, code or test.")
        required_kinds.add(kind)
        doc = by_key.get(key)
        if doc is None:
            raise SourceError(f"Missing required source: {key}.")
        expected_path = item.get("source_path", item.get("path"))
        if doc.kind != kind or (expected_path is not None and doc.source_path != expected_path):
            raise SourceError(f"Required source metadata mismatch: {key}.")
        if "revision" in item and doc.revision != item["revision"]:
            raise SourceError(f"Required source revision mismatch: {key}.")
    if required_kinds != KINDS:
        raise SourceError("Task must declare necessary spec, code and test sources.")
    return {
        "task_id": task_id, "request": request,
        "sources": [asdict(doc) for doc in result.documents],
        "database_query": {"sql": result.sql, "params": list(result.params), "rows_returned": len(result.documents)},
    }

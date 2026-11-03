"""SDD 上下文管理系统。

一句话：让 AI 开发助手在开工前拿到 **当前有效** 的规格、代码与测试，
并且明确知道哪些决策已经失效、哪些先前的验证已经过期。

默认零外部依赖：嵌入式 SQLite + 标准库，离线可跑。
"""

from .assistant import AssistantRuntime, ContextPacket
from .drift import DriftChecker
from .frontmatter import FrontmatterError, parse_document, parse_yaml
from .indexer import CodeIndex, index_root
from .ingestion import IngestionError, load_tree, parse_decision, parse_spec
from .models import (
    CodeRef,
    ContextBundle,
    Decision,
    DecisionStatus,
    Finding,
    Requirement,
    Severity,
    Spec,
    SpecStatus,
    Symbol,
    TestCase,
    TestRef,
)
from .resolver import ContextResolver
from .store import ContextStore, Review, SqliteStore

__version__ = "1.0.0"

__all__ = [
    "AssistantRuntime",
    "CodeIndex",
    "CodeRef",
    "ContextBundle",
    "ContextPacket",
    "ContextResolver",
    "ContextStore",
    "Decision",
    "DecisionStatus",
    "DriftChecker",
    "Finding",
    "FrontmatterError",
    "IngestionError",
    "Requirement",
    "Review",
    "Severity",
    "Spec",
    "SpecStatus",
    "SqliteStore",
    "Symbol",
    "TestCase",
    "TestRef",
    "index_root",
    "load_tree",
    "parse_decision",
    "parse_document",
    "parse_spec",
    "parse_yaml",
]


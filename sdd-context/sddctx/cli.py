"""命令行入口：`python -m sddctx <命令>`。

命令一览：
    init        建库（嵌入式 SQLite，默认 .sddctx/context.db）
    index       索引代码与测试
    ingest      导入 spec/ 下的规格与决策
    refresh     index + ingest + 体检摘要
    context     按开发任务取上下文包（markdown / json）
    doctor      上下文有效性体检（有 error 时退出码为 1）
    review      把某份规格标记为"已评审"
    assistant   生成给 AI 助手的提示词与清单
    serve       起本地 HTTP 接口
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .assistant import AssistantRuntime
from .drift import DriftChecker
from .indexer import index_root
from .ingestion import IngestionError, load_tree
from .models import Severity
from .resolver import ContextResolver
from .reviews import save_review
from .server import serve
from .store import Review, SqliteStore

DEFAULT_DB = ".sddctx/context.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sddctx",
        description="SDD 上下文管理系统：让 AI 开发助手拿到当前有效的规格、代码与测试",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"存储路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--root", default=".", help="被管理的代码根目录（默认当前目录）")
    parser.add_argument("--spec-dir", default="", help="规格目录（默认 <root>/spec）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="建库")
    sub.add_parser("index", help="索引代码与测试")
    sub.add_parser("ingest", help="导入规格与决策")

    refresh = sub.add_parser("refresh", help="索引 + 导入 + 体检摘要")
    refresh.add_argument("--json", action="store_true", help="以 JSON 输出")

    ctx = sub.add_parser("context", help="按开发任务取上下文包")
    ctx.add_argument("--task", required=True, help="开发任务描述")
    ctx.add_argument("--scope", default="", help="限定范围，逗号分隔")
    ctx.add_argument("--tags", default="", help="附加标签，逗号分隔")
    ctx.add_argument("--changed", default="", help="本次改动的文件，逗号分隔")
    ctx.add_argument("--format", choices=["markdown", "json"], default="markdown")

    doctor = sub.add_parser("doctor", help="上下文有效性体检")
    doctor.add_argument("--json", action="store_true", help="以 JSON 输出")
    doctor.add_argument("--spec", default="", help="只检查指定规格（逗号分隔）")

    review = sub.add_parser("review", help="把规格标记为已评审")
    review.add_argument("spec", help="规格 id")
    review.add_argument("--note", default="", help="备注")

    assistant = sub.add_parser("assistant", help="生成 AI 助手的提示词与清单")
    assistant.add_argument("--task", required=True, help="开发任务描述")
    assistant.add_argument("--changed", default="", help="本次改动的文件，逗号分隔")
    assistant.add_argument("--json", action="store_true", help="以 JSON 输出")

    server = sub.add_parser("serve", help="起本地 HTTP 接口")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)

    return parser


def _print_findings(findings: list, as_json: bool) -> None:
    if as_json:
        print(json.dumps([f.to_dict() for f in findings], ensure_ascii=False, indent=2))
        return
    if not findings:
        print("上下文体检通过：没有发现失效或漂移的上下文。")
        return
    icon = {Severity.ERROR: "[错误]", Severity.WARNING: "[提醒]", Severity.INFO: "[信息]"}
    for finding in findings:
        print(f"{icon[finding.severity]} {finding.target}  {finding.code}")
        print(f"        {finding.message}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    spec_root = Path(args.spec_dir).resolve() if args.spec_dir else root / "spec"
    store = SqliteStore(args.db)
    runtime = AssistantRuntime(store, root=root, spec_root=spec_root)

    try:
        if args.command == "init":
            print(f"已初始化上下文库：{Path(args.db).resolve()}")
            print("存储方式：嵌入式 SQLite（无需任何外部数据库实例）")
            return 0

        if args.command == "index":
            index = index_root(root)
            store.replace_files(index.files)
            store.replace_symbols(index.symbols)
            store.replace_tests(index.tests)
            print(
                f"已索引 {len(index.files)} 个文件、{len(index.symbols)} 个符号、"
                f"{len(index.tests)} 个测试用例"
            )
            return 0

        if args.command == "ingest":
            specs, decisions = load_tree(spec_root)
            for spec in specs:
                store.upsert_spec(spec, _now())
            for decision in decisions:
                store.upsert_decision(decision, _now())
            print(f"已导入 {len(specs)} 份规格、{len(decisions)} 条决策")
            return 0

        if args.command == "refresh":
            stats = runtime.refresh(_now())
            findings = runtime.checker.check()
            errors = [f for f in findings if f.severity is Severity.ERROR]
            if args.json:
                payload = {
                    "stats": stats,
                    "findings": [f.to_dict() for f in findings],
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(
                    f"索引 {stats['files']} 文件 / {stats['symbols']} 符号 / "
                    f"{stats['tests']} 测试；导入 {stats['specs']} 规格 / {stats['decisions']} 决策"
                )
                _print_findings(findings, False)
            return 1 if errors else 0

        if args.command == "context":
            resolver = ContextResolver(store, DriftChecker(store))
            bundle = resolver.resolve(
                args.task,
                scope=_split(args.scope),
                tags=_split(args.tags),
                changed_files=_split(args.changed),
            )
            if args.format == "json":
                print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(bundle.to_markdown())
            return 0

        if args.command == "doctor":
            checker = DriftChecker(store)
            findings = checker.check(spec_ids=_split(args.spec) or None)
            _print_findings(findings, args.json)
            return 1 if any(f.severity is Severity.ERROR for f in findings) else 0

        if args.command == "review":
            spec = store.get_spec(args.spec)
            if spec is None:
                print(f"找不到规格 {args.spec}", file=sys.stderr)
                return 2
            record = Review(
                spec_id=spec.id,
                content_hash=spec.content_hash,
                reviewed_at=_now(),
                note=args.note,
            )
            store.set_review(record)
            path = save_review(spec_root, record)
            print(f"已记录评审：{spec.id} @ {spec.content_hash}")
            print(f"评审基线已写入 {path}（可提交到仓库，跟着代码一起走）")
            return 0

        if args.command == "assistant":
            packet = runtime.prepare_task(
                args.task, changed_files=_split(args.changed)
            )
            if args.json:
                print(json.dumps(packet.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(packet.prompt)
                print("## 执行清单")
                for step in packet.checklist:
                    print(f"- [ ] {step}")
                if not packet.ready:
                    print("")
                    print("## 阻塞项")
                    for finding in packet.blocking:
                        print(f"- [{finding.code}] {finding.target}：{finding.message}")
            return 0 if packet.ready else 1

        if args.command == "serve":
            runtime.refresh(_now())
            serve(runtime, host=args.host, port=args.port)
            return 0
    except IngestionError as exc:
        print(f"规格解析失败：{exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


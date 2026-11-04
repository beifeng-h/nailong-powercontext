"""Import/context CLI proposal; real DB use only when explicitly invoked."""

import argparse
import asyncio
from dataclasses import asdict
import json
import sys

from .source_db import (
    DBConfig, SourceDB, SourceError, assemble_context, load_manifest, read_json,
)


def main(argv=None):
    # JSON is a UTF-8 interface even when Windows redirects stdout using GBK.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="SourceDB import and SQL-backed task context")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create the document table in the configured existing database")
    importing = commands.add_parser("import", help="upsert actual UTF-8 files by stable logical key")
    importing.add_argument("--project", required=True)
    importing.add_argument("--root", required=True)
    importing.add_argument("--manifest", required=True)
    context = commands.add_parser("context", help="build context only from actual SQL result rows")
    context.add_argument("--project", required=True)
    context.add_argument("--task", required=True)
    context.add_argument("--state-dir", help="restore saved PowerContext progress into the SQL-backed context")
    for command in ("remember", "resume"):
        state = commands.add_parser(command, help="write or restore explicit PowerContext task state")
        state.add_argument("--task", required=True)
        state.add_argument("--state-dir", required=True)
        if command == "remember":
            state.add_argument("--record", required=True, help="actual progress/verification JSON")
    args = parser.parse_args(argv)
    try:
        if args.command in ("remember", "resume"):
            from . import state
            task = read_json(args.task)
            if not isinstance(task, dict):
                raise SourceError("Task input must be an object.")
            task_id = task.get("task_id")
            if args.command == "remember":
                output = asyncio.run(state.remember(args.state_dir, task_id, read_json(args.record)))
            else:
                output = asyncio.run(state.restore(args.state_dir, task_id))
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0
        documents = load_manifest(args.manifest, args.root) if args.command == "import" else None
        task = read_json(args.task) if args.command == "context" else None
        if task is not None and not isinstance(task, dict):
            raise SourceError("Task input must be an object.")
        database = SourceDB(DBConfig.from_env())
        if args.command == "init":
            database.init_schema()
            output = {"operation": "init", "table": "minimax_sdd_sources"}
        elif args.command == "import":
            receipt = database.upsert(args.project, documents)
            output = {
                "operation": "import", "project_id": args.project, **receipt,
                "documents": [{key: value for key, value in asdict(doc).items() if key != "content"} for doc in documents],
            }
        else:
            result = database.search(args.project, task.get("query_terms"))
            output = assemble_context(task, result)
            output["project_id"] = args.project
            if args.state_dir:
                from .state import restore
                output["previous_task_state"] = asyncio.run(restore(args.state_dir, task.get("task_id")))
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except SourceError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception:
        # No raw traceback/config/driver exception text on the normal CLI path.
        print('{"error": "Unexpected local failure; connection details were not printed."}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

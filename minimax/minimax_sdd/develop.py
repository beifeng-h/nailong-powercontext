"""Single-request MiniMax MPlan development adapter proposal.

Import/prepare/parse are offline. Only run_actual() reads the dedicated key and
makes a request. No generated implementation is bundled with this proposal.
"""

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener


ENDPOINTS = {
    "intl": "https://api.minimax.io/v1/chat/completions",
    "cn": "https://api.minimax.cn/v1/chat/completions",
}
# Only this model is presently established by the reviewed MPlan setup docs.
# An active/legacy account still needs explicit entitlement/quota confirmation.
REVIEWED_MODELS = frozenset({"MiniMax-M3.1-Flash"})
KEY_ENV = "MINIMAX_MPLAN_API_KEY"
BEFORE = "business/before/taskboard.py"
AFTER = "business/after/taskboard.py"
TESTS = "tests/test_taskboard.py"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class DevelopError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _no_duplicate_keys(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise DevelopError("duplicate_json_key")
        output[key] = value
    return output


def _reject_nonfinite(value):
    raise DevelopError("nonfinite_json_number")


def strict_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_nonfinite)
    except DevelopError:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise DevelopError("invalid_json") from None


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def checked_path(root, relative, must_exist=False):
    relative = Path(relative)
    if relative.is_absolute():
        raise DevelopError("path_must_be_relative")
    candidate = root / relative
    current = root
    for part in relative.parts:
        if part in ("..", "."):
            raise DevelopError("path_traversal_rejected")
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise DevelopError("linked_path_rejected")
    resolved = candidate.resolve(strict=must_exist)
    if not resolved.is_relative_to(root):
        raise DevelopError("path_outside_project")
    return resolved


@dataclass(frozen=True)
class RunConfig:
    region: str
    endpoint: str
    model: str
    entitlement_confirmed: bool
    max_completion_tokens: int = 4096
    timeout_seconds: int = 60

    def validate(self):
        if self.region not in ENDPOINTS or self.endpoint != ENDPOINTS[self.region]:
            raise DevelopError("regional_endpoint_mismatch")
        if self.model not in REVIEWED_MODELS:
            raise DevelopError("model_not_reviewed_for_plan")
        if not 1 <= self.max_completion_tokens <= 8192 or not 1 <= self.timeout_seconds <= 120:
            raise DevelopError("invalid_explicit_run_limits")


def validate_context(task, context, before_sha, tests_sha):
    if not isinstance(task, dict) or not isinstance(context, dict):
        raise DevelopError("task_and_context_must_be_objects")
    task_id = task.get("task_id")
    if not nonempty(task_id) or context.get("task_id") != task_id:
        raise DevelopError("task_context_id_mismatch")
    if not nonempty(task.get("request")) or context.get("request") != task["request"]:
        raise DevelopError("task_context_request_mismatch")
    query = context.get("database_query")
    sources = context.get("sources")
    if (not isinstance(query, dict) or not nonempty(query.get("sql"))
        or not query["sql"].lstrip().upper().startswith("SELECT ")
        or not isinstance(query.get("params"), list) or not query["params"]
        or not isinstance(sources, list) or not sources
        or query.get("rows_returned") != len(sources)
        or query["params"][0] != context.get("project_id")):
        raise DevelopError("actual_database_context_required")
    by_key = {}
    for source in sources:
        if not isinstance(source, dict) or not nonempty(source.get("logical_key")):
            raise DevelopError("invalid_database_source")
        if source["logical_key"] in by_key or not isinstance(source.get("content"), str):
            raise DevelopError("invalid_database_source")
        if digest(source["content"].encode("utf-8")) != source.get("content_sha256"):
            raise DevelopError("database_source_hash_mismatch")
        by_key[source["logical_key"]] = source
    required = task.get("required_sources")
    if not isinstance(required, list) or not required:
        raise DevelopError("required_sources_not_declared")
    kinds = set()
    for item in required:
        if not isinstance(item, dict):
            raise DevelopError("invalid_required_source")
        source = by_key.get(item.get("logical_key"))
        if source is None or source.get("kind") != item.get("kind"):
            raise DevelopError("required_database_source_missing")
        kinds.add(source.get("kind"))
        path = item.get("source_path", item.get("path"))
        if (path is not None and source.get("source_path") != path) or ("revision" in item and source.get("revision") != item["revision"]):
            raise DevelopError("required_database_source_stale")
    if kinds != {"spec", "code", "test"}:
        raise DevelopError("spec_code_tests_required")
    for path, sha, kind in [(BEFORE, before_sha, "code"), (TESTS, tests_sha, "test")]:
        if not any(source.get("source_path") == path and source.get("kind") == kind
                   and source.get("content_sha256") == sha for source in sources):
            raise DevelopError("database_context_input_binding_mismatch")
    previous = context.get("previous_task_state")
    if not isinstance(previous, dict) or not isinstance(previous.get("state"), dict):
        raise DevelopError("restored_powercontext_state_required")
    state = previous["state"]
    pending = state.get("pending")
    if (state.get("task_id") != task_id or not isinstance(state.get("completed"), list)
        or not isinstance(pending, list) or not pending or not all(nonempty(value) for value in pending)
        or not state.get("verification") or not isinstance(state["verification"], (dict, list))
        or not isinstance(previous.get("citation"), dict) or not previous["citation"]
        or previous.get("next_step") != pending[0]):
        raise DevelopError("restored_powercontext_state_incomplete")
    return previous["next_step"]


def actual_git_head(root):
    try:
        # Git needs the caller's normal environment, but never the model key.
        # Filter names before looking up values so the key itself is not read.
        git_env = {name: os.environ[name] for name in os.environ if name.upper() != KEY_ENV}
        result = subprocess.run(
            ["git", "--no-lazy-fetch", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False, env=git_env,
        )
        head = result.stdout.decode("ascii").strip()
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise DevelopError("source_git_head_unavailable") from None
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise DevelopError("source_git_head_unavailable")
    return head


def prepare(root, task_relative, context_relative, source_version, expected_before_sha, expected_tests_sha, config,
            *, allow_existing_after=False):
    config.validate()
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or not re.fullmatch(r"[0-9a-fA-F]{40}", source_version):
        raise DevelopError("invalid_source_version_or_project_root")
    git_head = actual_git_head(root)
    if git_head != source_version.lower():
        raise DevelopError("expected_source_version_does_not_match_head")
    task_raw = checked_path(root, task_relative, True).read_bytes()
    context_raw = checked_path(root, context_relative, True).read_bytes()
    before_raw = checked_path(root, BEFORE, True).read_bytes()
    tests_raw = checked_path(root, TESTS, True).read_bytes()
    if digest(before_raw) != expected_before_sha or digest(tests_raw) != expected_tests_sha:
        raise DevelopError("expected_input_hash_mismatch")
    after = checked_path(root, AFTER)
    if os.path.lexists(after) and not allow_existing_after:
        raise DevelopError("after_must_be_fresh")
    task, context = strict_json(task_raw), strict_json(context_raw)
    next_step = validate_context(task, context, digest(before_raw), digest(tests_raw))
    user = {
        "task": task, "retrieved_context": context,
        "next_step_from_restored_powercontext": next_step,
        "allowed_output_path": AFTER,
        "constraints": "Modify only the business implementation. Keep specifications and fixed tests unchanged. Return complete source, no reasoning or commentary.",
    }
    payload = {
        "model": config.model, "stream": False, "reasoning_split": True,
        "max_completion_tokens": config.max_completion_tokens,
        "messages": [
            {"role": "system", "content": 'Return strictly one JSON object with exactly keys "path" and "code". path must be "business/after/taskboard.py". code must be the complete Python file. Do not include markdown, explanations, thinking, extra paths or test changes.'},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }
    return {"root": root, "task_raw": task_raw, "context_raw": context_raw,
            "before_raw": before_raw, "tests_raw": tests_raw, "payload": payload,
            "request_raw": json_bytes(payload), "source_version": git_head}


def parse_final(raw, expected_model):
    data = strict_json(raw)
    if not isinstance(data, dict):
        raise DevelopError("provider_response_not_object")
    application = data.get("base_resp")
    if application is not None and (not isinstance(application, dict) or application.get("status_code") != 0):
        raise DevelopError("provider_application_error")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise DevelopError("provider_choices_invalid")
    choice = choices[0]
    message = choice.get("message")
    if (choice.get("finish_reason") != "stop" or not isinstance(message, dict)
        or message.get("role") != "assistant" or message.get("tool_calls")):
        raise DevelopError("provider_completion_not_final")
    final = message.get("content")
    if not nonempty(final) or any(tag in final.lower() for tag in ("<think", "</think", "<reasoning", "</reasoning")):
        raise DevelopError("provider_final_content_invalid")
    output = strict_json(final)
    if not isinstance(output, dict) or set(output) != {"path", "code"} or output.get("path") != AFTER or not nonempty(output.get("code")):
        raise DevelopError("provider_output_not_allowlisted_json")
    try:
        tree = ast.parse(output["code"])
    except (SyntaxError, ValueError, TypeError):
        raise DevelopError("provider_python_syntax_invalid") from None
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "list_tasks"]
    if len(functions) != 1:
        raise DevelopError("provider_required_function_missing")
    if not nonempty(data.get("id")) or len(data["id"]) > 256 or data.get("model") != expected_model:
        raise DevelopError("provider_identity_invalid")
    usage_in = data.get("usage")
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if not isinstance(usage_in, dict) or not all(type(usage_in.get(key)) is int and usage_in[key] >= 0 for key in keys):
        raise DevelopError("provider_usage_invalid")
    usage = {key: usage_in[key] for key in keys}
    details = usage_in.get("prompt_tokens_details")
    if isinstance(details, dict) and type(details.get("cached_tokens")) is int and details["cached_tokens"] >= 0:
        usage["prompt_tokens_details"] = {"cached_tokens": details["cached_tokens"]}
    # Never copy the whole message/data; reasoning and raw body stay in memory.
    metadata = {"id": data["id"], "model": data["model"], "usage": usage, "finish_reason": "stop"}
    return output, metadata


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def write_fresh(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)


def check_no_secret(key, blobs):
    if any(key.encode("utf-8") in blob for blob in blobs):
        raise DevelopError("credential_detected_in_persistable_data")


def run_actual(prepared, config, run_relative):
    config.validate()
    if not config.entitlement_confirmed:
        raise DevelopError("actual_plan_entitlement_and_quota_not_confirmed")
    root = prepared["root"]
    after = checked_path(root, AFTER)
    if os.path.lexists(after):
        raise DevelopError("after_must_be_fresh")
    # This is the sole key source. No generic-key/region/model/billing fallback.
    key = os.environ.get(KEY_ENV)
    if not nonempty(key) or any(char.isspace() for char in key):
        raise DevelopError("dedicated_plan_key_not_ready")
    run_parts = Path(run_relative).parts
    if len(run_parts) < 3 or run_parts[:2] != ("evidence", "minimax"):
        raise DevelopError("run_directory_not_in_evidence_allowlist")
    run_dir = checked_path(root, run_relative)
    if os.path.lexists(run_dir):
        raise DevelopError("run_directory_must_be_fresh")
    inputs = {"task.json": prepared["task_raw"], "context.json": prepared["context_raw"],
              "before.py": prepared["before_raw"], "fixed-tests.py": prepared["tests_raw"],
              "request.json": prepared["request_raw"]}
    check_no_secret(key, list(inputs.values()))
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    run_dir = checked_path(root, run_relative)
    run_dir.mkdir(exist_ok=False)
    for name, raw in inputs.items():
        write_fresh(run_dir / name, raw)
    started = {"status": "request_started", "started_utc": datetime.now(timezone.utc).isoformat(),
               "endpoint": config.endpoint, "region": config.region, "requested_model": config.model,
               "key_environment_name": KEY_ENV, "requests_allowed": 1,
               "max_completion_tokens": config.max_completion_tokens, "source_version": prepared["source_version"],
               "input_sha256": {name: digest(raw) for name, raw in inputs.items()}}
    write_fresh(run_dir / "attempt-started.json", json_bytes(started))
    response_received = False
    applied = False
    try:
        # TLS verification uses the platform trust store. No environment proxy
        # inheritance or redirect can substitute a new credential destination.
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
        request = Request(config.endpoint, data=prepared["request_raw"], method="POST",
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=config.timeout_seconds) as response:
                if response.status != 200:
                    raise DevelopError("http_status_not_success")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            status = exc.code
            exc.close()  # Do not read/save the provider error body.
            raise DevelopError(f"http_error_{status}") from None
        except (URLError, TimeoutError, OSError):
            raise DevelopError("transport_outcome_unknown_do_not_retry") from None
        response_received = True
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DevelopError("provider_response_too_large")
        output, metadata = parse_final(raw, config.model)
        del raw
        code_raw = output["code"].encode("utf-8")
        if digest(code_raw) == digest(prepared["before_raw"]):
            raise DevelopError("provider_returned_unchanged_code")
        if (checked_path(root, BEFORE, True).read_bytes() != prepared["before_raw"]
            or checked_path(root, TESTS, True).read_bytes() != prepared["tests_raw"]):
            raise DevelopError("inputs_changed_during_request")
        diff = "\n".join(difflib.unified_diff(
            prepared["before_raw"].decode("utf-8").splitlines(), output["code"].splitlines(),
            fromfile=BEFORE, tofile=AFTER, lineterm="")) + "\n"
        final_record = {**output, **metadata}
        check_no_secret(key, [json_bytes(final_record), diff.encode("utf-8")])
        write_fresh(run_dir / "model-final.json", json_bytes(final_record))
        write_fresh(run_dir / "application.diff", diff.encode("utf-8"))
        after.parent.mkdir(parents=True, exist_ok=True)
        after = checked_path(root, AFTER)
        write_fresh(after, code_raw)  # Exclusive create, never overwrite.
        applied = True
        result = {"status": "code_saved_not_tested", "completed_utc": datetime.now(timezone.utc).isoformat(),
                  "source_version": prepared["source_version"], "before_sha256": digest(prepared["before_raw"]),
                  "tests_sha256": digest(prepared["tests_raw"]), "after_path": AFTER,
                  "after_sha256": digest(code_raw), "response": metadata,
                  "functional_or_regression_result": "not_run"}
        write_fresh(run_dir / "attempt-result.json", json_bytes(result))
        return result
    except Exception as exc:
        code = exc.code if isinstance(exc, DevelopError) else "local_outcome_requires_inspection"
        failure = {"status": "failed_or_incomplete_no_automatic_retry", "error_code": code,
                   "response_received": response_received, "after_write_completed": applied,
                   "inspect_partial_artifacts_before_any_retry": True}
        try:
            write_fresh(run_dir / "attempt-result.json", json_bytes(failure))
        except Exception:
            pass
        raise DevelopError(code) from None
    finally:
        key = None


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="One explicitly configured MiniMax MPlan development request")
    parser.add_argument("--root", required=True)
    parser.add_argument("--task", required=True, help="relative task JSON under root")
    parser.add_argument("--context", required=True, help="actual SQL+restored-PC context JSON under root")
    parser.add_argument("--region", required=True, choices=tuple(ENDPOINTS))
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--expected-before-sha256", required=True)
    parser.add_argument("--expected-tests-sha256", required=True)
    parser.add_argument("--max-completion-tokens", type=int, default=4096)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--run-dir", required=True, help="fresh relative evidence directory")
    parser.add_argument("--confirm-mplan-entitlement-and-quota", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="offline preflight; does not read key or write output")
    args = parser.parse_args(argv)
    try:
        config = RunConfig(args.region, args.endpoint, args.model,
                           args.confirm_mplan_entitlement_and_quota,
                           args.max_completion_tokens, args.timeout_seconds)
        prepared = prepare(args.root, args.task, args.context, args.source_version,
                           args.expected_before_sha256, args.expected_tests_sha256, config,
                           allow_existing_after=args.check_only)
        if args.check_only:
            print(json.dumps({"status": "offline_preflight_only", "actual_model_call": False,
                              "before_sha256": digest(prepared["before_raw"]),
                              "tests_sha256": digest(prepared["tests_raw"])}))
            return 0
        result = run_actual(prepared, config, args.run_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except DevelopError as exc:
        print(json.dumps({"error_code": exc.code, "automatic_retry": False}), file=sys.stderr)
        return 2
    except Exception:
        print('{"error_code":"local_preflight_failure","automatic_retry":false}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fetch pinned browser assets, without installing or executing any package.

Default: print a plan; no network, directory creation, or destination writes.
Deploy as PROJECT/tools/fetch_resources.py before running even plan-only mode.
Execution: --execute [--include-optional-text] [--root EXACT_PROJECT_ROOT].
The only root is Path(__file__).resolve().parents[1]; --root must resolve to it.
Symlink/reparse ancestors are refused before resolving the script or root.
Evidence is a fresh root/artifacts/browser-resource-fetch-* directory. Downloads
are one attempt each: 20s socket timeout, --timeout-seconds total per HTTP file
(deadline checked between read1 calls, so an in-flight read may add at most 20s).
Failures retain partial downloads and a failure receipt; they are not completion.
Only regular, explicitly named tar members are read with extractfile; no package
scripts, tar extraction, models, browser, or runtime are ever executed here.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

MODEL = "Xenova/all-MiniLM-L6-v2"
REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
NPM_URL = "https://registry.npmjs.org/@huggingface/transformers/-/transformers-3.8.1.tgz"
NPM_INTEGRITY = "sha512-tsTk4zVjImqdqjS8/AOZg2yNLd1z9S5v+7oUPpXaasDRwEDhB+xnglK1k5cad26lL5/ZIaeREgWWy0bs9y9pPA=="
ORT_VERSION = "1.22.0-dev.20250409-89f8206ba4"
NPM_LIMIT_BYTES = 64 * 1024 * 1024
CHUNK = 1024 * 1024
IO_TIMEOUT = 20
# The bundled file is intentional: transformers.web.min.js externalizes ORT.
RUNTIME = (
    ("package/dist/transformers.min.js", "transformers.min.js", 888173,
     "aa5002b70e789798da263f5f99c62bd3e8fcd0c119258a493c40c180648365fa"),
    ("package/dist/ort-wasm-simd-threaded.jsep.mjs", "ort-wasm-simd-threaded.jsep.mjs", 44484,
     "08fb86ec433c78bfb032c5d84a68b8e8e5a8d81268fa39e24314179a5767a5b9"),
    ("package/dist/ort-wasm-simd-threaded.jsep.wasm", "ort-wasm-simd-threaded.jsep.wasm", 21596019,
     "c46655e8a94afc45338d4cb2b840475f88e5012d524509916e505079c00bfa39"),
    ("package/LICENSE", "LICENSE.transformers.txt", 11358,
     "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),
)
COMMON = (
    ("config.json", 650, "7135149f7cffa1a573466c6e4d8423ed73b62fd2332c575bf738a0d033f70df7"),
    ("tokenizer.json", 711661, "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0"),
    ("tokenizer_config.json", 366, "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3"),
)
OPTIONAL = (
    ("special_tokens_map.json", 125, "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3"),
    ("vocab.txt", 231508, "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"),
)
WEIGHTS = (
    ("onnx/model.onnx", 90387606, "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e"),
    ("onnx/model_fp16.onnx", 45297825, "2cdb5e58291813b6d6e248ed69010100246821a367fa17b1b81ae9483744533d"),
    ("onnx/model_quantized.onnx", 22972370, "afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1"),
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def is_link_or_reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def check_chain(path):
    """Check existing path plus all ancestors; missing suffixes are permitted."""
    for item in reversed((path,) + tuple(path.parents)):
        if os.path.lexists(item):
            if is_link_or_reparse(item):
                raise ValueError(f"symlink/reparse path rejected: {item}")
            if item != path and not item.is_dir():
                raise ValueError(f"non-directory ancestor: {item}")


def absolute_clean(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("path must be absolute and contain no '..'")
    return path


def validate_root(value=None, script_path=None):
    # script_path is an internal pure-fixture seam, never a CLI option.
    script = absolute_clean(Path(__file__).absolute() if script_path is None else script_path)
    check_chain(script)
    if script.name != "fetch_resources.py" or script.parent.name != "tools" or not script.is_file():
        raise ValueError("deploy this proposal as PROJECT/tools/fetch_resources.py before running it")
    root = script.resolve(strict=True).parents[1]
    check_chain(root)
    if value is not None:
        requested = absolute_clean(value)
        check_chain(requested)
        if not requested.is_dir() or requested.resolve(strict=True) != root:
            raise ValueError("--root must resolve exactly to this script's project root")
    return root


def safe_path(root, relative):
    relative = PurePosixPath(relative)
    if relative.is_absolute() or not relative.parts or any(
            x in ("", ".", "..") or "\\" in x or ":" in x or "\x00" in x
            for x in relative.parts):
        raise ValueError(f"unsafe relative path: {relative}")
    target = root.joinpath(*relative.parts)
    target.relative_to(root)
    check_chain(target)
    return target


def mkdir_safe(root, target):
    relative = target.relative_to(root)
    check_chain(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if not os.path.lexists(cursor):
            cursor.mkdir()  # FileExistsError on a concurrent creator is safe failure.
        check_chain(cursor)
        if not cursor.is_dir():
            raise ValueError(f"directory required: {cursor}")


def digest_file(path, algorithm="sha256"):
    checksum = hashlib.new(algorithm)
    count = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            checksum.update(block)
            count += len(block)
    return count, checksum.hexdigest()


def matches(path, expected_bytes, expected_sha256):
    check_chain(path)
    if not os.path.lexists(path):
        return False
    if not path.is_file():
        raise ValueError(f"existing target is not a regular file: {path}")
    actual = digest_file(path)
    if actual != (expected_bytes, expected_sha256):
        raise ValueError(f"existing target conflicts (will not overwrite): {path}")
    return True


def resource_plan(root, optional=False):
    resources = []
    for member, name, size, sha256 in RUNTIME:
        resources.append(dict(kind="runtime", source=NPM_URL, tar_member=member,
                              relative=f"public/vendor/{name}", expected_bytes=size,
                              expected_sha256=sha256))
    prefix = f"public/models/{REVISION}/{MODEL}"
    for name, size, sha256 in COMMON + WEIGHTS + (OPTIONAL if optional else ()):
        resources.append(dict(kind="model", source=f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}",
                              relative=f"{prefix}/{name}", expected_bytes=size,
                              expected_sha256=sha256, optional=name in {x[0] for x in OPTIONAL}))
    for item in resources:
        item["target"] = str(safe_path(root, item["relative"]))
        item["reuse"] = matches(Path(item["target"]), item["expected_bytes"], item["expected_sha256"])
    common_bytes = sum(x[1] for x in COMMON)
    optional_bytes = sum(x[1] for x in OPTIONAL) if optional else 0
    return dict(schema=1, mode="plan", root=str(root), model=MODEL, revision=REVISION,
                runtime_version="3.8.1", onnxruntime_web=ORT_VERSION,
                npm_integrity=NPM_INTEGRITY, resources=resources,
                size_accounting=dict(common_minimum_bytes=common_bytes,
                    optional_text_bytes=optional_bytes,
                    model_packages=[dict(weight=name, common_plus_weight_bytes=common_bytes + size,
                                         with_optional_text_bytes=common_bytes + size + optional_bytes)
                                    for name, size, _ in WEIGHTS],
                    runtime_assets_bytes=sum(x[2] for x in RUNTIME),
                    runtime_includes_license=True),
                assurance="File acquisition/integrity only; not model execution or browser acceptance.")


def public_url(url):
    value = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((value.scheme, value.netloc, value.path, "", ""))


def allowed_url(url, family):
    value = urllib.parse.urlsplit(url)
    host = (value.hostname or "").lower()
    if value.scheme != "https" or value.username or value.password or value.port not in (None, 443):
        raise ValueError("only credential-free HTTPS on the standard port is permitted")
    if family == "npm":
        ok = host == "registry.npmjs.org"
    else:
        ok = (host == "huggingface.co" or host.endswith(".huggingface.co")
              or host == "hf.co" or host.endswith(".hf.co"))
    if not ok:
        raise ValueError(f"redirect outside the pinned source family: {public_url(url)}")
    return url


class NoAutomaticRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Manual redirects validate the next host before connecting and close
        # redirect bodies without draining an arbitrary response.
        return None


def open_official_response(opener, url, family, deadline, redirects):
    for hop in range(6):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("HTTP file deadline exceeded before request")
        allowed_url(url, family)
        request = urllib.request.Request(url, headers={"User-Agent": "pinned-browser-resource-fetch/1", "Accept-Encoding": "identity"})
        try:
            response = opener.open(request, timeout=min(IO_TIMEOUT, remaining))
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                error.close()
                raise
            response = error
        if response.code not in (301, 302, 303, 307, 308):
            return response
        with response:
            if hop == 5:
                raise ValueError("more than five HTTP redirects rejected")
            location = response.headers.get("Location")
            if not location:
                raise ValueError("HTTP redirect is missing Location")
            url = urllib.parse.urljoin(url, location)
            allowed_url(url, family)
            redirects.append(dict(status=response.code, target=public_url(url)))
    raise AssertionError("unreachable redirect state")


def fetch_once(url, destination, record, timeout_seconds, limit_bytes, family):
    """One GET only; retain partial file on every failure; never resume/retry."""
    allowed_url(url, family)
    redirects = record.setdefault("redirects", [])
    deadline = time.monotonic() + timeout_seconds
    # Avoid reading proxy credentials/settings from the environment. Every GET
    # uses the same verified-HTTPS, source-limited direct route.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        NoAutomaticRedirect())
    record.update(started_at=utc_now(), source=url, actual_bytes=0, partial=str(destination))
    try:
        with destination.open("xb") as output:
            with open_official_response(opener, url, family, deadline, redirects) as response:
                allowed_url(response.geturl(), family)
                record["final_source_without_query"] = public_url(response.geturl())
                record["http_status"] = response.status
                if response.status != 200:
                    raise ValueError(f"expected HTTP 200, got {response.status}")
                length = response.headers.get("Content-Length")
                record["content_length"] = length
                if length and int(length) > limit_bytes:
                    raise ValueError("Content-Length exceeds expected/allowed size")
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError("HTTP file deadline exceeded")
                    block = response.read1(CHUNK)
                    if not block:
                        break
                    output.write(block)
                    record["actual_bytes"] += len(block)
                    if record["actual_bytes"] > limit_bytes:
                        raise ValueError("download exceeds expected/allowed size")
                output.flush()
                os.fsync(output.fileno())
        if time.monotonic() > deadline:
            raise TimeoutError("HTTP file deadline exceeded")
        record["finished_at"] = utc_now()
    finally:
        if destination.exists():
            record["actual_bytes"], record["actual_sha256"] = digest_file(destination)


def verify_download(path, item):
    actual = digest_file(path)
    if actual != (item["expected_bytes"], item["expected_sha256"]):
        raise ValueError(f"size/SHA256 mismatch: {item.get('relative', path.name)}")


def read_tar_whitelist(tar_path, stage_dir, runtime=RUNTIME):
    """Require each selected member exactly once; reject all links/special types."""
    expected = {entry[0]: entry for entry in runtime}
    selected = {}
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive:
            name = member.name
            posix = PurePosixPath(name)
            if (not name or name.startswith("/") or "\\" in name or "\x00" in name
                    or any(x in ("..", ".") or ":" in x for x in posix.parts)):
                raise ValueError("unsafe name in tar; nothing extracted")
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise ValueError("tar links/special entries rejected")
            if name not in expected:
                continue
            if name in selected or not member.isfile():
                raise ValueError(f"duplicate or non-regular whitelisted tar member: {name}")
            _, _, size, checksum = expected[name]
            if member.size != size:
                raise ValueError(f"tar member size mismatch: {name}")
            destination = stage_dir / (str(len(selected)) + ".verified")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"tar member unreadable: {name}")
            with source, destination.open("xb") as output:
                remaining = size
                while remaining:
                    block = source.read(min(CHUNK, remaining))
                    if not block:
                        raise ValueError(f"truncated tar member: {name}")
                    output.write(block)
                    remaining -= len(block)
                if source.read(1):
                    raise ValueError(f"oversized tar member: {name}")
            if digest_file(destination) != (size, checksum):
                raise ValueError(f"tar member SHA256 mismatch: {name}")
            selected[name] = destination
    if set(selected) != set(expected):
        raise ValueError("missing whitelisted tar member(s)")
    return selected


def publish(root, staged, item):
    target = safe_path(root, item["relative"])
    if matches(target, item["expected_bytes"], item["expected_sha256"]):
        return "reused"
    mkdir_safe(root, target.parent)
    check_chain(target)
    try:
        # Exclusive creation: never overwrite an existing file. If interrupted,
        # preserve the partial target and reject it on the next preflight.
        with target.open("xb") as output, staged.open("rb") as source:
            shutil.copyfileobj(source, output, CHUNK)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        if matches(target, item["expected_bytes"], item["expected_sha256"]):
            return "reused"
        raise
    verify_download(target, item)
    return "published"


def sanitized_error(exc):
    return re.sub(r"https?://[^\s'\"]+", lambda m: public_url(m.group()), str(exc))


def execute(root, plan, timeout_seconds):
    evidence_name = "artifacts/browser-resource-fetch-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10]
    evidence = safe_path(root, evidence_name)
    mkdir_safe(root, evidence.parent)
    evidence.mkdir()  # Fresh evidence directory only, never reuse.
    receipt = dict(schema=1, status="incomplete", started_at=utc_now(), evidence=str(evidence),
                   plan=plan, downloads=[], results=[], runtime_tested=False, models_executed=False)
    code = 1
    try:
        resources = plan["resources"]
        runtime_needed = any(not x["reuse"] for x in resources if x["kind"] == "runtime")
        selected = {}
        if runtime_needed:
            tar_path = evidence / "transformers-3.8.1.tgz.part"
            npm_record = dict(kind="npm_tarball", expected_integrity=NPM_INTEGRITY, reuse=False)
            receipt["downloads"].append(npm_record)
            fetch_once(NPM_URL, tar_path, npm_record, timeout_seconds, NPM_LIMIT_BYTES, "npm")
            _, actual_sha512 = digest_file(tar_path, "sha512")
            expected_sha512 = base64.b64decode(NPM_INTEGRITY.removeprefix("sha512-"), validate=True).hex()
            npm_record["actual_sha512"] = actual_sha512
            if actual_sha512 != expected_sha512:
                raise ValueError("NPM dist.integrity SHA512 mismatch; tar not opened")
            npm_record["verified"] = True
            stage = evidence / "npm-members"
            stage.mkdir()
            selected = read_tar_whitelist(tar_path, stage)
        for index, item in enumerate(resources):
            result = dict(relative=item["relative"], kind=item["kind"], source=item["source"],
                          expected_bytes=item["expected_bytes"], expected_sha256=item["expected_sha256"])
            if "tar_member" in item:
                result["tar_member"] = item["tar_member"]
            receipt["results"].append(result)
            target = safe_path(root, item["relative"])
            if matches(target, item["expected_bytes"], item["expected_sha256"]):
                result["status"], result["reuse"] = "reused", True
            else:
                result["reuse"] = False
                if item["kind"] == "runtime":
                    staged = selected[item["tar_member"]]
                else:
                    staged = evidence / f"model-{index}.part"
                    record = dict(kind="model", expected_bytes=item["expected_bytes"],
                                  expected_sha256=item["expected_sha256"], reuse=False)
                    receipt["downloads"].append(record)
                    fetch_once(item["source"], staged, record, timeout_seconds, item["expected_bytes"], "hf")
                    verify_download(staged, item)
                    record["verified"] = True
                result["status"] = publish(root, staged, item)
                result["reuse"] = result["status"] == "reused"
            result["actual_bytes"], result["actual_sha256"] = digest_file(target)
        # Final complete-set verification, including initially reused resources.
        for item in resources:
            verify_download(safe_path(root, item["relative"]), item)
        receipt["status"] = "acquisition_complete_not_runtime_tested"
        code = 0
    except BaseException as exc:
        receipt["status"] = "failed_partial_preserved"
        receipt["error"] = dict(type=type(exc).__name__, message=sanitized_error(exc))
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        receipt["finished_at"] = utc_now()
        check_chain(evidence)
        with (evidence / "receipt.json").open("x", encoding="utf-8", newline="\n") as output:
            json.dump(receipt, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        print(json.dumps(dict(status=receipt["status"], receipt=str(evidence / "receipt.json")), ensure_ascii=False))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="optional absolute path that must resolve exactly to PROJECT above this script's tools directory")
    parser.add_argument("--execute", action="store_true", help="perform the pinned downloads; default is plan-only")
    parser.add_argument("--include-optional-text", action="store_true", help="also fetch fixed special_tokens_map.json and vocab.txt; accounted separately")
    parser.add_argument("--timeout-seconds", type=int, default=600, help="total HTTP deadline per file, 30..1800 (socket bound adds at most 20s)")
    args = parser.parse_args(argv)
    if not 30 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds must be in 30..1800")
    try:
        root = validate_root(args.root)
        plan = resource_plan(root, args.include_optional_text)
    except (OSError, ValueError) as exc:
        print(json.dumps(dict(status="preflight_rejected_no_download", error=sanitized_error(exc))), file=sys.stderr)
        return 2
    if not args.execute:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    return execute(root, plan, args.timeout_seconds)


if __name__ == "__main__":
    sys.exit(main())

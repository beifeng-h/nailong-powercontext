"""Run unchanged tests against one explicitly selected implementation."""

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation", type=Path, required=True)
    parser.add_argument("--suite", choices=("target", "regression", "all"), default="all")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    source_dir = args.implementation.resolve()
    source_file = source_dir / "taskboard.py"
    if not source_file.is_file():
        parser.error("implementation must contain taskboard.py")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source_dir))
    sys.path.insert(0, str(base / "tests"))
    module = importlib.import_module("taskboard")
    if Path(module.__file__).resolve() != source_file:
        raise RuntimeError("loaded taskboard from an unexpected source path")
    test_file = base / "tests" / "test_taskboard.py"
    print(json.dumps({
        "implementation": str(source_file),
        "implementation_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
        "tests_sha256": hashlib.sha256(test_file.read_bytes()).hexdigest(),
        "suite": args.suite,
        "scope": "local business fixture only; no MiniMax/DB/PowerContext claim",
    }, ensure_ascii=False), flush=True)
    names = {
        "target": ["test_taskboard.TargetBehaviorTests"],
        "regression": ["test_taskboard.RegressionBehaviorTests"],
        "all": ["test_taskboard.TargetBehaviorTests", "test_taskboard.RegressionBehaviorTests"],
    }[args.suite]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

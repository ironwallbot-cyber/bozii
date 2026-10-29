"""Sandboxed entry point for capability tools.

This module is executed as a separate process inside the sandbox:

    python -m bozii.capability_engine.runner --dir <capability dir> \
        --entry tool.py --input <json file>

The capability module is imported from its own directory and `execute(args)` is
called. The result is written to stdout prefixed with ``@@BOZII_RESULT@@`` so
any incidental prints from the capability cannot corrupt the protocol.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import traceback
from pathlib import Path

MARKER = "@@BOZII_RESULT@@"


def load_module(entry_path: Path):
    spec = importlib.util.spec_from_file_location(f"bozii_capability_{entry_path.stem}", str(entry_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load capability entry point: {entry_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def emit(payload: dict) -> None:
    sys.stdout.write("\n" + MARKER + json.dumps(payload, default=str))
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bozii capability sandbox runner")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--entry", default="tool.py")
    parser.add_argument("--input", default="")
    args = parser.parse_args(argv)

    cap_dir = Path(args.dir)
    input_path = Path(args.input) if args.input else None
    payload: dict = {}
    try:
        if input_path and input_path.exists():
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        module = load_module(cap_dir / args.entry)
        execute = getattr(module, "execute", None)
        if execute is None:
            raise AttributeError(
                f"{args.entry} does not define execute(args: dict) -> dict"
            )
        result = execute(payload)
        if not isinstance(result, dict):
            result = {"result": result}
        emit({"ok": True, "output": result})
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        emit(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=5),
            }
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

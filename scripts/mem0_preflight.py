"""Preflight for optional real Mem0 verification.

This never prints secret values. It only reports whether the local environment
has the optional package and credentials required to run ``MEMGAUGE_BACKEND=mem0``.
"""

from __future__ import annotations

import importlib.util
import os
import sys


def _ok(message: str) -> None:
    print(f"  ok {message}")


def _missing(message: str) -> None:
    print(f"  missing {message}")


def main() -> None:
    print("Mem0 optional backend preflight")
    ready = True

    if importlib.util.find_spec("mem0") is None:
        _missing("mem0ai package (`pip install mem0ai` locally; not committed)")
        ready = False
    else:
        _ok("mem0 package importable")

    has_mem0_key = bool(os.getenv("MEM0_API_KEY"))
    has_openai_key = bool(os.getenv("OPENAI_API_KEY"))
    if has_mem0_key:
        _ok("MEM0_API_KEY present")
    elif has_openai_key:
        _ok("OPENAI_API_KEY present")
    else:
        _missing("MEM0_API_KEY or OPENAI_API_KEY")
        ready = False

    backend = os.getenv("MEMGAUGE_BACKEND", "mock")
    if backend == "mem0":
        _ok("MEMGAUGE_BACKEND=mem0")
    else:
        _missing(f"MEMGAUGE_BACKEND=mem0 (currently {backend!r})")
        ready = False

    if not ready:
        print("MEM0 PREFLIGHT: NOT READY")
        sys.exit(2)

    print("MEM0 PREFLIGHT: READY")


if __name__ == "__main__":
    main()

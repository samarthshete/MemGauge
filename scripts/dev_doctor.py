"""Development environment preflight for MemGauge.

This is intentionally standard-library only so it can run before project
dependencies are installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

REQUIRED_PYTHON = (3, 11)


def _ok(message: str) -> None:
    print(f"  ok {message}")


def _fail(message: str) -> None:
    print(f"  x {message}")
    raise SystemExit(1)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)


def _check_python() -> None:
    version = sys.version_info
    if version.major != REQUIRED_PYTHON[0] or version.minor != REQUIRED_PYTHON[1]:
        _fail(
            "Python 3.11.x is required; running "
            f"{version.major}.{version.minor}.{version.micro}. "
            "Use `make venv PY311=<your-python3.11>` after installing 3.11."
        )
    _ok(f"python {version.major}.{version.minor}.{version.micro}")


def _check_module(name: str) -> None:
    result = _run([sys.executable, "-c", f"import {name}"])
    if result.returncode != 0:
        _fail(
            f"project dependency `{name}` is not importable with {sys.executable}. "
            "Run `make venv` and then re-run `make doctor`."
        )
    _ok(f"python module {name}")


def _check_docker() -> None:
    docker = shutil.which("docker")
    if docker is None:
        _fail("docker CLI not found. Install Docker Desktop or Docker Engine + Compose.")

    docker_version = _run(["docker", "--version"])
    if docker_version.returncode != 0:
        _fail(docker_version.stderr.strip() or docker_version.stdout.strip())
    _ok(docker_version.stdout.strip())

    compose_version = _run(["docker", "compose", "version"])
    if compose_version.returncode != 0:
        _fail("`docker compose version` failed. Install Docker Compose v2.")
    _ok(compose_version.stdout.strip())

    info = _run(["docker", "info"])
    if info.returncode != 0:
        _fail("Docker daemon is not reachable. Start Docker, then re-run `make doctor`.")
    _ok("docker daemon reachable")


def _check_compose_file() -> None:
    result = _run(["docker", "compose", "config", "--quiet"])
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        _fail(f"docker compose config failed: {detail}")
    _ok("docker compose config")


def _check_python_version_files() -> None:
    expected = "3.11.15"
    for path in (".python-version", ".tool-versions"):
        try:
            contents = open(path, encoding="utf-8").read()
        except OSError as exc:
            _fail(f"could not read {path}: {exc}")
        if not re.search(r"\b3\.11\.15\b", contents):
            _fail(f"{path} does not pin {expected}")
    _ok("version files pin python 3.11.15")


def main() -> None:
    print("MemGauge dev environment doctor")
    _check_python()
    _check_python_version_files()
    _check_module("fastapi")
    _check_module("pytest")
    _check_docker()
    _check_compose_file()
    print("DEV DOCTOR: PASS")


if __name__ == "__main__":
    main()

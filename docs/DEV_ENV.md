# Development Environment

MemGauge is pinned to **Python 3.11.x** and Docker Compose. The project uses
`datetime.UTC`, so Python 3.10 and Python 3.12 are not supported for local
development.

## Required Tools

- Python **3.11.15** recommended (`>=3.11,<3.12` required by `pyproject.toml`)
- Docker with Compose v2 (`docker compose ...`)
- `make`

Version manager hints:

- `pyenv` reads `.python-version` (`3.11.15`)
- `asdf` reads `.tool-versions` (`python 3.11.15`)

## Fresh Setup

```bash
python3.11 --version
docker --version
docker compose version

make venv
make doctor
make test-unit
```

If your Python 3.11 binary is not named `python3.11`, pass it explicitly:

```bash
make venv PY311=/path/to/python3.11
```

## Verified Local Commands

No services needed:

```bash
make doctor
make test-unit
make lint
```

Docker-backed:

```bash
make test
make stack-up
make r6-observability
make r7-resilience
```

Full demo path:

```bash
make r1
```

## Troubleshooting

- `make doctor` says Python is wrong: install Python 3.11 and rebuild `.venv`
  with `make venv PY311=<your-python3.11>`.
- `make doctor` cannot import dependencies: run `make venv`.
- Docker daemon is unreachable: start Docker Desktop or your Docker daemon.
- Integration tests conflict with the demo stack: they should not. The test
  compose file uses isolated host ports (`25432`, `27474`, `27687`, `26379`).
- Stale state in the demo stack: run `make reset`, then `make stack-up`.

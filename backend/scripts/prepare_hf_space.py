"""Stage the backend as a Hugging Face Docker Space.

Usage:
    cd backend
    uv run python scripts/prepare_hf_space.py

Then:
    hf auth login
    hf repo create <user>/studbud-api --repo-type space --space_sdk docker
    hf upload <user>/studbud-api .hf-space . --repo-type space

The staging directory contains no .env, tests, storage, or virtualenv.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".hf-space"

FILES = [
    "Dockerfile",
    "docker-entrypoint.sh",
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
    "README.md",
    ".dockerignore",
]
DIRECTORIES = ["src", "migrations"]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    for name in FILES:
        shutil.copy2(ROOT / name, OUT / name)

    for name in DIRECTORIES:
        shutil.copytree(
            ROOT / name,
            OUT / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )

    print(f"Space staged at {OUT}")
    print("Create and upload with:")
    print("  hf repos create <user>/studbud-api --type space --sdk docker --public")
    print(f"  hf upload <user>/studbud-api {OUT} . --repo-type space")
    print("Set secrets and variables in the Space settings before first boot.")


if __name__ == "__main__":
    main()

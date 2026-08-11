"""Build production-ready archives for backend (Python) and frontend (Next.js).

Backend archive `backend-prod.tar.gz` contains only the runtime payload:
- src/, config/, pyproject.toml, uv.lock
- scripts/ (launchers), Dockerfile, .env.example
- README.md

Frontend archive `frontend-prod.tar.gz` contains:
- frontend/.next/ (Next.js production build output)
- frontend/{package.json, package-lock.json, next.config.mjs, postcss.config.mjs,
  eslint.config.js, prettier.config.js, tailwind.config.*, tsconfig.json}
- frontend/app/, components/, hooks/, lib/, public/, assets/, next-env.d.ts

Excluded everywhere: tests/, docs/, .claude/, .superpowers/, __pycache__/,
*.pyc, .pytest_cache/, .env (with secrets), assets/uploads/, assets/reviews/,
assets/results/, logs/, .venv/, frontend/node_modules/, frontend/.next/cache/,
CLAUDE.md, scripts/_private/, *.md.local, .git/, .github/, .vscode/.

Usage:
    python scripts/build_prod.py                 # build + leave archives in dist/
    python scripts/build_prod.py --output DIR    # write into DIR/
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "dist"

BACKEND_INCLUDES = [
    "src",
    "config",
    "policy_packs",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    ".env.example",
    ".dockerignore",
    "README.md",
    "scripts/http_run.sh",
    "scripts/local_run.sh",
    "scripts/setup.sh",
    "scripts/pack.sh",
    "scripts/load_env.py",
    "scripts/load_env.sh",
]

BACKEND_EXCLUDES = {
    ".git", ".github", ".venv", ".pytest_cache", "__pycache__",
    ".claude", ".superpowers", "scripts/_private", "tests", "docs",
    "logs", "node_modules", "frontend", "CLAUDE.md",
}

FRONTEND_INCLUDES = [
    "frontend/.next",
    "frontend/app",
    "frontend/components",
    "frontend/hooks",
    "frontend/lib",
    "frontend/assets",
    "frontend/public",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/next.config.mjs",
    "frontend/next-env.d.ts",
    "frontend/postcss.config.mjs",
    "frontend/eslint.config.js",
    "frontend/prettier.config.js",
    "frontend/components.json",
    "frontend/tsconfig.json",
]

FRONTEND_EXCLUDES = {
    "frontend/node_modules",
    "frontend/.next/cache",
    "frontend/logs",
}


_IGNORE_DIR_NAMES = {
    "__pycache__", "node_modules", ".pytest_cache", ".vite", "logs",
    ".mypy_cache", ".ruff_cache",
}


def _copytree(src: Path, dst: Path, exclude_names: set[str]) -> None:
    """Copy a directory tree, skipping excluded top-level entries."""
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name in exclude_names:
            continue
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", "node_modules",
                ".next/cache", "cache",  # exclude .next/cache from .next copy
            ))
        else:
            shutil.copy2(child, target)


def _copy_files(srcs: list[str], dst_root: Path, exclude_names: set[str]) -> None:
    """Copy specific files/dirs into dst_root.

    Each entry in ``srcs`` is treated as a top-level item: a directory becomes
    ``dst_root/<basename>`` and a file is placed at ``dst_root/<basename>``.
    We deliberately do NOT preserve the relative subpath here, so the staging
    tree mirrors the source's top-level layout (avoids ``dist/frontend/frontend/``
    double prefixes when callers pass ``frontend/...`` entries).
    """
    dst_root.mkdir(parents=True, exist_ok=True)
    for rel in srcs:
        src = ROOT / rel
        if not src.exists():
            print(f"[skip] {rel} (missing)")
            continue
        dst = dst_root / src.name
        if src.is_dir():
            shutil.copytree(
                src, dst,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "node_modules",
                    ".next/cache", "cache",  # exclude .next/cache
                    ".pytest_cache", ".vite", "*.log", "logs",
                    ".mypy_cache", ".ruff_cache",
                ),
            )
        else:
            shutil.copy2(src, dst)
        print(f"[ok]   {rel}")


def build_backend(output_dir: Path) -> Path:
    backend_dir = output_dir / "backend"
    if backend_dir.exists():
        shutil.rmtree(backend_dir)
    backend_dir.mkdir(parents=True)

    print("\n=== Backend files ===")
    _copy_files(BACKEND_INCLUDES, backend_dir, BACKEND_EXCLUDES)

    # Drop anything accidentally left from the excludes set.
    for child in list(backend_dir.iterdir()):
        if child.name in BACKEND_EXCLUDES:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    return backend_dir


def build_frontend(output_dir: Path) -> Path:
    frontend_src = ROOT / "frontend"
    if not (frontend_src / ".next").exists():
        print("\n=== Building Next.js production bundle ===")
        env = os.environ.copy()
        env.setdefault("NODE_ENV", "production")
        result = subprocess.run(
            ["npm", "run", "build"], cwd=str(frontend_src), env=env, check=False
        )
        if result.returncode != 0:
            sys.exit(f"frontend build failed (exit={result.returncode})")
    else:
        print("\n=== Skipping npm build (frontend/.next already exists) ===")

    frontend_dir = output_dir / "frontend"
    if frontend_dir.exists():
        shutil.rmtree(frontend_dir)
    frontend_dir.mkdir(parents=True)

    print("\n=== Frontend files ===")
    _copy_files(FRONTEND_INCLUDES, frontend_dir, FRONTEND_EXCLUDES)

    for child in list(frontend_dir.iterdir()):
        if child.name in FRONTEND_EXCLUDES:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    return frontend_dir


def make_archive(src_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()
    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(src_dir, arcname=src_dir.name)
    print(f"[archive] {archive_path} ({archive_path.stat().st_size // 1024} KiB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build production archives.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--skip-frontend", action="store_true",
                        help="Skip frontend build/archive (backend only)")
    parser.add_argument("--skip-archive", action="store_true",
                        help="Skip tarring (just copy files)")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {args.output}")

    backend_dir = build_backend(args.output)

    frontend_dir = None
    if not args.skip_frontend:
        frontend_dir = build_frontend(args.output)

    if args.skip_archive:
        print(f"\nDone. Files written under {args.output}")
        return 0

    backend_archive = args.output / "backend-prod.tar.gz"
    make_archive(backend_dir, backend_archive)

    if frontend_dir is not None:
        frontend_archive = args.output / "frontend-prod.tar.gz"
        make_archive(frontend_dir, frontend_archive)

    # Remove the staging dirs after archiving so dist/ only contains the .tar.gz.
    shutil.rmtree(backend_dir)
    if frontend_dir is not None:
        shutil.rmtree(frontend_dir)

    print(f"\nDone. Archives in {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
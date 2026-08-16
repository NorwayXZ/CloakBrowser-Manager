"""Start CloakBrowser Manager natively on Windows or macOS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
SETUP_MARKER = VENV_DIR / ".manager-setup.json"
FRONTEND_DIR = ROOT / "frontend"
SERVER_URL = "http://127.0.0.1:8080"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_setup_state() -> dict[str, str]:
    try:
        value = json.loads(SETUP_MARKER.read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _run(command: list[str], cwd: Path = ROOT) -> None:
    print(f"[setup] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _manager_data_dir() -> Path:
    from backend.runtime import resolve_runtime

    return resolve_runtime().data_dir


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _cleanup_installation(*, purge_data: bool) -> None:
    targets = [
        VENV_DIR,
        VENV_DIR / ".manager-setup.json",
        FRONTEND_DIR / "node_modules",
        FRONTEND_DIR / "dist",
        FRONTEND_DIR / ".vite",
        FRONTEND_DIR / ".cache",
        ROOT / ".pytest_cache",
        ROOT / "__pycache__",
        ROOT / "backend" / "__pycache__",
        ROOT / "frontend" / "__pycache__",
    ]
    for target in targets:
        if target.exists():
            print(f"[remove] {target}", flush=True)
            _remove_path(target)

    if purge_data:
        data_dir = _manager_data_dir()
        if data_dir.exists():
            print(f"[remove] {data_dir}", flush=True)
            _remove_path(data_dir)


def _print_data_locations() -> None:
    data_dir = _manager_data_dir()
    print(f"[info] Manager data directory: {data_dir}", flush=True)
    print(f"[info] Profiles database: {data_dir / 'profiles.db'}", flush=True)
    print(f"[info] Profile folders: {data_dir / 'profiles'}", flush=True)


def _ensure_environment() -> Path:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required")
    if sys.platform not in {"win32", "darwin"}:
        raise RuntimeError(
            "Native Manager supports Windows and macOS; use Docker on Linux"
        )

    python = _venv_python()
    if not python.exists():
        print("[setup] Creating Python environment", flush=True)
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    state = _load_setup_state()
    requirements = ROOT / "backend" / "requirements.txt"
    requirements_hash = _file_hash(requirements)
    if state.get("requirements") != requirements_hash:
        _run([
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(requirements),
        ])
        state["requirements"] = requirements_hash

    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("Node.js 18 or newer is required to build the Manager UI")

    package_lock = FRONTEND_DIR / "package-lock.json"
    frontend_hash = _file_hash(package_lock)
    if state.get("frontend") != frontend_hash or not (FRONTEND_DIR / "node_modules").exists():
        _run([npm, "ci"], cwd=FRONTEND_DIR)
        state["frontend"] = frontend_hash

    source_mtime = max(
        path.stat().st_mtime
        for path in (FRONTEND_DIR / "src").rglob("*")
        if path.is_file()
    )
    index_path = FRONTEND_DIR / "dist" / "index.html"
    if not index_path.exists() or index_path.stat().st_mtime < source_mtime:
        _run([npm, "run", "build"], cwd=FRONTEND_DIR)

    SETUP_MARKER.write_text(json.dumps(state, indent=2))
    return python


def _ensure_server_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.bind(("127.0.0.1", 8080))
        except OSError as exc:
            raise RuntimeError(
                "Port 8080 is already in use; stop the existing Manager or service"
            ) from exc


def _open_when_ready() -> None:
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{SERVER_URL}/api/status", timeout=0.5):
                webbrowser.open(SERVER_URL)
                return
        except OSError:
            time.sleep(0.1)
    print(f"[error] Manager did not become ready at {SERVER_URL}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the local runtime files while keeping browser profile data",
    )
    parser.add_argument(
        "--purge-data",
        action="store_true",
        help="Also remove the Manager profile data directory",
    )
    args = parser.parse_args()

    if args.uninstall:
        try:
            _cleanup_installation(purge_data=args.purge_data)
            _print_data_locations()
        except (OSError, RuntimeError) as exc:
            print(f"[error] {exc}", file=sys.stderr, flush=True)
            return 1
        print("[done] CloakBrowser Manager uninstalled", flush=True)
        return 0

    try:
        python = _ensure_environment()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1

    try:
        _ensure_server_port_available()
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1

    env = {**os.environ, "CLOAKBROWSER_MANAGER_RUNTIME": "native"}
    print(f"[start] CloakBrowser Manager: {SERVER_URL}", flush=True)
    _print_data_locations()
    threading.Thread(target=_open_when_ready, daemon=True).start()
    process = subprocess.Popen(
        [
            str(python), "-m", "uvicorn", "backend.main:app",
            "--host", "127.0.0.1", "--port", "8080",
        ],
        cwd=ROOT,
        env=env,
    )
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())

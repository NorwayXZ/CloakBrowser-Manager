"""One-click update for the packaged apps (macOS .app, Windows installer).

The running app cannot replace its own files, so the update is split:

1. Inside the app: pick the release asset for this computer, download it,
   verify its SHA-256 (GitHub's asset digest, else the release's
   SHA256SUMS.txt), and prepare the new version.
2. A small detached script waits for the app to quit, swaps in the new
   version and starts it. On macOS it keeps the previous bundle and puts it
   back if the new one does not answer within 90 seconds.

A ``pending.json`` note records the target version; whichever version starts
next compares it with its own and reports success or failure in the panel.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import ssl
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

HEALTH_TIMEOUT_SECONDS = 90
QUIT_TIMEOUT_SECONDS = 120
CHECKSUMS_NAME = "SHA256SUMS.txt"
MOUNT_DIR_NAME = "mount"
PACKAGE_SUFFIXES = (".dmg", ".exe", ".partial")
PENDING_NAME = "pending.json"
SCRIPT_LOG_NAME = "update.log"


class UpdateError(RuntimeError):
    """The update cannot go ahead; the message is shown to the user."""


@dataclass(frozen=True)
class UpdatePlan:
    version: str
    asset_name: str
    url: str
    size: int
    sha256: str


def updates_dir(data_dir: Path) -> Path:
    return data_dir / "updates"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(url: str, timeout: float = 30):
    request = urllib.request.Request(url, headers={"User-Agent": "CloakBrowser-Manager"})
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


def _fetch_text(url: str) -> str:
    with _open(url) as response:
        return response.read().decode("utf-8", "replace")


def parse_checksums(text: str) -> dict[str, str]:
    """``sha256sum`` output: "<hex>  <name>" (a leading "*" marks binary mode)."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            sums[parts[1].lstrip("*").strip()] = parts[0].lower()
    return sums


def plan_update(
    release: dict,
    keyword: str,
    *,
    fetch_text: Callable[[str], str] = _fetch_text,
) -> UpdatePlan:
    """The asset for this computer and the checksum it must match."""
    version = str(release.get("tag_name") or "").lstrip("v")
    assets = release.get("assets") or []
    asset = next((a for a in assets if keyword in str(a.get("name", "")).lower()), None)
    if not version or asset is None:
        raise UpdateError("最新版本里没有适合这台电脑的安装包。")
    name = str(asset["name"])
    sha = ""
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:"):
        sha = digest.split(":", 1)[1].lower()
    if not sha:
        sums_asset = next((a for a in assets if a.get("name") == CHECKSUMS_NAME), None)
        if sums_asset is not None:
            sha = parse_checksums(fetch_text(str(sums_asset["browser_download_url"]))).get(name, "")
    if len(sha) != 64:
        raise UpdateError("这个版本没有发布校验码，为了安全不自动安装，请手动下载。")
    return UpdatePlan(
        version=version,
        asset_name=name,
        url=str(asset["browser_download_url"]),
        size=int(asset.get("size") or 0),
        sha256=sha,
    )


def download_verified(
    plan: UpdatePlan,
    dest_dir: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    opener: Callable[[str], object] = _open,
) -> Path:
    """Download the asset, checking its SHA-256 before it gets its real name."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / plan.asset_name
    partial = dest_dir / f"{plan.asset_name}.partial"
    digest = hashlib.sha256()
    done = 0
    try:
        with opener(plan.url) as response, open(partial, "wb") as handle:  # type: ignore[attr-defined]
            while chunk := response.read(1024 * 256):
                handle.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, plan.size)
        if digest.hexdigest() != plan.sha256:
            raise UpdateError("下载的安装包和发布的校验码对不上，已丢弃，没有安装。")
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


# ── macOS ───────────────────────────────────────────────────────────────────


def macos_install_target(running_app: Path, *, folders: tuple[Path, ...] | None = None) -> Path:
    """Where the app really lives; a quarantined app runs from a read-only copy."""
    if "AppTranslocation" not in running_app.parts:
        return running_app
    for folder in folders or (Path("/Applications"), Path.home() / "Applications"):
        candidate = folder / running_app.name
        if candidate.exists():
            return candidate
    raise UpdateError("找不到应用在「应用程序」里的位置，请手动下载安装。")


def macos_stage_app(
    dmg: Path,
    work_dir: Path,
    target_app: Path,
    version: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    """Copy the new .app out of the DMG next to the installed one (same volume)."""
    parent = target_app.parent
    if not os.access(parent, os.W_OK):
        raise UpdateError(f"没有权限写入 {parent}，请手动下载安装。")
    mount = work_dir / MOUNT_DIR_NAME
    mount.mkdir(parents=True, exist_ok=True)
    attach = runner(
        ["hdiutil", "attach", str(dmg), "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mount)],
        capture_output=True, text=True,
    )
    if attach.returncode != 0:
        raise UpdateError(f"打开安装包失败：{attach.stderr.strip() or attach.returncode}")
    try:
        apps = [p for p in mount.iterdir() if p.suffix == ".app"]
        if len(apps) != 1:
            raise UpdateError("安装包里没有找到应用。")
        staged = parent / f".{target_app.stem}.update-{version}.app"
        shutil.rmtree(staged, ignore_errors=True)
        copy = runner(["ditto", str(apps[0]), str(staged)], capture_output=True, text=True)
        if copy.returncode != 0:
            raise UpdateError(f"复制新版本失败：{copy.stderr.strip() or copy.returncode}")
    finally:
        runner(["hdiutil", "detach", str(mount), "-force"], capture_output=True, text=True)
    return staged


def macos_swap_script(
    *,
    pid: int,
    target_app: Path,
    staged_app: Path,
    backup_app: Path,
    version: str,
    port: int,
    log_path: Path,
    health_timeout: int = HEALTH_TIMEOUT_SECONDS,
    open_command: str = "open",
) -> str:
    """Shell script: wait for the app to quit, swap bundles, verify, roll back on failure."""
    q = shlex.quote
    launch = f"{open_command} " if open_command else ""
    status = f"http://127.0.0.1:{port}/api/status"
    executable = f"{target_app}/Contents/MacOS/"
    return f"""#!/bin/sh
exec >>{q(str(log_path))} 2>&1
echo "$(date) update to {version}: waiting for pid {pid}"
i=0
while kill -0 {pid} 2>/dev/null; do
  i=$((i+1)); [ $i -gt {QUIT_TIMEOUT_SECONDS} ] && echo "old app did not quit" && exit 1
  sleep 1
done
rm -rf {q(str(backup_app))}
if ! mv {q(str(target_app))} {q(str(backup_app))}; then
  echo "cannot move the current app aside (macOS App Management?)"; rm -rf {q(str(staged_app))}
  {launch}{q(str(target_app))}; exit 1
fi
if ! mv {q(str(staged_app))} {q(str(target_app))}; then
  echo "cannot move the new app in; restoring"; mv {q(str(backup_app))} {q(str(target_app))}
  {launch}{q(str(target_app))}; exit 1
fi
xattr -dr com.apple.quarantine {q(str(target_app))} 2>/dev/null
{launch}{q(str(target_app))}
i=0
while [ $i -lt {health_timeout} ]; do
  if curl -fsS --max-time 2 {q(status)} 2>/dev/null | grep -q '"app_version":"{version}"'; then
    echo "$(date) {version} is running"; exit 0
  fi
  i=$((i+1)); sleep 1
done
echo "$(date) {version} did not start; rolling back"
pkill -f {q(executable)} 2>/dev/null; sleep 3
rm -rf {q(str(target_app))}.failed
mv {q(str(target_app))} {q(str(target_app))}.failed
mv {q(str(backup_app))} {q(str(target_app))}
{launch}{q(str(target_app))}
exit 1
"""


# ── Windows ─────────────────────────────────────────────────────────────────


def windows_install_script(*, pid: int, installer: Path, log_path: Path) -> str:
    """cmd script: wait for the app to quit, then run the installer silently.

    The installer starts the new version itself after a silent install.
    """
    return (
        "@echo off\r\n"
        f'echo %date% %time% waiting for pid {pid} >> "{log_path}"\r\n'
        "set /a n=0\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul || goto install\r\n'
        "set /a n+=1\r\n"
        f"if %n% gtr {QUIT_TIMEOUT_SECONDS} goto end\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        "goto wait\r\n"
        ":install\r\n"
        f'"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /LOG="{log_path}.installer.txt"\r\n'
        f'echo %date% %time% installer exit %errorlevel% >> "{log_path}"\r\n'
        ":end\r\n"
    )


# ── Shared ──────────────────────────────────────────────────────────────────


def write_pending(data_dir: Path, *, from_version: str | None, to_version: str) -> None:
    path = updates_dir(data_dir) / PENDING_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "from": from_version,
        "to": to_version,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }))


def clean_after_success(work_dir: Path) -> list[Path]:
    """Drop the downloaded package and the empty mount point once the update landed.

    The log and scripts stay for reference; the previous app bundle lives next
    to the installed app and is not touched here.
    """
    removed: list[Path] = []
    if not work_dir.is_dir():
        return removed
    for path in work_dir.iterdir():
        if path.is_file() and path.name.endswith(PACKAGE_SUFFIXES):
            path.unlink(missing_ok=True)
            removed.append(path)
    mount = work_dir / MOUNT_DIR_NAME
    if mount.is_dir():
        try:
            mount.rmdir()  # only succeeds when empty, i.e. nothing is still mounted there
            removed.append(mount)
        except OSError:
            pass
    return removed


def settle_pending(data_dir: Path, running_version: str | None) -> dict | None:
    """After a restart: did the update land? Clears the note and returns the outcome."""
    path = updates_dir(data_dir) / PENDING_NAME
    if not path.is_file():
        return None
    try:
        pending = json.loads(path.read_text())
    except (OSError, ValueError):
        pending = {}
    path.unlink(missing_ok=True)
    target = pending.get("to")
    if not target or not running_version:
        return None
    if running_version == target:
        try:
            clean_after_success(updates_dir(data_dir))
        except OSError:
            pass  # leftovers are harmless; the next update clears the folder anyway
    log = updates_dir(data_dir) / SCRIPT_LOG_NAME
    reason = None
    if running_version != target and log.is_file():
        lines = [line for line in log.read_text(errors="replace").splitlines() if line.strip()]
        reason = lines[-1] if lines else None
    return {
        "ok": running_version == target,
        "from": pending.get("from"),
        "to": target,
        "running": running_version,
        "reason": reason,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def launch_detached(command: list[str]) -> None:
    """Start the update script so that it outlives this process."""
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def plan_as_dict(plan: UpdatePlan) -> dict:
    return asdict(plan)

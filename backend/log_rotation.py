"""Keep the app's log file from growing without limit.

The packaged apps point stdout and stderr of the whole process (and the
Xray / Chromium children that inherit them) at one manager.log opened in
append mode. A rename-based rotation would leave those writers on the old
file, so the file is rotated by copy-and-truncate instead: append-mode writers
carry on at the new end. Lines written in the instant between the copy and
the truncate can be lost, which is the usual price of this method.
"""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

logger = logging.getLogger("cloakbrowser.desktop.logs")

MAX_BYTES = 10 * 1024 * 1024
KEEP = 5
CHECK_SECONDS = 60


def rotate_log(path: Path, max_bytes: int = MAX_BYTES, keep: int = KEEP) -> bool:
    """Shift manager.log to .1 (and .1 to .2, ...) once it exceeds max_bytes. Returns whether it rotated."""
    try:
        if keep < 1 or not path.is_file() or path.stat().st_size <= max_bytes:
            return False
        oldest = path.with_name(f"{path.name}.{keep}")
        oldest.unlink(missing_ok=True)
        for index in range(keep - 1, 0, -1):
            source = path.with_name(f"{path.name}.{index}")
            if source.exists():
                source.replace(path.with_name(f"{path.name}.{index + 1}"))
        shutil.copyfile(path, path.with_name(f"{path.name}.1"))
        with open(path, "r+b") as handle:
            handle.truncate(0)
        return True
    except OSError as exc:
        # Logging must never stop the app: try again at the next check.
        logger.warning("Could not rotate %s: %s", path, exc)
        return False


def start_rotation(path: Path, max_bytes: int = MAX_BYTES, keep: int = KEEP, interval: float = CHECK_SECONDS) -> threading.Thread:
    """Check the size now and then for as long as the app runs."""
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(interval):
            if rotate_log(path, max_bytes, keep):
                logger.info("Rotated %s", path.name)

    thread = threading.Thread(target=watch, name="log-rotation", daemon=True)
    thread.stop = stop  # type: ignore[attr-defined]
    thread.start()
    return thread

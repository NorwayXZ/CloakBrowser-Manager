"""The computer's own screen size, for profiles whose screen follows it.

Detection sites compare ``screen.width``/``height`` with CSS media queries
(``device-width``/``device-height``). The kernel only spoofs the former, so a
screen that differs from the real display is reported as an inconsistent
fingerprint. Profiles that follow the real display avoid the mismatch.
"""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

COREGRAPHICS_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
MIN_WIDTH = 320
MIN_HEIGHT = 240


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def _macos_primary_screen() -> tuple[float, float]:
    cg = ctypes.CDLL(COREGRAPHICS_PATH)
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    cg.CGDisplayBounds.restype = _CGRect
    # The main display carries the menu bar; new browser windows open on it.
    # Its bounds are in points, which is what the browser reports as screen size.
    rect = cg.CGDisplayBounds(cg.CGMainDisplayID())
    return rect.size.width, rect.size.height


def primary_screen_size() -> tuple[int, int] | None:
    """Logical size of the screen new browser windows open on, if known."""
    if sys.platform != "darwin":
        return None
    try:
        width, height = _macos_primary_screen()
    except (OSError, AttributeError, ValueError) as exc:
        logger.warning("Could not read the screen size: %s", exc)
        return None
    size = int(round(width)), int(round(height))
    if size[0] < MIN_WIDTH or size[1] < MIN_HEIGHT:
        return None
    return size
